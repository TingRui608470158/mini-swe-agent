import subprocess
from datetime import date
from pathlib import Path

import pytest

from minisweagent.run.extra.vault_audit import is_due, parse_note
from minisweagent.run.extra.vault_check import (
    check_conflicts,
    check_deletions,
    check_frontmatter,
    check_placement,
    load_settings,
)

NOTE = "---\nauthor: a\ndate: 2026-01-01\nupdated: 2026-01-01\ntags: [x]\n---\n# hi\n"


def commit(vault: Path, author: str, message: str, **files: str | None):
    for name, content in files.items():
        if content is None:
            (vault / name).unlink()
        else:
            (vault / name).parent.mkdir(parents=True, exist_ok=True)
            (vault / name).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=vault, check=True)
    subprocess.run(
        ["git", "-c", f"user.name={author}", "-c", "user.email=a@b.c", "commit", "-q", "-m", message],
        cwd=vault,
        check=True,
    )


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", tmp_path], check=True)
    commit(
        tmp_path,
        "RayLian",
        "init",
        **{
            "README.md": NOTE,
            "20-areas/vault-management/audit/settings.md": NOTE.replace(
                "---\n#", "members:\n  Ray: [RayLian]\n  Bob: [bob]\n---\n#"
            ),
            "personal/Ray/weekly/w1.md": NOTE + "see [[gone]]\n",
            "personal/Ray/gone.md": NOTE,
            "personal/Ray/long.md": NOTE + "\n".join(f"line {i}" for i in range(30)),
            "personal/Bob/notes/x.md": "no frontmatter",
            "personal/Bob/notes/x 1.md": "dup",
            "personal/Bob/notes/img.png": "",
            "templates/t.md": "---\nauthor:\n---\n",
            "10-projects/proj-a/knowledge/k.md": NOTE,
            "stray.canvas": "{}",
            "script.py": "print(1)",
        },
    )
    return tmp_path


def test_deletions_and_broken_links(vault: Path):
    commit(vault, "bob", "cleanup", **{"personal/Ray/gone.md": None, "personal/Ray/long.md": NOTE})
    findings = check_deletions(vault, load_settings(vault), "1.day")
    assert [f["type"] for f in findings] == ["deleted", "content_mostly_removed"]
    assert findings[0]["path"] == "personal/Ray/gone.md" and findings[0]["author"] == "bob"
    assert findings[0]["broken_links_from"] == ["personal/Ray/weekly/w1.md"]
    assert findings[1]["path"] == "personal/Ray/long.md" and findings[1]["deleted"] >= 20


def test_conflicts(vault: Path):
    commit(vault, "bob", "edit", **{"README.md": NOTE + "<<<<<<< HEAD\na\n=======\nb\n>>>>>>> theirs\n"})
    findings = check_conflicts(vault, load_settings(vault), "1.day")
    assert {(f["type"], f["path"]) for f in findings} == {
        ("duplicate_file", "personal/Bob/notes/x 1.md"),
        ("conflict_markers", "README.md"),
        ("multi_author_edit", "README.md"),
    }
    assert next(f for f in findings if f["type"] == "multi_author_edit")["authors"] == ["Bob", "Ray"]


def test_frontmatter(vault: Path):
    assert {(f["type"], f["path"]) for f in check_frontmatter(vault, load_settings(vault))} == {
        ("missing_frontmatter", "personal/Bob/notes/x.md"),
        ("missing_frontmatter", "personal/Bob/notes/x 1.md"),
    }


def test_placement(vault: Path):
    findings = check_placement(vault, load_settings(vault), "1.day")
    assert {(f["type"], f["path"]) for f in findings} == {
        ("file_in_vault_root", "stray.canvas"),
        ("media_outside_assets", "personal/Bob/notes/img.png"),
        ("media_bad_name", "personal/Bob/notes/img.png"),
        ("code_file_in_vault", "script.py"),
        ("project_missing_index", "10-projects/proj-a/"),
        ("edited_other_members_folder", "personal/Bob/notes/x.md"),
        ("edited_other_members_folder", "personal/Bob/notes/x 1.md"),
        ("edited_other_members_folder", "personal/Bob/notes/img.png"),
    }


@pytest.mark.parametrize(
    ("schedule", "today", "expected"),
    [
        ("daily", date(2026, 9, 26), True),
        ("weekdays", date(2026, 9, 26), False),
        ("weekdays", date(2026, 9, 25), True),
        ("mon,fri", date(2026, 9, 25), True),
        ("mon,fri", date(2026, 9, 24), False),
        ("1,15", date(2026, 9, 15), True),
        ("1,15", date(2026, 9, 16), False),
    ],
)
def test_is_due(schedule: str, today: date, expected: bool):
    assert is_due(schedule, today) == expected


def test_parse_note(tmp_path: Path):
    (tmp_path / "t.md").write_text("---\nschedule: mon\nenabled: false\n---\n\nDo the --- thing\n", encoding="utf-8")
    assert parse_note(tmp_path / "t.md") == ({"schedule": "mon", "enabled": False}, "Do the --- thing")

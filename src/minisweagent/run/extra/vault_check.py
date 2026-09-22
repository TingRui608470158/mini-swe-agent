"""Deterministic checks for a git-backed Obsidian vault. Prints JSON findings that the
vault_audit agent (see run/extra/vault_audit.py) investigates and turns into a report.

Settings (member mapping, thresholds) are read from the frontmatter of
`<vault>/20-areas/vault-management/audit/settings.md` so admins can edit them in Obsidian.
"""

import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import typer
import yaml

app = typer.Typer(help=__doc__)

SETTINGS_NOTE = "20-areas/vault-management/audit/settings.md"
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4", ".mov"}
CODE_SUFFIXES = {".py", ".js", ".ts", ".cpp", ".c", ".h", ".sh", ".ipynb"}
DEFAULT_SETTINGS = {
    "members": {},
    "required_keys": ["author", "date", "updated", "tags"],
    "media_pattern": r"^[A-Za-z]+-\d{4}[wW]\d{2}-",
    "inbox_max_days": 14,
    "ignore": ["templates/"],
}
COMMIT_HEADER = re.compile(r"^([0-9a-f]{7,})\|(.*)\|(\d{4}-\d{2}-\d{2})$")

VaultOpt = typer.Option(Path("."), "--vault", help="Vault root (defaults to cwd)")
SinceOpt = typer.Option("1.day", "--since", help="git --since spec, e.g. 1.day, 2025-01-01")


def git(vault: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.quotepath=off", *args],
        cwd=vault,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout


def frontmatter(text: str) -> dict | None:
    if not text.startswith("---"):
        return None
    parts = text.split("\n---", 2)
    return yaml.safe_load(parts[0][3:]) or {} if len(parts) >= 2 else None


def load_settings(vault: Path) -> dict:
    note = vault / SETTINGS_NOTE
    return DEFAULT_SETTINGS | (frontmatter(note.read_text(encoding="utf-8")) or {} if note.exists() else {})


def tracked(vault: Path, *pathspecs: str) -> list[str]:
    return [
        p for p in git(vault, "ls-files", "-z", "--", *pathspecs).split("\0") if p and not p.startswith(".obsidian/")
    ]


def member_of(author: str, settings: dict) -> str:
    """Map a git author name to the folder name under personal/, falling back to the raw author."""
    return next((name for name, aliases in settings["members"].items() if author in aliases), author)


def commits_with_files(vault: Path, since: str, *log_args: str) -> list[tuple[dict, list[str]]]:
    """Parse `git log --name-status`-style output into (commit, [status\\tpath]) pairs."""
    result, current = [], None
    for line in git(vault, "log", f"--since={since}", "--format=%h|%an|%ad", "--date=short", *log_args).splitlines():
        if m := COMMIT_HEADER.match(line):
            current = {"commit": m[1], "author": m[2], "date": m[3]}
            result.append((current, []))
        elif line.strip() and current is not None:
            result[-1][1].append(line)
    return result


def ignored(path: str, settings: dict) -> bool:
    return path.startswith(".obsidian/") or any(path.startswith(prefix) for prefix in settings["ignore"])


def check_deletions(vault: Path, settings: dict, since: str) -> list[dict]:
    findings = []
    notes = tracked(vault, "*.md")
    for commit, lines in commits_with_files(vault, since, "--diff-filter=D", "--name-status"):
        for line in lines:
            path = line.split("\t", 1)[1]
            if ignored(path, settings):
                continue
            stem = Path(path).stem
            referencing = [n for n in notes if f"[[{stem}" in (vault / n).read_text(encoding="utf-8", errors="replace")]
            findings.append({"type": "deleted", "path": path, "broken_links_from": referencing, **commit})
    for commit, lines in commits_with_files(vault, since, "--numstat", "--diff-filter=M"):
        for line in lines:
            added, deleted, path = line.split("\t", 2)
            if (
                added.isdigit()
                and int(deleted) >= 20
                and int(added) <= int(deleted) * 0.2
                and not ignored(path, settings)
            ):
                findings.append(
                    {
                        "type": "content_mostly_removed",
                        "path": path,
                        "added": int(added),
                        "deleted": int(deleted),
                        **commit,
                    }
                )
    return findings


def check_conflicts(vault: Path, settings: dict, since: str) -> list[dict]:
    findings = []
    files = tracked(vault)
    for path in files:
        original = re.sub(r"( \d+|\.orig|\.sync-conflict[^/]*)(\.\w+)$", r"\2", path)
        if original != path and original in files and not ignored(path, settings):
            findings.append({"type": "duplicate_file", "path": path, "original": original})
        if path.endswith(".md") and re.search(
            r"^(<<<<<<< |>>>>>>> )", (vault / path).read_text(encoding="utf-8", errors="replace"), re.M
        ):
            findings.append({"type": "conflict_markers", "path": path})
    findings += [{"type": "merge_commit", **commit} for commit, _ in commits_with_files(vault, since, "--merges")]
    authors = defaultdict(set)
    for commit, lines in commits_with_files(vault, since, "--name-only", "--no-merges"):
        for path in lines:
            authors[path].add(member_of(commit["author"], settings))
    findings += [
        {"type": "multi_author_edit", "path": p, "authors": sorted(a)}
        for p, a in authors.items()
        if len(a) > 1 and p in files and not ignored(p, settings)
    ]
    return findings


def check_frontmatter(vault: Path, settings: dict) -> list[dict]:
    findings = []
    for path in tracked(vault, "*.md"):
        if ignored(path, settings):
            continue
        fm = frontmatter((vault / path).read_text(encoding="utf-8", errors="replace"))
        if fm is None:
            findings.append({"type": "missing_frontmatter", "path": path})
        elif missing := [k for k in settings["required_keys"] if not fm.get(k)]:
            findings.append({"type": "empty_frontmatter_keys", "path": path, "keys": missing})
    return findings


def check_placement(vault: Path, settings: dict, since: str) -> list[dict]:
    findings = []
    files = tracked(vault)
    for path in files:
        p = Path(path)
        if len(p.parts) == 1 and p.suffix in {".md", ".canvas", ".base"} and p.name != "README.md":
            findings.append({"type": "file_in_vault_root", "path": path})
        if p.suffix.lower() in MEDIA_SUFFIXES:
            if p.parent.name != "assets":
                findings.append({"type": "media_outside_assets", "path": path})
            if not re.match(settings["media_pattern"], p.name):
                findings.append({"type": "media_bad_name", "path": path, "expected": settings["media_pattern"]})
        if p.suffix.lower() in CODE_SUFFIXES:
            findings.append({"type": "code_file_in_vault", "path": path})
        if p.parts[0] == "00-inbox" and p.suffix == ".md" and p.name != "README.md":
            last = date.fromisoformat(git(vault, "log", "-1", "--format=%ad", "--date=short", "--", path).strip())
            if last < date.today() - timedelta(days=settings["inbox_max_days"]):
                findings.append({"type": "inbox_stale", "path": path, "last_commit": str(last)})
    for project_dir in {Path(f).parts[1] for f in files if f.startswith("10-projects/") and len(Path(f).parts) > 2}:
        if f"10-projects/{project_dir}.md" not in files:
            findings.append(
                {
                    "type": "project_missing_index",
                    "path": f"10-projects/{project_dir}/",
                    "expected": f"10-projects/{project_dir}.md",
                }
            )
    for commit, lines in commits_with_files(vault, since, "--name-only", "--no-merges"):
        for path in lines:
            parts = Path(path).parts
            if parts[0] == "personal" and len(parts) > 2 and member_of(commit["author"], settings) != parts[1]:
                findings.append({"type": "edited_other_members_folder", "path": path, "owner": parts[1], **commit})
    return findings


@app.command()
def deletions(vault: Path = VaultOpt, since: str = SinceOpt):
    """Deleted notes (with notes that still link to them) and files whose content was mostly removed."""
    _print(check_deletions(vault, load_settings(vault), since))


@app.command()
def conflicts(vault: Path = VaultOpt, since: str = SinceOpt):
    """Conflict markers, duplicate/sync-conflict files, merge commits and files edited by several members."""
    _print(check_conflicts(vault, load_settings(vault), since))


@app.command("frontmatter")
def frontmatter_cmd(vault: Path = VaultOpt):
    """Notes without frontmatter or with required keys missing/empty."""
    _print(check_frontmatter(vault, load_settings(vault)))


@app.command()
def placement(vault: Path = VaultOpt, since: str = SinceOpt):
    """Files in the wrong place: vault root, media outside assets/, stale inbox, missing project index, cross-member edits."""
    _print(check_placement(vault, load_settings(vault), since))


@app.command("all")
def all_checks(vault: Path = VaultOpt, since: str = SinceOpt):
    """Run every check and print them grouped by check name."""
    settings = load_settings(vault)
    _print(
        {
            "deletions": check_deletions(vault, settings, since),
            "conflicts": check_conflicts(vault, settings, since),
            "frontmatter": check_frontmatter(vault, settings),
            "placement": check_placement(vault, settings, since),
        }
    )


def _print(data) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    app()

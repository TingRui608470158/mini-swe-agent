"""Run the audit tasks of a git-backed Obsidian vault and commit their reports.

Tasks are notes in `<vault>/20-areas/vault-management/audit/tasks/*.md`: the frontmatter holds
`schedule` (daily | weekdays | mon,thu | 1,15 (days of month)) and `enabled`, the body is the task
prompt. Reports land in `.../audit/reports/<date>-<task>.md`. Meant to run once a day from cron.
"""

import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import typer
import yaml

from minisweagent import global_config_dir
from minisweagent.agents.default import DefaultAgent
from minisweagent.config import get_config_from_spec
from minisweagent.environments.local import LocalEnvironment
from minisweagent.models import get_model
from minisweagent.utils.serialize import recursive_merge

app = typer.Typer(help=__doc__)
AUDIT_DIR = "20-areas/vault-management/audit"


def parse_note(path: Path) -> tuple[dict, str]:
    """Split a note into (frontmatter dict, body)."""
    _, meta, body = path.read_text(encoding="utf-8").split("---", 2)
    return yaml.safe_load(meta) or {}, body.strip()


def is_due(schedule: str, today: date) -> bool:
    if schedule == "daily":
        return True
    if schedule == "weekdays":
        return today.weekday() < 5
    parts = [p.strip().lower() for p in str(schedule).split(",")]
    return today.strftime("%a").lower() in parts or str(today.day) in parts


def git_bash() -> str:
    """Path of the bash.exe that ships with Git for Windows (works whether git.exe is in Git/cmd or Git/mingw64/bin)."""
    git = Path(shutil.which("git"))
    return str(next(p for p in (git.parents[1] / "bin/bash.exe", git.parents[2] / "bin/bash.exe") if p.exists()))


def fallback_report(task_name: str, today: date, exit_status: str) -> str:
    return (
        f"---\nauthor: vault-audit\ndate: {today}\nupdated: {today}\ntags:\n  - audit\ntask: {task_name}\n---\n"
        f"## 摘要\n\n⚠️ 稽核未完成，agent 結束狀態：`{exit_status}`。請管理員查看 trajectory 檔案。\n"
    )


# fmt: off
@app.command()
def main(
    vault: Path = typer.Option(..., "--vault", envvar="VAULT_PATH", help="Vault root (git checkout)"),
    model_name: str | None = typer.Option(None, "-m", "--model", help="Model to use (defaults to MSWEA_MODEL_NAME)"),
    config_spec: list[str] = typer.Option(["vault_audit.yaml"], "-c", "--config", help="Config files or key=value overrides"),
    only: list[str] = typer.Option([], "-t", "--task", help="Only run task notes with these file stems"),
    force: bool = typer.Option(False, "--force", help="Run tasks regardless of their schedule"),
    push: bool = typer.Option(True, help="Commit and push the reports"),
) -> list[Path]:
    # fmt: on
    def git(*args: str):
        subprocess.run(["git", *args], cwd=vault, check=True)

    if push:
        git("pull", "--ff-only")
    config = recursive_merge(*[get_config_from_spec(spec) for spec in config_spec])
    # make `python -m minisweagent...` inside the agent's subshell resolve to this interpreter
    config["environment"]["env"]["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"
    if os.name == "nt":
        config["environment"].setdefault("shell", [git_bash(), "-c"])
    today = date.today()
    reports = []
    for note in sorted((vault / AUDIT_DIR / "tasks").glob("*.md")):
        meta, prompt = parse_note(note)
        if note.stem.startswith("_") or not meta.get("enabled", True) or (only and note.stem not in only):
            continue
        if not (force or is_due(meta.get("schedule", "daily"), today)):
            continue
        report = vault / AUDIT_DIR / "reports" / f"{today}-{note.stem}.md"
        agent = DefaultAgent(
            get_model(model_name, config.get("model", {})),
            LocalEnvironment(cwd=str(vault), **config["environment"]),
            output_path=global_config_dir / "vault_audit" / f"{today}-{note.stem}.traj.json",
            **config["agent"],
        )
        print(f"Running task {note.stem!r} -> {report}")
        result = agent.run(
            prompt, task_name=note.stem, date=str(today), vault=vault.as_posix(), report_path=report.relative_to(vault).as_posix()
        )
        if not report.exists():
            report.write_text(fallback_report(note.stem, today, result.get("exit_status", "")), encoding="utf-8")
        reports.append(report)
    if reports and push:
        git("add", "--", *[str(r) for r in reports])
        git("commit", "-m", f"audit: {today} ({', '.join(r.stem.removeprefix(f'{today}-') for r in reports)})")
        git("push")
    return reports


if __name__ == "__main__":
    app()

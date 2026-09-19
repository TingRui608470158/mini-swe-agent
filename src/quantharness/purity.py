"""Purity checks for strategy files (Stage 2 R2).

R2a: static analysis of the source, never executes it.
R2b/R2c: the strategy runs only in a subprocess (this module's CLI) with a wall-clock limit; the
parent compares sequential, permuted-order and re-imported runs bit for bit.
"""

import ast
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import typer

from quantharness.strategy import load_strategy, sanitize

ALLOWED_IMPORTS = frozenset({"math", "typing"})
FORBIDDEN_CALLS = frozenset(
    "open exec eval compile __import__ getattr setattr delattr globals locals vars input print breakpoint".split()
)


@dataclass
class Violation:
    line: int
    reason: str


def _is_literal(node: ast.expr) -> bool:
    if isinstance(node, ast.Tuple):
        return all(_is_literal(e) for e in node.elts)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _is_literal(node.operand)
    return isinstance(node, ast.Constant)


def _node_violation(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        bad = [a.name for a in node.names if a.name.split(".")[0] not in ALLOWED_IMPORTS]
        return f"import of {bad[0]!r} is not allowed" if bad else None
    if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
        return f"import from {node.module!r} is not allowed"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
        return f"call to {node.func.id!r} is not allowed"
    if isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
        return f"dunder attribute {node.attr!r} is not allowed"
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return "global/nonlocal is not allowed"
    return None


def _module_level_violation(stmt: ast.stmt) -> str | None:
    if isinstance(stmt, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)):
        return None
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
        return None
    if isinstance(stmt, ast.Assign) and all(isinstance(t, ast.Name) for t in stmt.targets) and _is_literal(stmt.value):
        return None
    if (
        isinstance(stmt, ast.AnnAssign)
        and isinstance(stmt.target, ast.Name)
        and (stmt.value is None or _is_literal(stmt.value))
    ):
        return None
    return "module level only allows imports, defs and literal constants"


def _signature_violation(tree: ast.Module) -> Violation | None:
    defs = [s for s in tree.body if isinstance(s, ast.FunctionDef) and s.name == "generate_signal"]
    if len(defs) != 1:
        return Violation(1, "exactly one module-level generate_signal is required")
    args = defs[0].args
    if len(args.posonlyargs) + len(args.args) != 1 or args.vararg or args.kwarg or args.kwonlyargs:
        return Violation(defs[0].lineno, "generate_signal must take exactly one positional argument")
    return None


def check_static(source: str) -> Violation | None:
    """First violation by line number, or None if the source passes R2a."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return Violation(e.lineno or 1, f"syntax error: {e.msg}")
    violations = [Violation(n.lineno, r) for n in ast.walk(tree) if hasattr(n, "lineno") and (r := _node_violation(n))]
    violations += [Violation(s.lineno, r) for s in tree.body if (r := _module_level_violation(s))]
    return min(violations, key=lambda v: v.line) if violations else _signature_violation(tree)


def sandboxed_positions(
    strategy: Path, features: pd.DataFrame, timeout: float, seed: int = 0
) -> np.ndarray | Violation:
    """Run the strategy over `features` in a subprocess; return sanitized positions or why it failed R2b/R2c."""
    with tempfile.TemporaryDirectory() as tmp:
        features_path, out_path = Path(tmp, "features.csv"), Path(tmp, "positions.json")
        features.to_csv(features_path)
        cmd = [
            sys.executable,
            "-m",
            "quantharness.purity",
            str(strategy),
            str(features_path),
            str(out_path),
            "--seed",
            str(seed),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return Violation(0, f"timeout after {timeout}s")
        if proc.returncode != 0:
            return Violation(0, f"strategy raised: {(proc.stderr.strip().splitlines() or ['unknown error'])[-1]}")
        runs = json.loads(out_path.read_text())
    if runs["seq"] != runs["perm"]:
        return Violation(0, "output depends on call order (hidden state)")
    if runs["seq"] != runs["again"]:
        return Violation(0, "output differs across imports (non-deterministic)")
    return np.array(runs["seq"], dtype="float64")


app = typer.Typer()


@app.command()
def run(strategy: Path, features: Path, out: Path, seed: int = 0) -> None:
    """Subprocess side of `sandboxed_positions`."""
    rows = pd.read_csv(features, index_col=0, float_precision="round_trip").to_dict("records")
    generate_signal = load_strategy(strategy)
    seq = [sanitize(generate_signal(dict(row))) for row in rows]
    perm = [0.0] * len(rows)
    for i in np.random.default_rng(seed).permutation(len(rows)):
        perm[i] = sanitize(generate_signal(dict(rows[i])))
    again = [sanitize(load_strategy(strategy)(dict(row))) for row in rows]
    out.write_text(json.dumps({"seq": seq, "perm": perm, "again": again}))


if __name__ == "__main__":
    app()

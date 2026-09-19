"""Strategy interface: `generate_signal(features: dict[str, float]) -> float` (target position in [-1, 1])."""

import importlib.util
import math
from collections.abc import Callable
from pathlib import Path

Strategy = Callable[[dict[str, float]], float]


def load_strategy(path: Path) -> Strategy:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.generate_signal


def sanitize(signal: float) -> float:
    """Non-finite signals mean flat; everything else is clipped to [-1, 1]."""
    return min(max(float(signal), -1.0), 1.0) if math.isfinite(signal) else 0.0

import time

import numpy as np
import pytest

from quantharness.backtest import _positions
from quantharness.features import compute_features
from quantharness.purity import Violation, check_static, sandboxed_positions
from quantharness.strategy import load_strategy
from tests.quantharness.conftest import GOOD_STRATEGY

SIGNAL = "def generate_signal(features):\n    return 0.0\n"


@pytest.mark.parametrize(
    ("source", "line", "fragment"),
    [
        ("import socket\n" + SIGNAL, 1, "socket"),
        ("import requests\n" + SIGNAL, 1, "requests"),
        ("import math\nimport random\n" + SIGNAL, 2, "random"),
        ("import os.path\n" + SIGNAL, 1, "os"),
        ("from time import time\n" + SIGNAL, 1, "time"),
        ("def generate_signal(features):\n    return open('x')\n", 2, "open"),
        ("def generate_signal(features):\n    return __import__('socket')\n", 2, "__import__"),
        ("import math\ndef generate_signal(features):\n    return getattr(math, 'sin')(1)\n", 3, "getattr"),
        ("def generate_signal(features):\n    return features.__dict__\n", 2, "__dict__"),
        ("counter = 0\ndef generate_signal(features):\n    global counter\n    return 0.0\n", 3, "global"),
        ("cache = {}\n" + SIGNAL, 1, "module level"),
        ("results = []\n" + SIGNAL, 1, "module level"),
        ("import math\nX = math.pi\n" + SIGNAL, 2, "module level"),
        ("def helper(features):\n    return 0.0\n", 1, "generate_signal"),
        ("def generate_signal(features, other):\n    return 0.0\n", 1, "one positional"),
        ("def generate_signal(*features):\n    return 0.0\n", 1, "one positional"),
        ("def generate_signal(features)\n    return 0.0\n", 1, "syntax"),
    ],
)
def test_static_analysis_rejects_with_line_and_reason(source, line, fragment):
    violation = check_static(source)
    assert isinstance(violation, Violation) and violation.line == line and fragment in violation.reason


def test_static_analysis_accepts_a_legal_strategy():
    source = '"""Mean reversion."""\nimport math\nfrom typing import Mapping\n\nTHRESHOLD = -0.01\nWEIGHTS = (0.5, -0.5)\nLIMIT: float = 1.0\n\ndef _clip(x: float) -> float:\n    return max(-LIMIT, min(LIMIT, x))\n\ndef generate_signal(features: Mapping[str, float]) -> float:\n    return _clip(features["ret_1"] / THRESHOLD)\n'
    assert check_static(source) is None
    assert check_static(GOOD_STRATEGY) is None


def test_sandbox_matches_in_process_positions(ohlcv, strategy_file):
    path, features = strategy_file(GOOD_STRATEGY), compute_features(ohlcv)
    assert np.array_equal(sandboxed_positions(path, features, timeout=30), _positions(features, load_strategy(path)))


def test_sandbox_catches_state_hidden_from_static_analysis(ohlcv, strategy_file):
    source = "def _mem(x, _s=[0]):\n    _s[0] += 1\n    return x if _s[0] % 2 else -x\n\ndef generate_signal(features):\n    return _mem(0.5)\n"
    assert check_static(source) is None
    violation = sandboxed_positions(strategy_file(source), compute_features(ohlcv), timeout=30)
    assert isinstance(violation, Violation) and "order" in violation.reason


def test_sandbox_enforces_timeout(ohlcv, strategy_file):
    path = strategy_file("def generate_signal(features):\n    while True:\n        pass\n")
    start = time.perf_counter()
    violation = sandboxed_positions(path, compute_features(ohlcv).iloc[:5], timeout=3)
    assert isinstance(violation, Violation) and "timeout" in violation.reason and time.perf_counter() - start < 8


def test_sandbox_reports_strategy_exceptions(ohlcv, strategy_file):
    path = strategy_file("def generate_signal(features):\n    return features['missing']\n")
    violation = sandboxed_positions(path, compute_features(ohlcv), timeout=30)
    assert isinstance(violation, Violation) and "KeyError" in violation.reason

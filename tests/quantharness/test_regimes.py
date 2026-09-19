import numpy as np
import pytest

from quantharness.regimes import label_regimes


def _window_with_return(total: float, n: int = 720) -> np.ndarray:
    return np.full(n, (1 + total) ** (1 / n) - 1)


@pytest.mark.parametrize(("tail", "expected_tail_label"), [(100, ""), (400, "sideways")])
def test_windows_are_labelled_by_benchmark_return_and_short_tails_dropped(tail, expected_tail_label):
    gross = np.concatenate(
        [_window_with_return(0.15), _window_with_return(-0.15), _window_with_return(0.0), np.zeros(tail)]
    )
    labels = label_regimes(gross, window=720, threshold=0.10)
    assert list(labels[::720]) == ["bull", "bear", "sideways", expected_tail_label]
    assert (
        set(labels[:720]) == {"bull"} and set(labels[720:1440]) == {"bear"} and set(labels[1440:2160]) == {"sideways"}
    )
    assert set(labels[2160:]) == {expected_tail_label}

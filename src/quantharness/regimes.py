"""Regime labels for Stage 2 C2: non-overlapping windows classified by the benchmark's compounded return."""

import numpy as np

REGIMES = ("bull", "bear", "sideways")


def label_regimes(gross: np.ndarray, window: int, threshold: float) -> np.ndarray:
    """One label per bar; a trailing window shorter than half `window` is dropped (labelled "")."""
    labels = np.full(len(gross), "", dtype=object)
    for start in range(0, len(gross), window):
        chunk = gross[start : start + window]
        if len(chunk) * 2 < window:
            break
        ret = np.prod(1 + chunk) - 1
        labels[start : start + window] = "bull" if ret > threshold else "bear" if ret < -threshold else "sideways"
    return labels

import json

import pandas as pd

from quantharness.data import load_ohlcv
from quantharness.features import LOOKBACK, compute_features
from quantharness.split import SEGMENTS, body_start, load_bounds, segment, split_bounds
from tests.quantharness.conftest import SYMBOLS, ar1_bars


def test_segments_are_disjoint_ordered_and_cover_everything():
    bars = ar1_bars(1, n=1000)
    bounds = split_bounds(bars)
    bodies = [segment(bars, name, bounds).loc[body_start(name, bounds) :] for name in SEGMENTS]
    assert [len(b) for b in bodies] == [600, 200, 200]
    assert pd.concat(bodies).index.equals(bars.index)
    assert (
        bodies[0].index[-1] < bounds[0] <= bodies[1].index[0] and bodies[1].index[-1] < bounds[1] <= bodies[2].index[0]
    )


def test_segment_files_carry_warmup_and_reproduce_full_series_features(ar1_segments):
    bounds = load_bounds(ar1_segments / "split.json")
    train, validation = (load_ohlcv(ar1_segments / name / "BTCUSDT.csv") for name in ("train", "validation"))
    pd.testing.assert_frame_equal(validation.iloc[:LOOKBACK], train.iloc[-LOOKBACK:], check_freq=False)
    full = pd.concat(
        [train, validation.iloc[LOOKBACK:], load_ohlcv(ar1_segments / "holdout" / "BTCUSDT.csv").iloc[LOOKBACK:]]
    )
    body = compute_features(validation).loc[bounds[0] :]
    pd.testing.assert_frame_equal(
        body, compute_features(full).loc[bounds[0] : bounds[1]].iloc[:-1], check_exact=True, check_freq=False
    )
    assert body.index[0] == bounds[0] and body.index[-1] < bounds[1]


def test_all_symbols_share_the_same_timestamp_bounds(ar1_segments):
    bounds = load_bounds(ar1_segments / "split.json")
    starts = {load_ohlcv(ar1_segments / "validation" / f"{s}.csv").index[LOOKBACK] for s in SYMBOLS}
    assert starts == {bounds[0]}
    assert json.loads((ar1_segments / "split.json").read_text()) == {
        "train_end": bounds[0].isoformat(),
        "validation_end": bounds[1].isoformat(),
    }

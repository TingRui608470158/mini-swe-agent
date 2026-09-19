import numpy as np
import pandas as pd
import pytest

from quantharness.data import OHLCV_COLUMNS
from quantharness.features import FEATURE_NAMES, LOOKBACK, compute_features, compute_features_at


def _bars(**columns: list[float]) -> pd.DataFrame:
    n = len(next(iter(columns.values())))
    return pd.DataFrame(columns, index=pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC", name="ts"))


def test_batch_is_deterministic(ohlcv):
    pd.testing.assert_frame_equal(compute_features(ohlcv), compute_features(ohlcv), check_exact=True)


def test_online_snapshots_match_batch_bit_for_bit(ohlcv):
    batch = compute_features(ohlcv)
    for i in range(len(ohlcv)):
        snapshot = compute_features_at(ohlcv.iloc[: i + 1])
        assert tuple(snapshot) == FEATURE_NAMES
        assert np.array_equal(list(snapshot.values()), batch.iloc[i].to_numpy(), equal_nan=True)
    assert compute_features_at(ohlcv.iloc[-LOOKBACK:]) == compute_features_at(ohlcv)


def test_features_do_not_depend_on_future_bars(ohlcv):
    t = 250
    corrupted = ohlcv.copy()
    corrupted.loc[corrupted.index[t + 1 :], list(OHLCV_COLUMNS)] = np.random.default_rng(1).uniform(
        1, 2, (len(ohlcv) - t - 1, 5)
    )
    pd.testing.assert_frame_equal(
        compute_features(corrupted).iloc[: t + 1], compute_features(ohlcv).iloc[: t + 1], check_exact=True
    )

    def leaky(bars: pd.DataFrame) -> np.ndarray:
        """A feature that peeks one bar ahead; the same check must catch it."""
        return bars["close"].shift(-1).to_numpy()[: t + 1]

    assert not np.array_equal(leaky(corrupted), leaky(ohlcv), equal_nan=True)


@pytest.mark.parametrize(
    ("name", "warmup"),
    [
        ("ret_1", 1),
        ("ret_24", 24),
        ("sma_20_ratio", 19),
        ("sma_50_ratio", 49),
        ("vol_24", 24),
        ("vol_168", 168),
        ("range_1", 0),
        ("vol_ratio_24", 23),
    ],
)
def test_schema_and_warmup(ohlcv, name, warmup):
    features = compute_features(ohlcv)
    assert tuple(features.columns) == FEATURE_NAMES
    assert features[name].dtype == "float64"
    assert features[name].iloc[:warmup].isna().all()
    assert features[name].iloc[warmup:].notna().all()


def test_values_against_hand_computation():
    flat = compute_features_at(
        _bars(open=[4.0] * 200, high=[5.0] * 200, low=[3.0] * 200, close=[4.0] * 200, volume=[2.0] * 200)
    )
    assert flat == dict.fromkeys(FEATURE_NAMES, 0.0) | {"range_1": 0.5, "vol_ratio_24": 1.0}
    spike = compute_features_at(
        _bars(open=[1.0] * 25, high=[1.0] * 25, low=[1.0] * 25, close=[1.0] * 24 + [21.0], volume=[1.0] * 24 + [25.0])
    )
    assert spike["sma_20_ratio"] == 9.5
    assert spike["vol_ratio_24"] == 12.5
    assert spike["ret_1"] == spike["ret_24"] == pytest.approx(np.log(21))
    assert np.isnan(spike["sma_50_ratio"]) and np.isnan(spike["vol_168"])

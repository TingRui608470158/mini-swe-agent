import pandas as pd
import pytest

from quantharness.data import OHLCV_COLUMNS, load_ohlcv, normalize_ohlcv, save_ohlcv
from tests.quantharness.conftest import DUPLICATED_VOLUME, GAP, N_BARS


def test_normalize_sorts_dedupes_and_fills_gaps(raw_ohlcv, ohlcv):
    assert ohlcv.index.equals(pd.date_range("2024-01-01", periods=N_BARS, freq="1h", tz="UTC", name="ts"))
    assert list(ohlcv.columns) == ["open_time", *OHLCV_COLUMNS, "is_gap"]
    assert (ohlcv["open_time"] == (ohlcv.index - pd.Timedelta("1h")).asi8 // 1_000_000).all()
    assert (ohlcv.loc[raw_ohlcv.index[-2:], "volume"] == DUPLICATED_VOLUME).all()
    gaps = ohlcv[ohlcv["is_gap"]]
    assert list(gaps.index) == list(ohlcv.index[GAP])
    assert (gaps[["open", "high", "low", "close"]].eq(ohlcv["close"].iloc[GAP.start - 1], axis=0)).all().all()
    assert (gaps["volume"] == 0).all()


def test_normalize_rejects_off_grid_timestamps(raw_ohlcv):
    shifted = raw_ohlcv.index[:1].append(raw_ohlcv.index[1:] + pd.Timedelta("30min"))
    with pytest.raises(ValueError, match="grid"):
        normalize_ohlcv(raw_ohlcv.set_index(shifted))


def test_save_load_roundtrip_is_exact(ohlcv, tmp_path):
    save_ohlcv(ohlcv, tmp_path / "bars.csv")
    pd.testing.assert_frame_equal(load_ohlcv(tmp_path / "bars.csv"), ohlcv, check_exact=True, check_freq=False)

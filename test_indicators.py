import pandas as pd

from indicators import macd_qualifies


def test_macd_qualifies_when_rising_near_zero_and_above_signal():
    # Smooth upward series creates rising MACD that is above signal and near/above zero.
    idx = pd.date_range("2026-01-01", periods=60, freq="B")
    close = pd.Series([10 + i * 0.03 for i in range(60)], index=idx)
    df = pd.DataFrame({"Close": close})
    ok, details = macd_qualifies(df, idx[-1], near_zero_floor_pct=-0.5, rising_days=3)
    assert ok
    assert details["rising"] is True
    assert details["above_signal"] is True
    assert details["macd_pct"] >= -0.5


def test_macd_rejects_falling_series():
    idx = pd.date_range("2026-01-01", periods=60, freq="B")
    close = pd.Series([12 - i * 0.04 for i in range(60)], index=idx)
    df = pd.DataFrame({"Close": close})
    ok, _ = macd_qualifies(df, idx[-1], near_zero_floor_pct=-0.5, rising_days=3)
    assert not ok

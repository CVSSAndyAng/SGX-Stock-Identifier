from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from data import completed_hourly_bars, latest_market_bars
from scanner import most_recent_triggered_setup
from indicators import macd_qualifies

SG = ZoneInfo('Asia/Singapore')


def make_hourly_pattern():
    idx = pd.date_range('2026-08-27 09:00', periods=12, freq='h')
    return pd.DataFrame(
        {
            'Open':  [10.0,10.1,10.2,10.4,10.3,10.2,10.1,10.2,10.3,10.5,10.7,10.8],
            'High':  [10.2,10.5,10.8,10.7,10.6,10.5,10.4,10.5,10.6,10.8,11.0,11.1],
            'Low':   [9.8, 9.9,10.0,10.1,10.0, 9.9, 9.8, 9.9,10.0,10.2,10.4,10.5],
            'Close': [10.1,10.3,10.6,10.5,10.2,10.0,10.0,10.3,10.4,10.7,10.9,10.9],
        }, index=idx,
    )


def test_hourly_exact_timestamp_filter():
    df = make_hourly_pattern()
    candidates = [s for s in __import__('scanner').find_all_setups(df) if s.status == 'TRIGGERED']
    assert candidates
    dt = candidates[-1].breakout_date
    assert most_recent_triggered_setup(df, [dt], exact_timestamp=True) is not None
    assert most_recent_triggered_setup(df, [pd.Timestamp(dt) + pd.Timedelta(hours=1)], exact_timestamp=True) is None


def test_latest_market_bars_preserves_hours():
    df = make_hourly_pattern()
    bars = latest_market_bars({'X.SI': df}, 3)
    assert bars == list(df.index[-3:])


def test_completed_hourly_bars_drops_current_unfinished_bar():
    idx = pd.DatetimeIndex([
        pd.Timestamp('2026-08-28 09:00', tz=SG),
        pd.Timestamp('2026-08-28 10:00', tz=SG),
    ])
    df = pd.DataFrame({'Open':[1,1], 'High':[2,2], 'Low':[0.5,0.5], 'Close':[1.5,1.5]}, index=idx)
    out = completed_hourly_bars(df, now=datetime(2026,8,28,10,30,tzinfo=SG))
    assert len(out) == 1
    assert out.index[0] == pd.Timestamp('2026-08-28 09:00')


def test_macd_hourly_asof_has_no_future_leakage():
    idx = pd.date_range('2026-08-01 09:00', periods=80, freq='h')
    close = pd.Series([10 + i * 0.01 for i in range(80)], index=idx)
    # Make later bars collapse; exact as-of should still judge the earlier rising state.
    close.iloc[-2:] = [9.0, 8.0]
    df = pd.DataFrame({'Close': close})
    asof = idx[-3]
    ok, details = macd_qualifies(df, asof, near_zero_floor_pct=-0.5, rising_days=3, exact_timestamp=True)
    assert ok
    assert details['rising'] is True

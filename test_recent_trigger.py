import pandas as pd

from scanner import most_recent_triggered_setup


def make_df():
    dates = pd.bdate_range("2026-08-03", periods=12)
    return pd.DataFrame(
        {
            "Open":  [10.0,10.1,10.2,10.4,10.3,10.2,10.1,10.2,10.3,10.5,10.7,10.8],
            "High":  [10.2,10.5,10.8,10.7,10.6,10.5,10.4,10.5,10.6,10.8,11.0,11.1],
            "Low":   [9.8, 9.9,10.0,10.1,10.0, 9.9, 9.8, 9.9,10.0,10.2,10.4,10.5],
            "Close": [10.1,10.3,10.6,10.5,10.2,10.0,10.0,10.3,10.4,10.7,10.9,10.9],
        },
        index=dates,
    )


def test_recent_filter_accepts_breakout_date():
    df = make_df()
    setups = [s for s in __import__('scanner').find_all_setups(df) if s.status == 'TRIGGERED']
    assert setups
    dt = setups[-1].breakout_date
    found = most_recent_triggered_setup(df, [dt])
    assert found is not None
    assert found.breakout_date == dt


def test_recent_filter_rejects_old_breakout():
    df = make_df()
    future_dates = pd.bdate_range("2027-01-01", periods=3)
    found = most_recent_triggered_setup(df, future_dates)
    assert found is None

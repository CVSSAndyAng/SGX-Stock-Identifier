import pandas as pd

from scanner import latest_relevant_setup


def make_df(rows):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="B")
    return pd.DataFrame(rows, index=idx, columns=["Open", "High", "Low", "Close"])


def test_triggered_setup():
    df = make_df([
        [9.0, 10.0, 8.0, 9.5],
        [9.5, 11.0, 8.5, 10.5],
        [10.5, 12.0, 9.0, 11.5],
        [11.2, 11.5, 8.0, 10.8],
        [10.8, 11.0, 7.0, 9.5],
        [9.5, 10.0, 6.0, 8.0],
        [8.5, 10.5, 7.1, 10.0],
        [10.2, 12.5, 7.2, 11.2],
    ])
    setup = latest_relevant_setup(df)
    assert setup is not None
    assert setup.status == "TRIGGERED"
    assert setup.upper_trigger == 11.0
    assert setup.lower_invalidation == 7.0


def test_invalidated_before_breakout():
    df = make_df([
        [9.0, 10.0, 8.0, 9.5],
        [9.5, 11.0, 8.5, 10.5],
        [10.5, 12.0, 9.0, 11.5],
        [11.2, 11.5, 8.0, 10.8],
        [10.8, 11.0, 7.0, 9.5],
        [9.5, 10.0, 6.0, 8.0],
        [6.8, 12.0, 6.5, 11.5],
    ])
    setup = latest_relevant_setup(df)
    assert setup is not None
    assert setup.status == "INVALIDATED"

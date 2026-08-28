from __future__ import annotations

import pandas as pd


def macd_frame(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """Return Close, MACD, Signal and normalized MACD percent for a single ticker."""
    if df is None or df.empty or "Close" not in df.columns:
        return pd.DataFrame(columns=["Close", "MACD", "Signal", "MACD_pct"])

    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = pd.to_numeric(close, errors="coerce").dropna().sort_index()
    if close.empty:
        return pd.DataFrame(columns=["Close", "MACD", "Signal", "MACD_pct"])

    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    macd_pct = (macd / close) * 100.0

    return pd.DataFrame(
        {
            "Close": close,
            "MACD": macd,
            "Signal": signal_line,
            "MACD_pct": macd_pct,
        }
    )


def macd_qualifies(
    df: pd.DataFrame,
    as_of_date: pd.Timestamp,
    near_zero_floor_pct: float = -0.5,
    rising_days: int = 3,
) -> tuple[bool, dict]:
    """Check the user's bullish-near-zero MACD condition on a specific trading date.

    Rules:
    - standard MACD(12,26,9)
    - MACD must rise on each of the last `rising_days` observations
    - MACD must be above the signal line on the as-of date
    - normalized MACD must be >= `near_zero_floor_pct` of closing price
      (default -0.5%), allowing a slightly negative MACD approaching zero
    """
    frame = macd_frame(df)
    if frame.empty:
        return False, {"reason": "No MACD data"}

    target = pd.Timestamp(as_of_date).normalize()
    idx = pd.to_datetime(frame.index)
    normalized = pd.DatetimeIndex(idx).normalize()
    matches = frame.loc[normalized <= target]
    if len(matches) < rising_days:
        return False, {"reason": "Insufficient MACD history"}

    tail = matches.tail(rising_days)
    values = tail["MACD"].tolist()
    rising = all(values[i] > values[i - 1] for i in range(1, len(values)))
    current = tail.iloc[-1]
    above_signal = float(current["MACD"]) > float(current["Signal"])
    near_zero = float(current["MACD_pct"]) >= float(near_zero_floor_pct)

    details = {
        "macd": float(current["MACD"]),
        "signal": float(current["Signal"]),
        "macd_pct": float(current["MACD_pct"]),
        "rising": bool(rising),
        "above_signal": bool(above_signal),
        "near_zero": bool(near_zero),
        "near_zero_floor_pct": float(near_zero_floor_pct),
    }
    return bool(rising and above_signal and near_zero), details

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable

import pandas as pd


@dataclass
class PatternSetup:
    status: str
    hh1_date: pd.Timestamp
    hh2_date: pd.Timestamp
    hh3_date: pd.Timestamp
    upper_trigger: float
    ll1_date: pd.Timestamp
    ll2_date: pd.Timestamp
    ll3_date: pd.Timestamp
    lower_invalidation: float
    breakout_date: pd.Timestamp | None = None
    breakout_open: float | None = None
    breakout_close: float | None = None
    invalidated_date: pd.Timestamp | None = None
    invalidated_open: float | None = None
    invalidated_close: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _normalise_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """Return a clean single-ticker OHLC frame with flat column names."""
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()

    if isinstance(out.columns, pd.MultiIndex):
        # yfinance may return a 2-level index for even one ticker.
        price_names = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
        level0 = set(map(str, out.columns.get_level_values(0)))
        if price_names & level0:
            out.columns = out.columns.get_level_values(0)
        else:
            out.columns = out.columns.get_level_values(-1)

    required = ["Open", "High", "Low", "Close"]
    missing = [c for c in required if c not in out.columns]
    if missing:
        return pd.DataFrame()

    out = out[required].copy()
    for col in required:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=required)
    out = out[~out.index.duplicated(keep="last")]
    out = out.sort_index()
    return out


def find_all_setups(df: pd.DataFrame) -> list[PatternSetup]:
    """
    Find all non-overlapping candidate structures that follow the user's rule:

    1) Three consecutive candles with progressively higher highs: H1 < H2 < H3.
       The high of candle 2 is the upper trigger.
    2) The nearest subsequent three-candle sequence with progressively lower lows:
       L1 > L2 > L3. The low of candle 2 is the lower invalidation level.
    3) Starting AFTER LL3:
       - if Open or Close falls below LL2 first -> INVALIDATED
       - if Open or Close rises above HH2 first -> TRIGGERED
       - otherwise -> WATCHING

    Intraday wicks alone do not trigger or invalidate the setup.
    """
    prices = _normalise_ohlc(df)
    if len(prices) < 7:
        return []

    setups: list[PatternSetup] = []
    n = len(prices)

    for i in range(2, n):
        h1 = float(prices["High"].iloc[i - 2])
        h2 = float(prices["High"].iloc[i - 1])
        h3 = float(prices["High"].iloc[i])

        if not (h1 < h2 < h3):
            continue

        # Find the nearest lower-low sequence strictly after completion of HH3.
        ll_end = None
        for j in range(i + 3, n):
            l1 = float(prices["Low"].iloc[j - 2])
            l2 = float(prices["Low"].iloc[j - 1])
            l3 = float(prices["Low"].iloc[j])
            if l1 > l2 > l3:
                ll_end = j
                break

        if ll_end is None:
            continue

        j = ll_end
        setup = PatternSetup(
            status="WATCHING",
            hh1_date=pd.Timestamp(prices.index[i - 2]),
            hh2_date=pd.Timestamp(prices.index[i - 1]),
            hh3_date=pd.Timestamp(prices.index[i]),
            upper_trigger=h2,
            ll1_date=pd.Timestamp(prices.index[j - 2]),
            ll2_date=pd.Timestamp(prices.index[j - 1]),
            ll3_date=pd.Timestamp(prices.index[j]),
            lower_invalidation=float(prices["Low"].iloc[j - 1]),
        )

        # Invalidation is checked before breakout for each later candle.
        for k in range(j + 1, n):
            op = float(prices["Open"].iloc[k])
            cl = float(prices["Close"].iloc[k])
            dt = pd.Timestamp(prices.index[k])

            if op < setup.lower_invalidation or cl < setup.lower_invalidation:
                setup.status = "INVALIDATED"
                setup.invalidated_date = dt
                setup.invalidated_open = op
                setup.invalidated_close = cl
                break

            if op > setup.upper_trigger or cl > setup.upper_trigger:
                setup.status = "TRIGGERED"
                setup.breakout_date = dt
                setup.breakout_open = op
                setup.breakout_close = cl
                break

        setups.append(setup)

    return setups


def latest_relevant_setup(df: pd.DataFrame) -> PatternSetup | None:
    """Return the most recently formed WATCHING or TRIGGERED setup, else latest invalidated setup."""
    setups = find_all_setups(df)
    if not setups:
        return None

    active = [s for s in setups if s.status in {"WATCHING", "TRIGGERED"}]
    pool: Iterable[PatternSetup] = active if active else setups
    return max(pool, key=lambda s: s.ll3_date)


def scan_one(df: pd.DataFrame) -> dict | None:
    setup = latest_relevant_setup(df)
    return setup.to_dict() if setup else None


def most_recent_triggered_setup(
    df: pd.DataFrame,
    eligible_dates: Iterable[pd.Timestamp] | None = None,
    *,
    exact_timestamp: bool = False,
) -> PatternSetup | None:
    """Return the newest triggered setup in an allowed recent window.

    Daily mode passes market dates and uses date matching. Hourly mode passes the
    latest completed hourly timestamps with ``exact_timestamp=True`` so the same
    pattern is evaluated candle-for-candle without collapsing hours into dates.
    """
    setups = [s for s in find_all_setups(df) if s.status == "TRIGGERED" and s.breakout_date is not None]
    if eligible_dates is not None:
        if exact_timestamp:
            allowed = {pd.Timestamp(d) for d in eligible_dates}
            setups = [s for s in setups if pd.Timestamp(s.breakout_date) in allowed]
        else:
            allowed = {pd.Timestamp(d).normalize() for d in eligible_dates}
            setups = [s for s in setups if pd.Timestamp(s.breakout_date).normalize() in allowed]
    if not setups:
        return None
    return max(setups, key=lambda s: pd.Timestamp(s.breakout_date))


@dataclass
class HigherHighCloseBreakout:
    """Three-higher-high structure confirmed by a Close above HH2, with no LL requirement."""
    hh1_date: pd.Timestamp
    hh2_date: pd.Timestamp
    hh3_date: pd.Timestamp
    upper_trigger: float
    breakout_date: pd.Timestamp
    breakout_close: float

    def to_dict(self) -> dict:
        return asdict(self)


def find_hh_close_breakouts(df: pd.DataFrame) -> list[HigherHighCloseBreakout]:
    """Find HH1 < HH2 < HH3 structures whose Close subsequently exceeds HH2.

    The first qualifying close is searched from HH3 onward, so HH3 itself may
    confirm the breakout when its close is above the high of HH2. No lower-low
    sequence or invalidation test is used in this mode.
    """
    prices = _normalise_ohlc(df)
    if len(prices) < 3:
        return []

    out: list[HigherHighCloseBreakout] = []
    n = len(prices)
    for i in range(2, n):
        h1 = float(prices["High"].iloc[i - 2])
        h2 = float(prices["High"].iloc[i - 1])
        h3 = float(prices["High"].iloc[i])
        if not (h1 < h2 < h3):
            continue

        for k in range(i, n):
            cl = float(prices["Close"].iloc[k])
            if cl > h2:
                out.append(HigherHighCloseBreakout(
                    hh1_date=pd.Timestamp(prices.index[i - 2]),
                    hh2_date=pd.Timestamp(prices.index[i - 1]),
                    hh3_date=pd.Timestamp(prices.index[i]),
                    upper_trigger=h2,
                    breakout_date=pd.Timestamp(prices.index[k]),
                    breakout_close=cl,
                ))
                break
    return out


def most_recent_hh_close_breakout(
    df: pd.DataFrame,
    eligible_dates: Iterable[pd.Timestamp] | None = None,
    *,
    exact_timestamp: bool = False,
) -> HigherHighCloseBreakout | None:
    """Return the newest HH2 close breakout in the allowed recent window."""
    setups = find_hh_close_breakouts(df)
    if eligible_dates is not None:
        if exact_timestamp:
            allowed = {pd.Timestamp(d) for d in eligible_dates}
            setups = [s for s in setups if pd.Timestamp(s.breakout_date) in allowed]
        else:
            allowed = {pd.Timestamp(d).normalize() for d in eligible_dates}
            setups = [s for s in setups if pd.Timestamp(s.breakout_date).normalize() in allowed]
    if not setups:
        return None
    return max(setups, key=lambda s: pd.Timestamp(s.breakout_date))

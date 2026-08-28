from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

SG_TZ = ZoneInfo("Asia/Singapore")


def _extract_ticker_frame(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    if not isinstance(raw.columns, pd.MultiIndex):
        return raw.copy()

    level0 = set(map(str, raw.columns.get_level_values(0)))
    level1 = set(map(str, raw.columns.get_level_values(1)))
    if ticker in level0:
        return raw[ticker].copy()
    if ticker in level1:
        return raw.xs(ticker, axis=1, level=1).copy()
    return pd.DataFrame()


def _normalize_intraday_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize Yahoo intraday bars and remove any still-forming Singapore day."""
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()
    idx = pd.to_datetime(out.index, errors="coerce")
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert(SG_TZ).tz_localize(None)
    out.index = idx
    out = out[~out.index.isna()]

    # A bar is evidence of at least one trade only if it carries positive volume.
    if "Volume" in out.columns:
        vol = pd.to_numeric(out["Volume"], errors="coerce").fillna(0)
        out = out[vol > 0]

    now = datetime.now(SG_TZ)
    if now.time() < time(17, 15):
        today = pd.Timestamp(now.date())
        out = out[out.index.normalize() < today]

    return out.sort_index()


def download_intraday_activity(
    tickers: list[str],
    period: str = "60d",
    interval: str = "5m",
    batch_size: int = 20,
) -> dict[str, pd.DataFrame]:
    """Batch-download intraday bars used for conservative activity verification.

    Yahoo does not expose SGX's exact per-day number-of-trades field.  Each
    positive-volume intraday bar proves that at least one trade occurred in that
    interval. Therefore >=5 distinct positive-volume bars in a day is a
    conservative sufficient condition for >=5 trades that day.
    """
    import yfinance as yf

    clean = [str(t).strip().upper() for t in tickers if str(t).strip()]
    result: dict[str, pd.DataFrame] = {}

    for start in range(0, len(clean), batch_size):
        batch = clean[start : start + batch_size]
        try:
            raw = yf.download(
                batch,
                period=period,
                interval=interval,
                auto_adjust=False,
                progress=False,
                threads=True,
                group_by="ticker",
                prepost=False,
            )
        except Exception:
            raw = pd.DataFrame()

        for ticker in batch:
            result[ticker] = _normalize_intraday_frame(_extract_ticker_frame(raw, ticker))

    return result


def conservative_activity_qualifies(
    intraday_df: pd.DataFrame,
    market_dates: list[pd.Timestamp],
    as_of_date: pd.Timestamp,
    min_transactions: int = 5,
    required_trading_days: int = 20,
) -> tuple[bool, dict]:
    """Verify a conservative lower bound of >=N trades on each prior trading day.

    We count distinct positive-volume intraday bars.  Five such bars imply at
    least five trades, but fewer than five bars is *not* proof that fewer than
    five trades occurred because several trades can share one bar.  Such days
    are rejected conservatively.
    """
    if intraday_df is None or intraday_df.empty:
        return False, {"reason": "Intraday activity data unavailable"}

    target = pd.Timestamp(as_of_date).normalize()
    dates = sorted(
        {
            pd.Timestamp(d).normalize()
            for d in market_dates
            if pd.Timestamp(d).normalize() <= target
        }
    )
    if len(dates) < required_trading_days:
        return False, {"reason": "Insufficient market-date history"}

    required_dates = dates[-required_trading_days:]
    frame = _normalize_intraday_frame(intraday_df)
    if frame.empty:
        return False, {"reason": "No positive-volume intraday bars"}

    bar_counts = frame.groupby(frame.index.normalize()).size()
    counts: list[int] = []
    missing: list[pd.Timestamp] = []

    for day in required_dates:
        if day not in bar_counts.index:
            missing.append(day)
            counts.append(0)
        else:
            counts.append(int(bar_counts.loc[day]))

    minimum = min(counts) if counts else 0
    qualifies = not missing and all(v >= min_transactions for v in counts)

    return bool(qualifies), {
        "minimum_nonempty_bars": int(minimum),
        "average_nonempty_bars": float(sum(counts) / len(counts)) if counts else 0.0,
        "days_checked": len(counts),
        "missing_days": len(missing),
        "window_start": required_dates[0],
        "window_end": required_dates[-1],
        "method": "positive-volume 5-minute bars (conservative lower bound)",
    }

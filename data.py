from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo
from datetime import datetime, time
import re

import pandas as pd
import requests


STOCKSSG_COMPANIES_URL = "https://stocks.com.sg/api/v1/companies"
SG_TZ = ZoneInfo("Asia/Singapore")
OFFICIAL_SGX_BASELINE = 604


def _yahoo_ticker(code: str) -> str:
    code = str(code).strip().upper()
    if code.endswith(".SI"):
        return code
    return f"{code}.SI"


def _row_text(row: dict) -> str:
    keys = (
        "company_name", "name", "company", "security_name", "security_type",
        "asset_class", "instrument_type", "type", "category", "industry",
        "sector", "classification", "sub_industry",
    )
    return " | ".join(str(row.get(k)) for k in keys if row.get(k) is not None).upper()


def exclusion_reason(row: dict) -> str | None:
    """Exclude REITs and business/listed trusts; keep ordinary companies including penny stocks."""
    text = _row_text(row)
    if re.search(r"\bREIT\b", text) or "REAL ESTATE INVESTMENT TRUST" in text:
        return "REIT"
    if "BUSINESS TRUST" in text:
        return "Business Trust"
    if re.search(r"\bTRUST\b", text):
        return "Trust / Business Trust"
    return None


@lru_cache(maxsize=2)
def load_sgx_universe_from_web() -> tuple[pd.DataFrame, dict]:
    response = requests.get(STOCKSSG_COMPANIES_URL, timeout=20)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data", []) if isinstance(payload, dict) else []

    eligible, excluded = [], []
    seen_codes: set[str] = set()

    for row in rows:
        if not isinstance(row, dict):
            continue
        code = row.get("ticker") or row.get("symbol") or row.get("code")
        company = row.get("company_name") or row.get("name") or row.get("company") or code
        if not code:
            continue
        code = str(code).strip().upper()
        if not code or code.startswith("^"):
            continue
        ticker = _yahoo_ticker(code)
        if ticker in seen_codes:
            continue
        seen_codes.add(ticker)

        reason = exclusion_reason(row)
        record = {"Ticker": ticker, "Company": str(company or code).strip()}
        if reason:
            record["Exclusion Reason"] = reason
            excluded.append(record)
        else:
            eligible.append(record)

    eligible_df = pd.DataFrame(eligible, columns=["Ticker", "Company"])
    if eligible_df.empty:
        raise ValueError("SGX company API returned no usable eligible securities.")

    excluded_df = pd.DataFrame(excluded)
    reasons = excluded_df.get("Exclusion Reason", pd.Series(dtype=str))
    stats = {
        "official_baseline": OFFICIAL_SGX_BASELINE,
        "source_records": len(seen_codes),
        "excluded_reit_trust": len(excluded_df),
        "eligible": len(eligible_df),
        "excluded_reit": int((reasons == "REIT").sum()),
        "excluded_business_trust": int(reasons.isin(["Business Trust", "Trust / Business Trust"]).sum()),
    }
    return eligible_df.sort_values("Ticker").reset_index(drop=True), stats


def load_sgx_universe(fallback_path=None) -> tuple[pd.DataFrame, str, dict]:
    universe, stats = load_sgx_universe_from_web()
    return universe, "Live SGX securities universe (REITs & business trusts excluded)", stats


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


def _flatten_single_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        price_names = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
        level0 = set(map(str, out.columns.get_level_values(0)))
        if price_names & level0:
            out.columns = out.columns.get_level_values(0)
        else:
            out.columns = out.columns.get_level_values(-1)
    return out


def completed_daily_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Remove today's still-forming daily candle while SGX is open."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = _flatten_single_frame(df)
    try:
        idx = pd.to_datetime(out.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert(SG_TZ).tz_localize(None)
        out.index = idx
        now = datetime.now(SG_TZ)
        if now.time() < time(17, 15):
            out = out[out.index.normalize() < pd.Timestamp(now.date())]
    except Exception:
        pass
    return out.sort_index()


def completed_hourly_bars(df: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    """Keep only completed 60-minute SGX candles.

    Yahoo timestamps intraday bars at their start time. A bar is considered complete
    only after start + 60 minutes. This also naturally handles the lunch break because
    only bars actually returned by the feed are considered.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    out = _flatten_single_frame(df)
    idx = pd.to_datetime(out.index)
    if getattr(idx, "tz", None) is not None:
        idx_sg = idx.tz_convert(SG_TZ)
    else:
        idx_sg = idx.tz_localize(SG_TZ)
    current = now or datetime.now(SG_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SG_TZ)
    keep = (idx_sg + pd.Timedelta(hours=1)) <= pd.Timestamp(current)
    out = out.loc[keep].copy()
    # Store naive SG local timestamps for predictable comparisons/display.
    out.index = idx_sg[keep].tz_localize(None)
    return out.sort_index()


def clean_bars(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    return completed_hourly_bars(df) if interval in {"60m", "1h"} else completed_daily_bars(df)


@lru_cache(maxsize=2048)
def download_history(ticker: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    import yfinance as yf
    data = yf.download(
        ticker, period=period, interval=interval, auto_adjust=False,
        progress=False, threads=False, prepost=False,
    )
    return clean_bars(data, interval)


def download_histories(
    tickers: list[str], period: str = "2y", interval: str = "1d", batch_size: int = 40
) -> dict[str, pd.DataFrame]:
    """Batch-download daily or 60-minute data for the full eligible SGX universe."""
    histories: dict[str, pd.DataFrame] = {}
    clean = [str(t).strip().upper() for t in tickers if str(t).strip()]

    for start in range(0, len(clean), batch_size):
        batch = clean[start:start + batch_size]
        try:
            import yfinance as yf
            raw = yf.download(
                batch, period=period, interval=interval, auto_adjust=False,
                progress=False, threads=True, group_by="ticker", prepost=False,
            )
        except Exception:
            raw = pd.DataFrame()

        for ticker in batch:
            histories[ticker] = clean_bars(_extract_ticker_frame(raw, ticker), interval)
    return histories


def latest_market_dates(histories: dict[str, pd.DataFrame], count: int = 3) -> list[pd.Timestamp]:
    dates: set[pd.Timestamp] = set()
    for df in histories.values():
        if df is None or df.empty:
            continue
        try:
            dates.update(pd.Timestamp(x).normalize() for x in pd.to_datetime(df.index))
        except Exception:
            continue
    return sorted(dates)[-count:]


def latest_market_bars(histories: dict[str, pd.DataFrame], count: int = 3) -> list[pd.Timestamp]:
    """Latest distinct completed hourly bar timestamps observed across the universe."""
    bars: set[pd.Timestamp] = set()
    for df in histories.values():
        if df is None or df.empty:
            continue
        try:
            bars.update(pd.Timestamp(x) for x in pd.to_datetime(df.index))
        except Exception:
            continue
    return sorted(bars)[-count:]


def load_ticker_file(path_or_buffer) -> pd.DataFrame:
    df = pd.read_csv(path_or_buffer)
    df.columns = [str(c).strip() for c in df.columns]
    if "Ticker" not in df.columns:
        raise ValueError("Ticker file must contain a 'Ticker' column.")
    if "Company" not in df.columns:
        df["Company"] = df["Ticker"]
    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper().apply(_yahoo_ticker)
    df["Company"] = df["Company"].astype(str).str.strip()
    return df[df["Ticker"] != ""][["Ticker", "Company"]].drop_duplicates("Ticker").reset_index(drop=True)

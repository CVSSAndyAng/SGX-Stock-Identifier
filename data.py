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
    """Flatten likely classification/name fields for exclusion checks."""
    keys = (
        "company_name",
        "name",
        "company",
        "security_name",
        "security_type",
        "asset_class",
        "instrument_type",
        "type",
        "category",
        "industry",
        "sector",
        "classification",
        "sub_industry",
    )
    values = []
    for key in keys:
        value = row.get(key)
        if value is not None:
            values.append(str(value))
    return " | ".join(values).upper()


def exclusion_reason(row: dict) -> str | None:
    """Return why a security is excluded, otherwise None.

    User rule: exclude REITs and business trusts.  The source API may expose
    classification metadata differently over time, so we use both metadata and
    conservative name checks.  A security whose name/classification contains
    the standalone word TRUST is excluded; this intentionally captures business
    trusts whose legal names do not literally contain the phrase 'Business Trust'.
    """
    text = _row_text(row)

    if re.search(r"\bREIT\b", text) or "REAL ESTATE INVESTMENT TRUST" in text:
        return "REIT"

    if "BUSINESS TRUST" in text:
        return "Business Trust"

    # Captures listed trusts such as '* Trust' even when the API omits subtype.
    if re.search(r"\bTRUST\b", text):
        return "Trust / Business Trust"

    return None


@lru_cache(maxsize=2)
def load_sgx_universe_from_web() -> tuple[pd.DataFrame, dict]:
    """Load SGX securities and remove REITs/business trusts before scanning.

    Returns (eligible_universe, stats).  Price data still comes from Yahoo
    Finance.  No price, market-cap, or liquidity filter is applied, so penny
    stocks remain eligible.
    """
    response = requests.get(STOCKSSG_COMPANIES_URL, timeout=20)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data", []) if isinstance(payload, dict) else []

    eligible = []
    excluded = []
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
        record = {
            "Ticker": ticker,
            "Company": str(company or code).strip(),
        }

        if reason:
            record["Exclusion Reason"] = reason
            excluded.append(record)
        else:
            eligible.append(record)

    eligible_df = pd.DataFrame(eligible, columns=["Ticker", "Company"])
    if eligible_df.empty:
        raise ValueError("SGX company API returned no usable eligible securities.")

    excluded_df = pd.DataFrame(excluded)
    stats = {
        "official_baseline": OFFICIAL_SGX_BASELINE,
        "source_records": len(seen_codes),
        "excluded_reit_trust": len(excluded_df),
        "eligible": len(eligible_df),
        "excluded_reit": int((excluded_df.get("Exclusion Reason", pd.Series(dtype=str)) == "REIT").sum()),
        "excluded_business_trust": int(
            excluded_df.get("Exclusion Reason", pd.Series(dtype=str)).isin(
                ["Business Trust", "Trust / Business Trust"]
            ).sum()
        ),
    }

    eligible_df = eligible_df.sort_values("Ticker").reset_index(drop=True)
    return eligible_df, stats


def load_sgx_universe(fallback_path=None) -> tuple[pd.DataFrame, str, dict]:
    """Return the live full-market eligible universe.

    We deliberately do not silently fall back to the old small starter list,
    because doing so would violate the user's requirement to scan the full SGX
    universe (less REITs/business trusts).  The app should surface the source
    error and ask the user to retry instead of claiming a partial market scan.
    """
    universe, stats = load_sgx_universe_from_web()
    return universe, "Live SGX securities universe (REITs & business trusts excluded)", stats


@lru_cache(maxsize=1024)
def download_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    """Download daily OHLCV data for one Yahoo Finance ticker."""
    import yfinance as yf

    data = yf.download(
        ticker,
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    return completed_daily_bars(data)


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


def download_histories(tickers: list[str], period: str = "2y", batch_size: int = 40) -> dict[str, pd.DataFrame]:
    """Batch-download daily data for the eligible SGX universe."""
    histories: dict[str, pd.DataFrame] = {}
    clean = [str(t).strip().upper() for t in tickers if str(t).strip()]

    for start in range(0, len(clean), batch_size):
        batch = clean[start : start + batch_size]
        try:
            import yfinance as yf
            raw = yf.download(
                batch,
                period=period,
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=True,
                group_by="ticker",
            )
        except Exception:
            raw = pd.DataFrame()

        for ticker in batch:
            frame = _extract_ticker_frame(raw, ticker)
            histories[ticker] = completed_daily_bars(frame)

    return histories


def completed_daily_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Exclude today's still-forming daily candle while SGX is open."""
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()
    try:
        idx = pd.to_datetime(out.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert(SG_TZ).tz_localize(None)
        out.index = idx

        now = datetime.now(SG_TZ)
        if now.time() < time(17, 15):
            today = pd.Timestamp(now.date())
            out = out[out.index.normalize() < today]
    except Exception:
        pass
    return out


def latest_market_dates(histories: dict[str, pd.DataFrame], count: int = 3) -> list[pd.Timestamp]:
    """Return the latest unique completed trading dates seen across the universe."""
    dates: set[pd.Timestamp] = set()
    for df in histories.values():
        if df is None or df.empty:
            continue
        try:
            idx = pd.to_datetime(df.index)
            if getattr(idx, "tz", None) is not None:
                idx = idx.tz_localize(None)
            dates.update(pd.Timestamp(x).normalize() for x in idx)
        except Exception:
            continue
    return sorted(dates)[-count:]


def load_ticker_file(path_or_buffer) -> pd.DataFrame:
    """Retained for local/manual testing; not used as full-market fallback."""
    df = pd.read_csv(path_or_buffer)
    df.columns = [str(c).strip() for c in df.columns]

    if "Ticker" not in df.columns:
        raise ValueError("Ticker file must contain a 'Ticker' column.")

    if "Company" not in df.columns:
        df["Company"] = df["Ticker"]

    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    df["Ticker"] = df["Ticker"].apply(_yahoo_ticker)
    df["Company"] = df["Company"].astype(str).str.strip()
    df = df[df["Ticker"] != ""]
    return df[["Ticker", "Company"]].drop_duplicates("Ticker").reset_index(drop=True)

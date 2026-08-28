from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo
from datetime import datetime, time

import pandas as pd
import requests
import yfinance as yf


STOCKSSG_COMPANIES_URL = "https://stocks.com.sg/api/v1/companies"
SG_TZ = ZoneInfo("Asia/Singapore")


def _yahoo_ticker(code: str) -> str:
    code = str(code).strip().upper()
    if code.endswith(".SI"):
        return code
    return f"{code}.SI"


@lru_cache(maxsize=2)
def load_sgx_universe_from_web() -> pd.DataFrame:
    """Load the current SGX company universe from StocksSG's public companies API.

    The endpoint is used only to obtain company/ticker names. Price data still comes
    from Yahoo Finance. If the endpoint is unavailable, the app falls back to the
    bundled CSV.
    """
    response = requests.get(STOCKSSG_COMPANIES_URL, timeout=20)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data", []) if isinstance(payload, dict) else []

    out = []
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
        out.append({"Ticker": _yahoo_ticker(code), "Company": str(company or code).strip()})

    df = pd.DataFrame(out)
    if df.empty:
        raise ValueError("SGX company API returned no usable tickers.")
    return df.drop_duplicates("Ticker").sort_values("Ticker").reset_index(drop=True)


def load_sgx_universe(fallback_path) -> tuple[pd.DataFrame, str]:
    """Return (universe, source_label), using the bundled CSV as a fallback."""
    try:
        return load_sgx_universe_from_web(), "Live SGX company universe"
    except Exception:
        return load_ticker_file(fallback_path), "Bundled fallback ticker list"


@lru_cache(maxsize=1024)
def download_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    """Download daily OHLCV data for one Yahoo Finance ticker."""
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
    """Batch-download daily data for a full SGX universe.

    Batching cuts the number of remote requests dramatically compared with one
    request per stock, which matters on Streamlit Community Cloud.
    """
    histories: dict[str, pd.DataFrame] = {}
    clean = [str(t).strip().upper() for t in tickers if str(t).strip()]

    for start in range(0, len(clean), batch_size):
        batch = clean[start : start + batch_size]
        try:
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
    """Exclude today's still-forming daily candle while SGX is open.

    Signals should be based on completed Open/High/Low/Close candles. After a
    conservative 17:15 Singapore-time cutoff, today's daily bar may be retained.
    """
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

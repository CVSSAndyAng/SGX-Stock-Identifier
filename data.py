from __future__ import annotations

from functools import lru_cache

import pandas as pd
import yfinance as yf


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
    return data


def load_ticker_file(path_or_buffer) -> pd.DataFrame:
    df = pd.read_csv(path_or_buffer)
    df.columns = [str(c).strip() for c in df.columns]

    if "Ticker" not in df.columns:
        raise ValueError("Ticker file must contain a 'Ticker' column.")

    if "Company" not in df.columns:
        df["Company"] = df["Ticker"]

    df["Ticker"] = df["Ticker"].astype(str).str.strip()
    df["Company"] = df["Company"].astype(str).str.strip()
    df = df[df["Ticker"] != ""]
    return df[["Ticker", "Company"]].drop_duplicates("Ticker").reset_index(drop=True)

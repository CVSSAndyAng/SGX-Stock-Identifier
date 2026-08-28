from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo
from datetime import datetime, time
from io import StringIO
import re
import unicodedata

import pandas as pd
import requests


# The 604 figure is the SGX month-end listed-securities count for Mar-2026 and is
# retained only as the user's reference baseline. The live market list can move as
# securities list/delist, so the app always displays the live source count too.
OFFICIAL_SGX_BASELINE = 604
OFFICIAL_SGX_BASELINE_LABEL = "Mar 2026 SGX listed-securities reference"

# StockAnalysis publishes a current, daily-refreshed list of SGX stock symbols and
# company names. It is used for trading-code discovery because SGX's corporate-info
# directory does not expose Yahoo-compatible ticker codes in its public HTML cards.
STOCKANALYSIS_SGX_URL = "https://stockanalysis.com/list/singapore-exchange/"
SGX_CORPORATE_INFO_URL = "https://www.sgx.com/securities/corporate-information"
SG_TZ = ZoneInfo("Asia/Singapore")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
    )
}


def _yahoo_ticker(code: str) -> str:
    code = str(code).strip().upper()
    if code.endswith(".SI"):
        return code
    return f"{code}.SI"


def _normalise_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).upper()
    text = text.replace("&", " AND ")
    # Remove common legal suffixes so SGX and market-data names match more often.
    text = re.sub(r"\b(PTE|LTD|LIMITED|INC|INCORPORATED|CORP|CORPORATION|PLC|BERHAD|BHD)\b", " ", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _row_text(row: dict) -> str:
    keys = (
        "company_name", "name", "company", "security_name", "security_type",
        "asset_class", "instrument_type", "type", "category", "industry",
        "sector", "classification", "sub_industry",
    )
    return " | ".join(str(row.get(k)) for k in keys if row.get(k) is not None).upper()


def exclusion_reason(row: dict, global_quote_names: set[str] | None = None) -> str | None:
    """Classify securities that are outside the user's requested stock universe.

    Penny stocks are deliberately kept. There is no price, market-cap or volume
    filter. REITs and business trusts are removed per the user's instruction.
    ETFs/funds and SGX Global Quote / SDR names are also removed because they are
    not ordinary Mainboard/Catalist operating-company equities.
    """
    text = _row_text(row)
    company = row.get("company_name") or row.get("name") or row.get("company") or ""
    norm = _normalise_name(company)

    if global_quote_names and norm in global_quote_names:
        return "Global Quote / SDR"
    if re.search(r"\bREIT\b", text) or "REAL ESTATE INVESTMENT TRUST" in text:
        return "REIT"
    if "BUSINESS TRUST" in text or "STAPLED TRUST" in text:
        return "Business Trust"
    if re.search(r"\bTRUST\b", text):
        return "Trust / Business Trust"
    if re.search(r"\bETF\b", text) or "EXCHANGE TRADED FUND" in text:
        return "ETF / Fund"
    # Bond/index funds can sometimes be labelled without the literal ETF token.
    if re.search(r"\bFUND\b", text) and not re.search(r"\bFUNDAMENT", text):
        return "ETF / Fund"
    return None


def _extract_stockanalysis_table(html: str) -> pd.DataFrame:
    """Extract Symbol + Company Name from a StockAnalysis SGX list page."""
    tables = pd.read_html(StringIO(html))
    for table in tables:
        cols = {str(c).strip(): c for c in table.columns}
        symbol_col = next((cols[c] for c in cols if c.lower() in {"symbol", "ticker"}), None)
        company_col = next((cols[c] for c in cols if c.lower() in {"company name", "company", "name"}), None)
        if symbol_col is not None and company_col is not None:
            out = table[[symbol_col, company_col]].copy()
            out.columns = ["Code", "Company"]
            out["Code"] = out["Code"].astype(str).str.strip().str.upper()
            out["Company"] = out["Company"].astype(str).str.strip()
            out = out[(out["Code"] != "") & (out["Company"] != "")]
            return out
    return pd.DataFrame(columns=["Code", "Company"])


def _fetch_stockanalysis_universe() -> pd.DataFrame:
    """Fetch the current SGX stock list from the known valid list pages.

    StockAnalysis currently exposes the Singapore list on page 1 and page 2.
    We intentionally do not probe page 3 because the site returns HTTP 404 for
    non-existent pagination pages. This keeps a harmless end-of-list response
    from disabling the whole scanner.
    """
    frames: list[pd.DataFrame] = []
    seen_codes: set[str] = set()

    urls = [
        STOCKANALYSIS_SGX_URL,
        f"{STOCKANALYSIS_SGX_URL}?page=2",
    ]

    for url in urls:
        response = requests.get(url, timeout=25, headers=_HEADERS)
        response.raise_for_status()
        frame = _extract_stockanalysis_table(response.text)
        if frame.empty:
            continue
        new_codes = set(frame["Code"]) - seen_codes
        if not new_codes:
            continue
        frames.append(frame[frame["Code"].isin(new_codes)])
        seen_codes.update(new_codes)

    if not frames:
        raise ValueError("Current SGX market list returned no usable stock symbols.")

    out = pd.concat(frames, ignore_index=True).drop_duplicates("Code", keep="first")
    return out.reset_index(drop=True)


def _parse_sgx_company_cards(text: str) -> list[str]:
    """Parse company names from the text of SGX corporate-information cards.

    SGX cards render as: Company Name / Country / 'Listing Board' / Board.
    This deliberately uses text structure instead of fragile CSS class names.
    """
    lines = [re.sub(r"\s+", " ", x).strip() for x in str(text).splitlines()]
    lines = [x for x in lines if x]
    names: list[str] = []
    for i, value in enumerate(lines):
        if value.upper() != "LISTING BOARD" or i < 2:
            continue
        company = lines[i - 2]
        if company.upper() in {"COUNTRY", "CORPORATE INFORMATION"}:
            continue
        if company not in names:
            names.append(company)
    return names


def _fetch_global_quote_names() -> set[str]:
    """Fetch SGX Global Quote names so SDR/DR counters can be excluded by name.

    Failure is non-fatal; the market list still loads and other exclusions apply.
    """
    names: set[str] = set()
    try:
        # Global Quote has well under 200 records. Read multiple pages because SGX
        # may ignore pagesize depending on deployment/session.
        for page in range(1, 12):
            params = {"listingBoard": "GLOBAL_QUOTE", "page": page, "pagesize": 100}
            r = requests.get(SGX_CORPORATE_INFO_URL, params=params, timeout=20, headers=_HEADERS)
            r.raise_for_status()
            page_names = _parse_sgx_company_cards(r.text)
            if not page_names:
                break
            before = len(names)
            names.update(_normalise_name(x) for x in page_names)
            if len(names) == before:
                break
            # Most deployments return 20/page. Stop once a short page is observed.
            if len(page_names) < 20:
                break
    except Exception:
        return set()
    return {x for x in names if x}


@lru_cache(maxsize=2)
def load_sgx_universe_from_web() -> tuple[pd.DataFrame, dict]:
    market = _fetch_stockanalysis_universe()
    global_quotes = _fetch_global_quote_names()

    eligible: list[dict] = []
    excluded: list[dict] = []
    seen: set[str] = set()

    for _, r in market.iterrows():
        code = str(r["Code"]).strip().upper()
        company = str(r["Company"]).strip()
        if not code or code == "NAN" or code.startswith("^"):
            continue
        ticker = _yahoo_ticker(code)
        if ticker in seen:
            continue
        seen.add(ticker)
        row = {"ticker": code, "company_name": company}
        reason = exclusion_reason(row, global_quote_names=global_quotes)
        record = {"Ticker": ticker, "Company": company}
        if reason:
            record["Exclusion Reason"] = reason
            excluded.append(record)
        else:
            eligible.append(record)

    eligible_df = pd.DataFrame(eligible, columns=["Ticker", "Company"])
    if eligible_df.empty:
        raise ValueError("The broad SGX market source returned no eligible stocks after exclusions.")

    excluded_df = pd.DataFrame(excluded)
    reasons = excluded_df.get("Exclusion Reason", pd.Series(dtype=str))
    stats = {
        "official_baseline": OFFICIAL_SGX_BASELINE,
        "source_records": len(seen),
        "global_quote_names_loaded": len(global_quotes),
        "excluded_global_quote": int((reasons == "Global Quote / SDR").sum()),
        "excluded_reit": int((reasons == "REIT").sum()),
        "excluded_business_trust": int(reasons.isin(["Business Trust", "Trust / Business Trust"]).sum()),
        "excluded_etf_fund": int((reasons == "ETF / Fund").sum()),
        "excluded_total": len(excluded_df),
        "eligible": len(eligible_df),
    }
    return eligible_df.sort_values("Ticker").reset_index(drop=True), stats


def load_sgx_universe(fallback_path=None) -> tuple[pd.DataFrame, str, dict]:
    universe, stats = load_sgx_universe_from_web()
    source = "Broad current SGX stock-symbol list + SGX Global Quote exclusion"
    return universe, source, stats


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
    """Keep only completed 60-minute SGX candles."""
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
    return df[["Ticker", "Company"]].drop_duplicates("Ticker").reset_index(drop=True)

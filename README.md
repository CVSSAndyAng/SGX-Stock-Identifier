# SGX Recent Trigger Scanner

A Streamlit technical-research screener for SGX-listed securities.

## Current universe rule

The app uses the live SGX company/securities universe and then **excludes REITs and business trusts before scanning**.

- Penny stocks: **included**
- Mainboard / Catalist operating-company counters: **included**
- No minimum price: **yes**
- No minimum market cap: **yes**
- No minimum volume: **yes**
- REITs: **excluded**
- Business trusts / listed trusts: **excluded**

The dashboard shows the 604-security reference baseline, the actual number returned by the live source, how many trusts were removed, and the final eligible count. It never silently claims a full-market scan when the source or Yahoo Finance did not provide complete data.

## Technical rule

For every eligible counter:

1. Find three consecutive candles with progressively higher highs (`H1 < H2 < H3`).
2. Store the **High of Day 2 (HH2)** as the upper trigger.
3. Find the **nearest subsequent** three consecutive candles with progressively lower lows (`L1 > L2 > L3`).
4. Store the **Low of Day 2 (LL2)** as the invalidation/stop level.
5. Starting after LL3, trigger when **Open or Close > HH2**, provided no earlier Open or Close fell below LL2.
6. Display only signals that triggered on one of the **latest 3 completed SGX trading days**.
7. Entry reference is the breakout Open if Open > HH2; otherwise the breakout Close.
8. Profit target is **+10% from entry**. LL2 remains the stop/invalidation level.

Intraday wicks below LL2 do not invalidate the setup unless the Open or Close is below LL2.

## Price data and coverage

Daily OHLC data is downloaded from Yahoo Finance using `yfinance` and batched for Streamlit Cloud performance. Today's still-forming daily candle is excluded until after a conservative 17:15 Singapore-time cutoff.

The app reports:

- eligible counters after trust exclusions;
- counters with usable Yahoo OHLC data;
- counters with missing/insufficient data; and
- number triggered within the latest 3 trading days.

If the live SGX universe source cannot be loaded, the app stops rather than silently falling back to the old 25-counter starter list.

## Deploy to Streamlit Community Cloud

Use:

- Repository: your GitHub repository
- Branch: `main`
- Main file path: `app.py`

Streamlit will redeploy automatically after you push the updated files to `main`.

## Run locally

```bash
python -m venv .venv
pip install -r requirements.txt
streamlit run app.py
```

## Tests

```bash
pytest -q
```

## Files

- `app.py` — dashboard, coverage reporting, and recent-trigger output
- `scanner.py` — HH/LL pattern engine
- `data.py` — SGX universe filtering and Yahoo Finance price data
- `requirements.txt` — dependencies
- `.streamlit/config.toml` — Streamlit configuration
- `test_scanner.py` — pattern tests
- `test_recent_trigger.py` — latest-3-trading-days tests
- `test_universe_filter.py` — REIT/business-trust exclusion tests

## Important

This is a technical screening/research tool, not an investment recommendation. Market-data sources can contain missing, delayed, suspended, or corporate-action-affected observations; verify any signal before use.

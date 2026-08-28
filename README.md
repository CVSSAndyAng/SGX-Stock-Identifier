# SGX Recent Trigger Scanner

A Streamlit technical-research screener for SGX stocks.

## Current rule

The app searches each stock for:

1. Three consecutive candles with progressively higher highs (`H1 < H2 < H3`).
2. Store the **High of Day 2 (HH2)** as the upper trigger.
3. Find the **nearest subsequent** three consecutive candles with progressively lower lows (`L1 > L2 > L3`).
4. Store the **Low of Day 2 (LL2)** as the invalidation/stop level.
5. Starting after LL3, the setup is triggered when **Open or Close > HH2**, provided no earlier Open or Close fell below LL2.

The dashboard now displays **only stocks whose trigger occurred on one of the latest 3 completed SGX trading days**.

## Universe

The app attempts to load the current SGX company universe from the public StocksSG companies API, then converts SGX codes to Yahoo Finance `.SI` symbols. If that source is temporarily unavailable, the bundled `sgx_tickers.csv` is used as a fallback and the UI clearly labels the fallback.

## Price data

Daily OHLC data is downloaded from Yahoo Finance with `yfinance`. The full universe is downloaded in batches for better Streamlit Cloud performance. Today's still-forming daily bar is excluded until after a conservative 17:15 Singapore-time cutoff.

## Run locally

```bash
python -m venv .venv
```

Activate the environment and install dependencies:

```bash
pip install -r requirements.txt
```

Run:

```bash
streamlit run app.py
```

## Deploy to Streamlit Community Cloud

Use:

- Repository: your GitHub repository
- Branch: `main`
- Main file path: `app.py`

No API key is required for the current version.

## Files

- `app.py` — Streamlit dashboard and recent-trigger filtering
- `scanner.py` — pattern engine
- `data.py` — SGX universe and Yahoo Finance price-data functions
- `sgx_tickers.csv` — fallback ticker universe
- `requirements.txt` — Python dependencies
- `.streamlit/config.toml` — Streamlit configuration
- `test_scanner.py` and `test_recent_trigger.py` — logic tests

## Important

This is a technical screening/research tool, not an investment recommendation. Yahoo symbols can occasionally be missing, delayed, suspended, or affected by corporate actions, so signals should be checked before use.

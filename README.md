# SGX HH/LL + MACD Stock Scanner

Streamlit scanner for SGX stock research candidates. It supports **Daily** and **Hourly (60-minute)** modes.

## Current screening rules

A counter is shown only when both conditions pass:

1. **HH/LL structure** — three consecutive higher highs; then the nearest subsequent three consecutive lower lows. HH2 is the upper trigger and LL2 is the invalidation level. After LL3, Open or Close must break above HH2 before any Open or Close falls below LL2. Only triggers from the latest 3 completed candles are shown.
2. **MACD(12,26,9)** — MACD is rising for 3 candles, above its signal line, and may remain slightly negative while approaching zero. The default near-zero floor is -0.5% of price and can be adjusted in the sidebar.

There is **no transaction/activity condition**. There is also no minimum price, market-cap or volume filter.

## Universe fix

The earlier build used a narrow third-party company endpoint and could report only about 142 eligible counters. This build replaces that source with a broad current SGX stock-symbol list and then explicitly removes:

- REITs
- business/listed/stapled trusts
- ETFs/funds
- SGX Global Quote / SDR names

Penny stocks remain eligible. The app shows the full universe funnel on screen: current market symbols loaded, each exclusion category, final eligible counters, usable Yahoo OHLC, recent HH/LL triggers and MACD passes.

The `604` figure is retained only as the user's **March 2026 SGX listed-securities reference**. It is not hard-coded as the live count because listings and delistings change the market universe.

## Run locally

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Community Cloud

Push all files in this folder to the root of your private GitHub repository. Set the main file to `app.py`. Streamlit will install `requirements.txt` and redeploy automatically after pushes to the configured branch.

## Data notes

- Universe codes: broad current SGX stock list from StockAnalysis, refreshed when Streamlit restarts/reloads the cached universe.
- Global Quote/SDR classification: SGX corporate-information directory when reachable.
- OHLC: Yahoo Finance via `yfinance`.
- The app displays actual usable OHLC coverage and does not pretend every listed counter has a working Yahoo `.SI` history.

This is a technical research screener, not an investment recommendation.

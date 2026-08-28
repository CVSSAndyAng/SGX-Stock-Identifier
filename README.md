# SGX Multi-Condition Stock Scanner

A Streamlit scanner for SGX-listed operating-company stocks. Penny stocks are included; REITs and business trusts are excluded.

## Screening rules

A counter is shortlisted only when all conditions pass:

1. **Price structure** — find 3 consecutive higher highs, then the nearest subsequent 3 consecutive lower lows. Use HH Day 2 as the upper trigger and LL Day 2 as the invalidation level. A valid trigger occurs when a later candle opens or closes above HH2 without any earlier post-setup candle opening or closing below LL2. Only triggers from the latest 3 completed SGX trading days are shown.
2. **MACD (12,26,9)** — MACD is rising for 3 consecutive trading days, is above the signal line, and is either positive or no lower than the configurable near-zero floor (default -0.5% of share price).
3. **Activity** — no upload is required. The app automatically downloads 5-minute Yahoo intraday data. Every one of the prior 20 completed SGX trading days must contain at least 5 separate positive-volume 5-minute bars. Five such bars prove at least five trades occurred that day. This is deliberately conservative because the free Yahoo feed does not expose SGX's exact daily number-of-trades field; a thin counter with 5 trades clustered inside fewer than 5 bars may be rejected.

The app also displays a +10% target and the LL2 stop reference. It is a research screener, not an automatic investment recommendation.

## Deploy on Streamlit Community Cloud

1. Upload all files in this folder to the root of your GitHub repository.
2. In Streamlit Community Cloud, deploy the repository with `app.py` as the main file.
3. No API key and no transaction CSV upload are required.
4. Press **Scan all eligible SGX stocks**. Full-market scans can take time because both daily and intraday data are downloaded.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Notes on data

- Daily and intraday price/activity bars are downloaded from Yahoo Finance through `yfinance`.
- The SGX universe is loaded dynamically, with REITs and business trusts excluded before scanning.
- Yahoo coverage can be incomplete for suspended, newly listed, or very illiquid counters. The dashboard reports actual usable coverage rather than assuming every security was successfully downloaded.
- The activity test is a conservative lower-bound verification, not SGX's official per-counter transaction-count field. Exact historical trade counts would require a market-data source that licenses that field.

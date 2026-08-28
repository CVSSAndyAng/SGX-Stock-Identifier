# SGX HH/LL + MACD Scanner

A Streamlit technical-research screener for SGX-listed stocks.

## Final rules

### Universe
- Uses the live SGX securities universe.
- Includes penny stocks.
- Excludes REITs and business trusts.
- No minimum price, volume, market-cap, or transaction-count requirement.
- **Condition 2 / transaction activity has been removed.**

### Price-structure condition
For the selected candle timeframe:
1. Find 3 consecutive candles with higher highs: `H1 < H2 < H3`.
2. Store the high of candle 2 as **HH2 trigger**.
3. Find the nearest subsequent 3 consecutive candles with lower lows: `L1 > L2 > L3`.
4. Store the low of candle 2 as **LL2 invalidation / stop**.
5. After LL3, invalidate the setup if any candle **Open or Close < LL2**.
6. Otherwise trigger when any candle **Open or Close > HH2**.

Intracandle wicks alone do not trigger or invalidate the setup.

### MACD condition
Standard MACD `(12, 26, 9)` on the same selected timeframe:
- MACD rising for 3 consecutive candles;
- MACD above its signal line;
- MACD can be slightly negative while rising toward zero;
- default normalized floor is `-0.5% of price`, adjustable in the sidebar.

## Daily vs Hourly mode

The app has a **Candle timeframe** switch:

- **Daily**: all rules use completed daily candles. Only setups triggered in the latest **3 completed SGX trading days** are shown.
- **Hourly**: all rules use completed **60-minute candles**. Only setups triggered in the latest **3 completed hourly SGX candles** are shown. HH/LL structure and MACD are both computed from hourly candles.

Hourly mode uses Yahoo Finance intraday data. Intraday history availability is provider-dependent and can be more limited than daily history.

## Output
For each qualifying research candidate the app shows:
- ticker and company;
- timeframe and trigger date/time;
- entry type and entry price;
- +10% target;
- LL2 stop;
- current close;
- MACD, signal, normalized MACD;
- HH/LL structure timestamps;
- candlestick chart with HH2, LL2, and +10% target lines.

## Run locally

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install and run:

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Community Cloud
1. Upload all repository files to GitHub.
2. In Streamlit Community Cloud create/deploy the app from that repository.
3. Main file path: `app.py`.
4. No API key or uploaded transaction file is required.

## Important
This is a technical research screener, not an investment recommendation. Free public data feeds can have missing/delayed SGX records, especially intraday and illiquid counters. The app reports actual usable OHLC coverage after each scan.

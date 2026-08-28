# SGX Technical Pattern Screener

A Streamlit app that scans SGX counters for a custom price-action setup.

## Pattern rule

1. Find **3 consecutive trading days with higher highs**: `H1 < H2 < H3`.
2. Store the **High of Day 2** as the upper trigger.
3. Find the **nearest subsequent** 3-day sequence with lower lows: `L1 > L2 > L3`.
4. Store the **Low of Day 2** as the lower invalidation level.
5. Starting after the third lower-low candle:
   - If any candle **opens OR closes below LL Day-2**, the setup is invalidated.
   - Otherwise, if a candle **opens OR closes above HH Day-2**, the setup is triggered and the stock is highlighted.
   - Intraday wicks alone do not trigger or invalidate the setup.

The app also shows currently valid **WATCHING** setups that have not yet triggered.

## Files

- `app.py` — Streamlit dashboard.
- `scanner.py` — pattern logic.
- `data.py` — Yahoo Finance data download and ticker-file handling.
- `sgx_tickers.csv` — starter SGX ticker universe. Add more rows as needed.
- `requirements.txt` — Python dependencies.
- `.streamlit/config.toml` — Streamlit appearance and server configuration.

## Run locally

### 1. Install Python

Use Python 3.10 or newer.

### 2. Create a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Start the app

```bash
streamlit run app.py
```

## Upload to GitHub

Create a new empty GitHub repository, then upload the contents of this folder. Do not upload the ZIP file itself if you want GitHub to show the individual project files.

Using Git from the project folder:

```bash
git init
git add .
git commit -m "Initial SGX technical screener"
git branch -M main
git remote add origin YOUR_GITHUB_REPOSITORY_URL
git push -u origin main
```

## Deploy on Streamlit Community Cloud

1. Push this folder to GitHub.
2. Sign in to Streamlit Community Cloud.
3. Create a new app from the repository.
4. Set the main file path to `app.py`.
5. Deploy.

## Ticker file format

Yahoo Finance typically represents SGX counters using the `.SI` suffix.

```csv
Ticker,Company
D05.SI,DBS Group Holdings
O39.SI,Oversea-Chinese Banking Corporation
U11.SI,United Overseas Bank
```

You may either edit `sgx_tickers.csv` or upload another CSV from the app sidebar.

## Signal statuses

- `WATCHING` — valid HH/LL structure found; neither breakout nor invalidation has occurred.
- `TRIGGERED` — Open or Close crossed above HH Day-2 before invalidation.
- `INVALIDATED` — Open or Close crossed below LL Day-2 first.

## Notes

This project uses Yahoo Finance data via `yfinance`. Yahoo data availability, ticker coverage, corporate-action handling, and rate limits can change. Validate important signals against another market-data source before acting on them.

This tool is for research and screening only and is not an investment recommendation.

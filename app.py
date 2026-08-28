from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data import (
    download_history,
    download_histories,
    latest_market_dates,
    load_sgx_universe,
)
from scanner import most_recent_triggered_setup


APP_DIR = Path(__file__).resolve().parent
DEFAULT_TICKERS = APP_DIR / "sgx_tickers.csv"
RECENT_TRADING_DAYS = 3

st.set_page_config(page_title="SGX Recent Trigger Scanner", page_icon="📈", layout="wide")

st.title("SGX Recent Trigger Scanner")
st.caption(
    "Shows only SGX stocks triggered on one of the latest 3 completed trading days. "
    "Pattern: 3 consecutive higher highs → nearest subsequent 3 consecutive lower lows → "
    "Open/Close breakout above HH Day-2, provided no earlier Open/Close fell below LL Day-2."
)

with st.sidebar:
    st.header("Scan settings")
    period = st.selectbox("Historical lookback", ["6mo", "1y", "2y", "5y"], index=2)
    st.info("Signal window is fixed at the latest **3 completed SGX trading days**.")
    st.caption("Today's candle is excluded while the SGX trading day is still in progress.")

try:
    ticker_df, universe_source = load_sgx_universe(DEFAULT_TICKERS)
except Exception as exc:
    st.error(f"Could not load SGX ticker universe: {exc}")
    st.stop()

c1, c2 = st.columns(2)
c1.metric("SGX counters to scan", len(ticker_df))
c2.metric("Trigger window", "3 trading days")
st.caption(f"Universe source: {universe_source}")

if "recent_trigger_results" not in st.session_state:
    st.session_state.recent_trigger_results = pd.DataFrame()
if "recent_trigger_dates" not in st.session_state:
    st.session_state.recent_trigger_dates = []

if st.button("Scan all SGX stocks", type="primary", use_container_width=True):
    tickers = ticker_df["Ticker"].tolist()

    status_text = st.empty()
    progress = st.progress(0)
    status_text.text(f"Downloading daily OHLC data for {len(tickers)} SGX counters...")

    histories = download_histories(tickers, period=period)
    market_dates = latest_market_dates(histories, RECENT_TRADING_DAYS)
    st.session_state.recent_trigger_dates = market_dates

    rows = []
    total = len(ticker_df)

    for pos, (_, row) in enumerate(ticker_df.iterrows(), start=1):
        ticker = row["Ticker"]
        company = row["Company"]
        status_text.text(f"Scanning {pos}/{total}: {ticker} — {company}")

        history = histories.get(ticker, pd.DataFrame())
        if history is not None and not history.empty:
            try:
                setup = most_recent_triggered_setup(history, eligible_dates=market_dates)
                if setup is not None:
                    close_col = history["Close"]
                    if isinstance(close_col, pd.DataFrame):
                        close_col = close_col.iloc[:, 0]
                    current_close = float(pd.to_numeric(close_col, errors="coerce").dropna().iloc[-1])

                    # Entry follows the user's rule: if Open itself is already above HH2,
                    # use Open; otherwise the Close is the breakout entry reference.
                    if setup.breakout_open is not None and setup.breakout_open > setup.upper_trigger:
                        entry_price = float(setup.breakout_open)
                        entry_type = "Open"
                    else:
                        entry_price = float(setup.breakout_close)
                        entry_type = "Close"

                    target_10 = entry_price * 1.10
                    stop_pct = (setup.lower_invalidation / entry_price - 1) * 100
                    target_distance_pct = (target_10 / current_close - 1) * 100

                    rows.append(
                        {
                            "Ticker": ticker,
                            "Company": company,
                            "Trigger Date": setup.breakout_date.date(),
                            "Entry Type": entry_type,
                            "Entry Price": round(entry_price, 4),
                            "+10% Target": round(target_10, 4),
                            "LL2 Stop": round(setup.lower_invalidation, 4),
                            "Current Close": round(current_close, 4),
                            "Stop from Entry %": round(stop_pct, 2),
                            "Distance to +10% Target %": round(target_distance_pct, 2),
                            "HH2 Trigger": round(setup.upper_trigger, 4),
                            "HH1 Date": setup.hh1_date.date(),
                            "HH2 Date": setup.hh2_date.date(),
                            "HH3 Date": setup.hh3_date.date(),
                            "LL1 Date": setup.ll1_date.date(),
                            "LL2 Date": setup.ll2_date.date(),
                            "LL3 Date": setup.ll3_date.date(),
                        }
                    )
            except Exception:
                # A failed/unsupported Yahoo symbol should not stop the full-market scan.
                pass

        progress.progress(pos / total)

    status_text.empty()
    progress.empty()
    st.session_state.recent_trigger_results = pd.DataFrame(rows)

market_dates = st.session_state.recent_trigger_dates
if market_dates:
    formatted = ", ".join(pd.Timestamp(d).strftime("%d %b %Y") for d in market_dates)
    st.success(f"Latest completed SGX trading dates used: {formatted}")

results = st.session_state.recent_trigger_results.copy()

if results.empty:
    if market_dates:
        st.info("No SGX counters triggered on any of the latest 3 completed trading days.")
    else:
        st.info("Press **Scan all SGX stocks** to find newly triggered counters.")
else:
    results = results.sort_values(["Trigger Date", "Ticker"], ascending=[False, True]).reset_index(drop=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("Recent triggers", len(results))
    c2.metric("Newest trigger date", str(results["Trigger Date"].max()))
    c3.metric("Universe scanned", len(ticker_df))

    st.subheader("Triggered within the latest 3 trading days")
    shortlist_cols = [
        "Ticker",
        "Company",
        "Trigger Date",
        "Entry Type",
        "Entry Price",
        "+10% Target",
        "LL2 Stop",
        "Current Close",
        "Stop from Entry %",
        "Distance to +10% Target %",
        "HH2 Trigger",
    ]
    st.dataframe(results[shortlist_cols], use_container_width=True, hide_index=True)

    st.download_button(
        "Download recent triggers CSV",
        data=results.to_csv(index=False).encode("utf-8"),
        file_name="sgx_recent_3day_triggers.csv",
        mime="text/csv",
    )

    st.subheader("Inspect triggered stock")
    ticker_choice = st.selectbox("Select ticker", results["Ticker"].tolist())
    selected = results[results["Ticker"] == ticker_choice].iloc[0]

    chart_df = download_history(ticker_choice, period)
    if isinstance(chart_df.columns, pd.MultiIndex):
        chart_df.columns = chart_df.columns.get_level_values(0)

    fig = go.Figure(
        data=[
            go.Candlestick(
                x=chart_df.index,
                open=chart_df["Open"],
                high=chart_df["High"],
                low=chart_df["Low"],
                close=chart_df["Close"],
                name=ticker_choice,
            )
        ]
    )
    fig.add_hline(y=float(selected["HH2 Trigger"]), line_dash="dash", annotation_text="HH2 trigger")
    fig.add_hline(y=float(selected["LL2 Stop"]), line_dash="dot", annotation_text="LL2 stop")
    fig.add_hline(y=float(selected["+10% Target"]), line_dash="dashdot", annotation_text="+10% target")
    fig.update_layout(height=650, xaxis_rangeslider_visible=False, title=f"{ticker_choice} recent trigger")
    st.plotly_chart(fig, use_container_width=True)

st.caption(
    "Technical research screener only — not an investment recommendation. The live universe endpoint may occasionally "
    "be unavailable; when that happens the app uses the bundled fallback ticker list and labels it accordingly."
)

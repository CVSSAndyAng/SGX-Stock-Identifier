from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data import download_history, load_ticker_file
from scanner import latest_relevant_setup


APP_DIR = Path(__file__).resolve().parent
DEFAULT_TICKERS = APP_DIR / "sgx_tickers.csv"

st.set_page_config(page_title="SGX Technical Pattern Screener", page_icon="📈", layout="wide")

st.title("SGX Technical Pattern Screener")
st.caption(
    "Pattern: 3 consecutive higher highs → nearest subsequent 3 consecutive lower lows → "
    "Open/Close breakout above HH Day-2 before any Open/Close invalidation below LL Day-2."
)

with st.sidebar:
    st.header("Scan settings")
    period = st.selectbox("Historical lookback", ["6mo", "1y", "2y", "5y"], index=2)
    include_watching = st.checkbox("Show WATCHING setups", value=True)
    include_triggered = st.checkbox("Show TRIGGERED setups", value=True)
    include_invalidated = st.checkbox("Show INVALIDATED setups", value=False)

    uploaded = st.file_uploader("Optional custom ticker CSV", type=["csv"])
    st.caption("CSV columns: Ticker, Company. Yahoo SGX tickers normally end in .SI")

try:
    ticker_df = load_ticker_file(uploaded if uploaded is not None else DEFAULT_TICKERS)
except Exception as exc:
    st.error(f"Could not load ticker list: {exc}")
    st.stop()

st.write(f"Ticker universe: **{len(ticker_df)}** counters")

if "scan_results" not in st.session_state:
    st.session_state.scan_results = pd.DataFrame()

if st.button("Scan SGX", type="primary", use_container_width=True):
    rows = []
    progress = st.progress(0)
    status_text = st.empty()

    total = len(ticker_df)
    for idx, row in ticker_df.iterrows():
        ticker = row["Ticker"]
        company = row["Company"]
        status_text.text(f"Scanning {ticker} — {company}")

        try:
            history = download_history(ticker, period)
            setup = latest_relevant_setup(history)

            if setup is not None:
                current_close = None
                if history is not None and not history.empty:
                    try:
                        close_col = history["Close"]
                        if isinstance(close_col, pd.DataFrame):
                            close_col = close_col.iloc[:, 0]
                        current_close = float(pd.to_numeric(close_col, errors="coerce").dropna().iloc[-1])
                    except Exception:
                        current_close = None

                distance_pct = None
                if current_close is not None and setup.upper_trigger:
                    distance_pct = (current_close / setup.upper_trigger - 1) * 100

                rows.append(
                    {
                        "Ticker": ticker,
                        "Company": company,
                        "Status": setup.status,
                        "HH1 Date": setup.hh1_date.date(),
                        "HH2 Date": setup.hh2_date.date(),
                        "HH3 Date": setup.hh3_date.date(),
                        "HH2 Trigger": round(setup.upper_trigger, 4),
                        "LL1 Date": setup.ll1_date.date(),
                        "LL2 Date": setup.ll2_date.date(),
                        "LL3 Date": setup.ll3_date.date(),
                        "LL2 Invalidation": round(setup.lower_invalidation, 4),
                        "Current Close": round(current_close, 4) if current_close is not None else None,
                        "Distance to HH2 %": round(distance_pct, 2) if distance_pct is not None else None,
                        "Breakout Date": setup.breakout_date.date() if setup.breakout_date else None,
                        "Breakout Open": round(setup.breakout_open, 4) if setup.breakout_open is not None else None,
                        "Breakout Close": round(setup.breakout_close, 4) if setup.breakout_close is not None else None,
                        "Invalidated Date": setup.invalidated_date.date() if setup.invalidated_date else None,
                    }
                )
        except Exception as exc:
            rows.append(
                {
                    "Ticker": ticker,
                    "Company": company,
                    "Status": "DATA ERROR",
                    "Error": str(exc),
                }
            )

        progress.progress((idx + 1) / total)

    status_text.empty()
    progress.empty()
    st.session_state.scan_results = pd.DataFrame(rows)

results = st.session_state.scan_results.copy()

if not results.empty:
    allowed = []
    if include_watching:
        allowed.append("WATCHING")
    if include_triggered:
        allowed.append("TRIGGERED")
    if include_invalidated:
        allowed.append("INVALIDATED")

    filtered = results[results["Status"].isin(allowed)].copy() if allowed else results.iloc[0:0]

    c1, c2, c3 = st.columns(3)
    c1.metric("Triggered", int((results["Status"] == "TRIGGERED").sum()))
    c2.metric("Watching", int((results["Status"] == "WATCHING").sum()))
    c3.metric("Invalidated", int((results["Status"] == "INVALIDATED").sum()))

    st.subheader("Shortlist")
    if filtered.empty:
        st.info("No counters match the currently selected status filters.")
    else:
        preferred_cols = [
            "Ticker", "Company", "Status", "HH2 Trigger", "LL2 Invalidation",
            "Current Close", "Distance to HH2 %", "Breakout Date",
            "HH1 Date", "HH2 Date", "HH3 Date", "LL1 Date", "LL2 Date", "LL3 Date"
        ]
        shown_cols = [c for c in preferred_cols if c in filtered.columns]
        st.dataframe(
            filtered[shown_cols].sort_values(
                by=["Status", "Distance to HH2 %"],
                ascending=[True, False],
                na_position="last",
            ),
            use_container_width=True,
            hide_index=True,
        )

        csv_bytes = filtered.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download shortlist CSV",
            data=csv_bytes,
            file_name="sgx_pattern_shortlist.csv",
            mime="text/csv",
        )

        st.subheader("Inspect chart")
        ticker_choice = st.selectbox("Select ticker", filtered["Ticker"].tolist())
        selected = filtered[filtered["Ticker"] == ticker_choice].iloc[0]

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
        fig.add_hline(y=float(selected["LL2 Invalidation"]), line_dash="dot", annotation_text="LL2 invalidation")
        fig.update_layout(height=650, xaxis_rangeslider_visible=False, title=f"{ticker_choice} price chart")
        st.plotly_chart(fig, use_container_width=True)

        st.caption(
            "Important: this is a technical screening tool, not an investment recommendation. "
            "Verify data quality and corporate actions before relying on any signal."
        )
else:
    st.info("Press **Scan SGX** to run the pattern screen.")

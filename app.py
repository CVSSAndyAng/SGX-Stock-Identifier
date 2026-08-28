from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data import (
    OFFICIAL_SGX_BASELINE,
    download_history,
    download_histories,
    latest_market_dates,
    load_sgx_universe,
)
from scanner import most_recent_triggered_setup


APP_DIR = Path(__file__).resolve().parent
RECENT_TRADING_DAYS = 3

st.set_page_config(page_title="SGX Recent Trigger Scanner", page_icon="📈", layout="wide")

st.title("SGX Recent Trigger Scanner")
st.caption(
    "Full-market SGX technical screener excluding REITs and business trusts. "
    "Shows only counters triggered on one of the latest 3 completed SGX trading days."
)

with st.sidebar:
    st.header("Scan settings")
    period = st.selectbox("Historical lookback", ["6mo", "1y", "2y", "5y"], index=2)
    st.info("Signal window is fixed at the latest **3 completed SGX trading days**.")
    st.caption("No minimum price, market cap, or volume filter. Penny stocks are included.")
    st.caption("REITs and business trusts are excluded before price data is downloaded.")

try:
    ticker_df, universe_source, universe_stats = load_sgx_universe()
except Exception as exc:
    st.error("Could not load the live SGX universe, so the app will not run a partial-market scan.")
    st.code(str(exc))
    st.info("Please retry later. The app intentionally avoids falling back to the old 25-counter starter list.")
    st.stop()

st.subheader("Universe coverage")
c1, c2, c3, c4 = st.columns(4)
c1.metric("SGX official baseline", OFFICIAL_SGX_BASELINE)
c2.metric("Live securities loaded", universe_stats["source_records"])
c3.metric("REITs / trusts removed", universe_stats["excluded_reit_trust"])
c4.metric("Eligible counters", universe_stats["eligible"])

if universe_stats["source_records"] != OFFICIAL_SGX_BASELINE:
    st.warning(
        f"The live source currently returned {universe_stats['source_records']} unique securities versus the "
        f"604-security reference baseline. Listings/delistings or source coverage can change over time. "
        "The scanner reports the actual number loaded rather than claiming 604 when it did not receive 604."
    )

st.caption(
    f"Universe source: {universe_source}. Removed: "
    f"{universe_stats['excluded_reit']} REIT-classified and "
    f"{universe_stats['excluded_business_trust']} trust/business-trust-classified counters."
)

if "recent_trigger_results" not in st.session_state:
    st.session_state.recent_trigger_results = pd.DataFrame()
if "recent_trigger_dates" not in st.session_state:
    st.session_state.recent_trigger_dates = []
if "scan_coverage" not in st.session_state:
    st.session_state.scan_coverage = {}

if st.button("Scan eligible SGX stocks", type="primary", use_container_width=True):
    tickers = ticker_df["Ticker"].tolist()

    status_text = st.empty()
    progress = st.progress(0)
    status_text.text(f"Downloading daily OHLC data for {len(tickers)} eligible SGX counters...")

    histories = download_histories(tickers, period=period)
    market_dates = latest_market_dates(histories, RECENT_TRADING_DAYS)
    st.session_state.recent_trigger_dates = market_dates

    usable_count = sum(1 for df in histories.values() if df is not None and not df.empty)
    unavailable_count = len(tickers) - usable_count

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
                pass

        progress.progress(pos / total)

    status_text.empty()
    progress.empty()
    st.session_state.recent_trigger_results = pd.DataFrame(rows)
    st.session_state.scan_coverage = {
        "eligible": len(tickers),
        "usable": usable_count,
        "unavailable": unavailable_count,
        "triggered": len(rows),
    }

market_dates = st.session_state.recent_trigger_dates
if market_dates:
    formatted = ", ".join(pd.Timestamp(d).strftime("%d %b %Y") for d in market_dates)
    st.success(f"Latest completed SGX trading dates used: {formatted}")

coverage = st.session_state.scan_coverage
if coverage:
    st.subheader("Last scan coverage")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Eligible universe", coverage["eligible"])
    c2.metric("Usable Yahoo OHLC", coverage["usable"])
    c3.metric("No/insufficient data", coverage["unavailable"])
    c4.metric("Triggered ≤3 days", coverage["triggered"])

results = st.session_state.recent_trigger_results.copy()

if results.empty:
    if market_dates:
        st.info("No eligible SGX counters triggered on any of the latest 3 completed trading days.")
    else:
        st.info("Press **Scan eligible SGX stocks** to find newly triggered counters.")
else:
    results = results.sort_values(["Trigger Date", "Ticker"], ascending=[False, True]).reset_index(drop=True)

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
        file_name="sgx_recent_3day_triggers_ex_reit_trust.csv",
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
    "Technical research screener only — not an investment recommendation. REITs and business trusts are excluded. "
    "Penny stocks remain included. Yahoo symbols can be missing or suspended, so scan coverage is shown explicitly."
)

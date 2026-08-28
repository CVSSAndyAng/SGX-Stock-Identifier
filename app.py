from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data import (
    OFFICIAL_SGX_BASELINE,
    download_history,
    download_histories,
    latest_market_bars,
    latest_market_dates,
    load_sgx_universe,
)
from indicators import macd_qualifies
from scanner import most_recent_triggered_setup

RECENT_CANDLES = 3
DEFAULT_MACD_NEAR_ZERO_PCT = 0.5

st.set_page_config(page_title="SGX HH/LL + MACD Scanner", page_icon="📈", layout="wide")
st.title("SGX HH/LL + MACD Stock Scanner")
st.caption(
    "All eligible SGX stocks including penny stocks, excluding REITs and business trusts. "
    "Choose Daily or Hourly candles; Condition 2 / transaction activity has been removed."
)

with st.sidebar:
    st.header("Scan settings")
    mode = st.radio("Candle timeframe", ["Daily", "Hourly"], horizontal=True)

    if mode == "Daily":
        period = st.selectbox("Historical lookback", ["6mo", "1y", "2y", "5y"], index=2)
        interval = "1d"
        window_label = "latest 3 completed SGX trading days"
    else:
        # Yahoo intraday history is more constrained than daily history. Six months
        # gives hundreds of 60-minute candles and ample MACD/pattern warm-up.
        period = st.selectbox("Hourly lookback", ["1mo", "3mo", "6mo", "1y"], index=2)
        interval = "60m"
        window_label = "latest 3 completed 1-hour SGX candles"

    macd_near_zero_pct = st.slider(
        "MACD near-zero allowance (% of price)",
        min_value=0.1,
        max_value=2.0,
        value=DEFAULT_MACD_NEAR_ZERO_PCT,
        step=0.1,
        help="MACD may still be slightly negative while rising toward zero. Default floor: -0.5% of price.",
    )

    st.info(f"Signal window: **{window_label}**.")
    st.caption("MACD: 12/26/9, rising for 3 candles, above signal, and not below the selected near-zero floor.")
    st.caption("No transaction-count, volume, minimum-price, or market-cap filter.")

st.subheader("Active conditions")
st.markdown(
    """
**Price structure:** 3 consecutive higher highs → nearest subsequent 3 consecutive lower lows → HH2 is the upper trigger and LL2 is the invalidation level. After LL3, a setup triggers when Open or Close rises above HH2, provided no earlier Open or Close fell below LL2.

**MACD confirmation:** MACD(12,26,9) must be rising across the latest 3 candles as of the trigger candle, be above its signal line, and be at or above the configured near-zero floor.
"""
)

if mode == "Hourly":
    st.warning(
        "Hourly mode applies the same rules to completed 60-minute candles. It is a separate, faster-timeframe screen: "
        "HH1/HH2/HH3, LL1/LL2/LL3, breakout, and MACD are all calculated from hourly candles, not daily candles."
    )

try:
    ticker_df, universe_source, universe_stats = load_sgx_universe()
except Exception as exc:
    st.error("Could not load the live SGX universe, so the app will not run a partial-market scan.")
    st.code(str(exc))
    st.stop()

st.subheader("Universe coverage")
c1, c2, c3, c4 = st.columns(4)
c1.metric("SGX reference baseline", OFFICIAL_SGX_BASELINE)
c2.metric("Live securities loaded", universe_stats["source_records"])
c3.metric("REITs / trusts removed", universe_stats["excluded_reit_trust"])
c4.metric("Eligible counters", universe_stats["eligible"])

if universe_stats["source_records"] != OFFICIAL_SGX_BASELINE:
    st.warning(
        f"The live source returned {universe_stats['source_records']} unique securities versus the "
        f"{OFFICIAL_SGX_BASELINE}-security reference baseline. Actual live coverage is shown rather than claiming a fixed count."
    )

st.caption(
    f"Universe source: {universe_source}. Removed: {universe_stats['excluded_reit']} REIT-classified and "
    f"{universe_stats['excluded_business_trust']} trust/business-trust-classified counters."
)

state_key = f"scan_{mode.lower()}"
if state_key not in st.session_state:
    st.session_state[state_key] = {"results": pd.DataFrame(), "recent": [], "coverage": {}}

scan_clicked = st.button(
    f"Scan all eligible SGX stocks — {mode}",
    type="primary",
    use_container_width=True,
)

if scan_clicked:
    tickers = ticker_df["Ticker"].tolist()
    status_text = st.empty()
    progress = st.progress(0)
    status_text.text(f"Downloading {mode.lower()} OHLC data for {len(tickers)} eligible SGX counters...")

    histories = download_histories(tickers, period=period, interval=interval)
    if mode == "Daily":
        recent = latest_market_dates(histories, RECENT_CANDLES)
        exact_timestamp = False
    else:
        recent = latest_market_bars(histories, RECENT_CANDLES)
        exact_timestamp = True

    usable_count = sum(1 for df in histories.values() if df is not None and not df.empty)
    rows = []
    pattern_count = 0
    macd_count = 0
    total = len(ticker_df)

    for pos, (_, row) in enumerate(ticker_df.iterrows(), start=1):
        ticker = row["Ticker"]
        company = row["Company"]
        status_text.text(f"Scanning {pos}/{total}: {ticker} — {company}")
        history = histories.get(ticker, pd.DataFrame())
        if history is None or history.empty:
            progress.progress(pos / total)
            continue

        try:
            setup = most_recent_triggered_setup(history, eligible_dates=recent, exact_timestamp=exact_timestamp)
            if setup is None:
                progress.progress(pos / total)
                continue
            pattern_count += 1

            macd_ok, macd_details = macd_qualifies(
                history,
                as_of_date=setup.breakout_date,
                near_zero_floor_pct=-float(macd_near_zero_pct),
                rising_days=3,
                exact_timestamp=exact_timestamp,
            )
            if not macd_ok:
                progress.progress(pos / total)
                continue
            macd_count += 1

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
            trigger_ts = pd.Timestamp(setup.breakout_date)
            rows.append({
                "Ticker": ticker,
                "Company": company,
                "Timeframe": mode,
                "Trigger": trigger_ts.strftime("%Y-%m-%d") if mode == "Daily" else trigger_ts.strftime("%Y-%m-%d %H:%M"),
                "Entry Type": entry_type,
                "Entry Price": round(entry_price, 4),
                "+10% Target": round(target_10, 4),
                "LL2 Stop": round(setup.lower_invalidation, 4),
                "Current Close": round(current_close, 4),
                "MACD": round(macd_details["macd"], 6),
                "MACD Signal": round(macd_details["signal"], 6),
                "MACD % of Price": round(macd_details["macd_pct"], 4),
                "HH2 Trigger": round(setup.upper_trigger, 4),
                "HH1": pd.Timestamp(setup.hh1_date),
                "HH2": pd.Timestamp(setup.hh2_date),
                "HH3": pd.Timestamp(setup.hh3_date),
                "LL1": pd.Timestamp(setup.ll1_date),
                "LL2": pd.Timestamp(setup.ll2_date),
                "LL3": pd.Timestamp(setup.ll3_date),
            })
        except Exception:
            pass
        progress.progress(pos / total)

    status_text.empty()
    progress.empty()
    st.session_state[state_key] = {
        "results": pd.DataFrame(rows),
        "recent": recent,
        "coverage": {
            "eligible": len(tickers),
            "usable": usable_count,
            "unavailable": len(tickers) - usable_count,
            "pattern": pattern_count,
            "macd": macd_count,
        },
    }

state = st.session_state[state_key]
recent = state["recent"]
coverage = state["coverage"]
results = state["results"].copy()

if recent:
    if mode == "Daily":
        formatted = ", ".join(pd.Timestamp(d).strftime("%d %b %Y") for d in recent)
        st.success(f"Completed SGX trading dates used: {formatted}")
    else:
        formatted = ", ".join(pd.Timestamp(d).strftime("%d %b %Y %H:%M") for d in recent)
        st.success(f"Completed SGX hourly candles used: {formatted} (Singapore time)")

if coverage:
    st.subheader("Last scan funnel")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Eligible universe", coverage["eligible"])
    c2.metric("Usable OHLC", coverage["usable"])
    c3.metric("Recent price triggers", coverage["pattern"])
    c4.metric("+ MACD pass", coverage["macd"])
    st.caption(f"No/insufficient OHLC: {coverage['unavailable']} | Final shortlist: {coverage['macd']}")

if results.empty:
    if recent:
        st.info(f"No eligible SGX counters currently satisfy both screening conditions in {mode.lower()} mode.")
    else:
        st.info(f"Press **Scan all eligible SGX stocks — {mode}** to run the screen.")
else:
    results = results.sort_values(["Trigger", "Ticker"], ascending=[False, True]).reset_index(drop=True)
    st.subheader(f"{mode} shortlist — research candidates")
    shortlist_cols = [
        "Ticker", "Company", "Trigger", "Entry Price", "+10% Target", "LL2 Stop",
        "Current Close", "MACD", "MACD Signal", "MACD % of Price",
    ]
    st.dataframe(results[shortlist_cols], use_container_width=True, hide_index=True)

    st.download_button(
        "Download shortlist CSV",
        data=results.to_csv(index=False).encode("utf-8"),
        file_name=f"sgx_{mode.lower()}_shortlist.csv",
        mime="text/csv",
    )

    st.subheader("Inspect shortlisted stock")
    ticker_choice = st.selectbox("Select ticker", results["Ticker"].tolist(), key=f"ticker_{mode}")
    selected = results[results["Ticker"] == ticker_choice].iloc[0]
    chart_df = download_history(ticker_choice, period=period, interval=interval)

    fig = go.Figure(data=[go.Candlestick(
        x=chart_df.index,
        open=chart_df["Open"], high=chart_df["High"], low=chart_df["Low"], close=chart_df["Close"],
        name=ticker_choice,
    )])
    fig.add_hline(y=float(selected["HH2 Trigger"]), line_dash="dash", annotation_text="HH2 trigger")
    fig.add_hline(y=float(selected["LL2 Stop"]), line_dash="dot", annotation_text="LL2 stop")
    fig.add_hline(y=float(selected["+10% Target"]), line_dash="dashdot", annotation_text="+10% target")
    fig.update_layout(height=650, xaxis_rangeslider_visible=False, title=f"{ticker_choice} — {mode} qualifying setup")
    st.plotly_chart(fig, use_container_width=True)

st.caption(
    "Technical research screener only — not an investment recommendation. REITs and business trusts are excluded; "
    "penny stocks remain eligible. Condition 2 / transaction activity has been removed."
)

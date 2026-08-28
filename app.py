from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from activity import download_intraday_activity, conservative_activity_qualifies
from data import (
    OFFICIAL_SGX_BASELINE,
    download_history,
    download_histories,
    latest_market_dates,
    load_sgx_universe,
)
from indicators import macd_qualifies
from scanner import most_recent_triggered_setup

RECENT_TRADING_DAYS = 3
TRANSACTION_WINDOW_DAYS = 20
MIN_DAILY_TRANSACTIONS = 5
DEFAULT_MACD_NEAR_ZERO_PCT = 0.5

st.set_page_config(page_title="SGX Multi-Condition Scanner", page_icon="📈", layout="wide")

st.title("SGX Multi-Condition Stock Scanner")
st.caption(
    "All eligible SGX stocks (including penny stocks; excluding REITs and business trusts). "
    "A counter appears only when the price-structure trigger, MACD filter, and automatic activity filter all pass."
)

with st.sidebar:
    st.header("Scan settings")
    period = st.selectbox("Historical lookback", ["6mo", "1y", "2y", "5y"], index=2)
    macd_near_zero_pct = st.slider(
        "MACD near-zero allowance (% of price)",
        min_value=0.1,
        max_value=2.0,
        value=DEFAULT_MACD_NEAR_ZERO_PCT,
        step=0.1,
        help="Allows MACD to remain slightly negative while rising toward zero. Default: -0.5% of share price.",
    )
    st.info("Signal window: latest **3 completed SGX trading days**.")
    st.caption("MACD: 12/26/9, rising for 3 trading days, above signal, and at least the selected near-zero floor.")
    st.caption("Activity: at least 5 separate positive-volume 5-minute bars on each of the prior 20 SGX trading days (conservative proof of ≥5 trades).")
    st.caption("No minimum price, market cap, or share-volume filter.")

st.subheader("Automatic activity verification")
st.write(
    "No file upload is required. The app automatically checks Yahoo 5-minute intraday data. "
    "Because the free feed does not expose SGX's exact daily number-of-trades field, a day passes only when "
    "there are at least **5 separate positive-volume 5-minute bars**. This is conservative: 5 such bars prove "
    "at least 5 trades occurred, but trades clustered inside fewer bars can cause a false rejection."
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
        f"{OFFICIAL_SGX_BASELINE}-security reference baseline. The app reports actual live coverage rather than "
        "claiming a fixed universe when listings or source coverage have changed."
    )

st.caption(
    f"Universe source: {universe_source}. Removed: "
    f"{universe_stats['excluded_reit']} REIT-classified and "
    f"{universe_stats['excluded_business_trust']} trust/business-trust-classified counters."
)

if "filtered_results" not in st.session_state:
    st.session_state.filtered_results = pd.DataFrame()
if "recent_trigger_dates" not in st.session_state:
    st.session_state.recent_trigger_dates = []
if "scan_coverage" not in st.session_state:
    st.session_state.scan_coverage = {}

scan_clicked = st.button(
    "Scan all eligible SGX stocks",
    type="primary",
    use_container_width=True,
)

if scan_clicked:
    tickers = ticker_df["Ticker"].tolist()

    status_text = st.empty()
    progress = st.progress(0)
    status_text.text(f"Downloading daily OHLC data for {len(tickers)} eligible SGX counters...")

    histories = download_histories(tickers, period=period)
    status_text.text(f"Downloading 5-minute activity data for {len(tickers)} eligible SGX counters...")
    intraday_activity = download_intraday_activity(tickers, period="60d", interval="5m")
    all_recent_market_dates = latest_market_dates(histories, max(35, TRANSACTION_WINDOW_DAYS + RECENT_TRADING_DAYS + 5))
    market_dates = all_recent_market_dates[-RECENT_TRADING_DAYS:]
    st.session_state.recent_trigger_dates = market_dates

    usable_count = sum(1 for df in histories.values() if df is not None and not df.empty)
    unavailable_count = len(tickers) - usable_count

    pattern_count = 0
    macd_count = 0
    transaction_count = 0
    rows = []
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
            setup = most_recent_triggered_setup(history, eligible_dates=market_dates)
            if setup is None:
                progress.progress(pos / total)
                continue
            pattern_count += 1

            macd_ok, macd_details = macd_qualifies(
                history,
                as_of_date=setup.breakout_date,
                near_zero_floor_pct=-float(macd_near_zero_pct),
                rising_days=3,
            )
            if not macd_ok:
                progress.progress(pos / total)
                continue
            macd_count += 1

            activity_ok, activity_details = conservative_activity_qualifies(
                intraday_activity.get(ticker, pd.DataFrame()),
                market_dates=all_recent_market_dates,
                as_of_date=setup.breakout_date,
                min_transactions=MIN_DAILY_TRANSACTIONS,
                required_trading_days=TRANSACTION_WINDOW_DAYS,
            )
            if not activity_ok:
                progress.progress(pos / total)
                continue
            transaction_count += 1

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
                    "MACD": round(macd_details["macd"], 6),
                    "MACD Signal": round(macd_details["signal"], 6),
                    "MACD % of Price": round(macd_details["macd_pct"], 4),
                    "Min Active 5m Bars (20D)": int(activity_details["minimum_nonempty_bars"]),
                    "Avg Active 5m Bars (20D)": round(activity_details["average_nonempty_bars"], 1),
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
    st.session_state.filtered_results = pd.DataFrame(rows)
    st.session_state.scan_coverage = {
        "eligible": len(tickers),
        "usable": usable_count,
        "unavailable": unavailable_count,
        "pattern": pattern_count,
        "macd": macd_count,
        "activity": transaction_count,
        "final": len(rows),
    }

market_dates = st.session_state.recent_trigger_dates
if market_dates:
    formatted = ", ".join(pd.Timestamp(d).strftime("%d %b %Y") for d in market_dates)
    st.success(f"Latest completed SGX trading dates used: {formatted}")

coverage = st.session_state.scan_coverage
if coverage:
    st.subheader("Last scan funnel")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Usable OHLC", coverage["usable"])
    c2.metric("Recent price triggers", coverage["pattern"])
    c3.metric("+ MACD pass", coverage["macd"])
    c4.metric("+ 20D activity pass", coverage["final"])
    st.caption(
        f"Eligible universe: {coverage['eligible']} | No/insufficient OHLC: {coverage['unavailable']} | "
        f"Final shortlist: {coverage['final']}"
    )

results = st.session_state.filtered_results.copy()

if results.empty:
    if market_dates:
        st.info("No eligible SGX counters currently satisfy all three screening conditions.")
    else:
        st.info("Press **Scan all eligible SGX stocks** to run the automatic screen.")
else:
    results = results.sort_values(["Trigger Date", "Ticker"], ascending=[False, True]).reset_index(drop=True)

    st.subheader("Stocks satisfying all conditions")
    shortlist_cols = [
        "Ticker",
        "Company",
        "Trigger Date",
        "Entry Price",
        "+10% Target",
        "LL2 Stop",
        "Current Close",
        "MACD",
        "MACD Signal",
        "MACD % of Price",
        "Min Active 5m Bars (20D)",
        "Avg Active 5m Bars (20D)",
    ]
    st.dataframe(results[shortlist_cols], use_container_width=True, hide_index=True)

    st.download_button(
        "Download shortlist CSV",
        data=results.to_csv(index=False).encode("utf-8"),
        file_name="sgx_all_conditions_shortlist.csv",
        mime="text/csv",
    )

    st.subheader("Inspect shortlisted stock")
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
    fig.update_layout(height=650, xaxis_rangeslider_visible=False, title=f"{ticker_choice} qualifying setup")
    st.plotly_chart(fig, use_container_width=True)

st.caption(
    "Technical research screener only — not an investment recommendation. The activity condition uses a conservative "
    "lower-bound check from positive-volume 5-minute bars because the free feed does not expose exact SGX trade counts. "
    "REITs and business trusts are excluded; penny stocks remain eligible."
)

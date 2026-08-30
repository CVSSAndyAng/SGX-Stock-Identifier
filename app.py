from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data import (
    OFFICIAL_SGX_BASELINE,
    OFFICIAL_SGX_BASELINE_LABEL,
    download_history,
    download_histories,
    latest_market_bars,
    latest_market_dates,
    load_sgx_universe,
)
from indicators import macd_qualifies
from scanner import most_recent_hh_close_breakout, most_recent_triggered_setup

RECENT_CANDLES = 3
DEFAULT_MACD_NEAR_ZERO_PCT = 0.5

st.set_page_config(
    page_title="SGX HH/LL + MACD Scanner",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Responsive styling for phones and small tablets. This changes presentation only;
# screening logic and calculations remain untouched.
st.markdown(
    """
    <style>
    /* Comfortable desktop spacing while preserving Streamlit's responsive width. */
    .block-container {
        padding-top: 1.25rem;
        padding-bottom: 2rem;
        max-width: 1400px;
    }

    /* Make primary actions easy to tap. */
    div.stButton > button,
    div.stDownloadButton > button {
        min-height: 2.8rem;
        border-radius: 0.65rem;
    }

    /* Prevent long table contents from breaking the page width. */
    [data-testid="stDataFrame"] {
        max-width: 100%;
        overflow-x: auto;
    }

    @media (max-width: 768px) {
        .block-container {
            padding-top: 0.75rem !important;
            padding-left: 0.8rem !important;
            padding-right: 0.8rem !important;
            padding-bottom: 1.5rem !important;
        }

        h1 {
            font-size: 1.75rem !important;
            line-height: 1.15 !important;
            margin-bottom: 0.4rem !important;
        }
        h2 {
            font-size: 1.35rem !important;
            line-height: 1.2 !important;
        }
        h3 {
            font-size: 1.15rem !important;
        }
        p, li, label, [data-testid="stCaptionContainer"] {
            font-size: 0.95rem !important;
            line-height: 1.45 !important;
        }

        /* Stack Streamlit column groups vertically on phones. */
        [data-testid="stHorizontalBlock"] {
            flex-direction: column !important;
            gap: 0.55rem !important;
        }
        [data-testid="column"] {
            width: 100% !important;
            flex: 1 1 100% !important;
            min-width: 100% !important;
        }

        /* Full-width tap targets. */
        div.stButton > button,
        div.stDownloadButton > button {
            width: 100% !important;
            min-height: 3rem !important;
            font-size: 1rem !important;
        }

        /* Keep form controls readable and touch friendly. */
        [data-baseweb="select"] > div,
        [data-baseweb="input"] > div,
        [role="radiogroup"] {
            min-height: 2.75rem;
        }

        /* Compact alert boxes on narrow screens. */
        [data-testid="stAlert"] {
            padding: 0.7rem 0.8rem !important;
        }

        /* Let wide result tables scroll horizontally instead of squeezing text. */
        [data-testid="stDataFrame"] > div {
            overflow-x: auto !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("SGX HH/LL + MACD Stock Scanner")
st.caption(
    "All eligible SGX stocks including penny stocks, excluding REITs and business trusts. "
    "Choose Daily or Hourly candles; Condition 2 / transaction activity has been removed."
)

st.subheader("Scan options")

with st.container(border=True):
    option_col1, option_col2 = st.columns(2)

    with option_col1:
        mode = st.radio(
            "Candle timeframe",
            ["Daily", "Hourly"],
            horizontal=True,
            key="candle_timeframe",
        )

    with option_col2:
        price_mode = st.radio(
            "Price setup",
            ["Full HH → LL confirmation", "HH2 close breakout only"],
            horizontal=False,
            key="price_setup",
            help="HH2 close breakout only ignores the lower-low sequence and requires Close > HH2.",
        )

    settings_col1, settings_col2 = st.columns(2)

    with settings_col1:
        if mode == "Daily":
            period = st.selectbox("Historical lookback", ["6mo", "1y", "2y", "5y"], index=2)
            interval = "1d"
            window_label = "latest 3 completed SGX trading days"
        else:
            period = st.selectbox("Hourly lookback", ["1mo", "3mo", "6mo", "1y"], index=2)
            interval = "60m"
            window_label = "latest 3 completed 1-hour SGX candles"

    with settings_col2:
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

with st.expander("Active conditions", expanded=False):
    st.markdown(
        """
**Price structure — Full HH → LL confirmation:** 3 consecutive higher highs → nearest subsequent 3 consecutive lower lows → HH2 is the upper trigger and LL2 is the invalidation level. After LL3, a setup triggers when Open or Close rises above HH2, provided no earlier Open or Close fell below LL2.

**Price structure — HH2 close breakout only:** 3 consecutive higher highs → HH2 is the upper trigger → from HH3 onward, the first candle with **Close > HH2** triggers. No lower-low sequence or LL invalidation is required.

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
c1.metric("604 reference", OFFICIAL_SGX_BASELINE)
c2.metric("Current market symbols loaded", universe_stats["source_records"])
c3.metric("Non-eligible removed", universe_stats["excluded_total"])
c4.metric("Eligible stock counters", universe_stats["eligible"])

st.caption(f"Reference: {OFFICIAL_SGX_BASELINE_LABEL}. The reference is historical; the live market count can change with listings and delistings.")

st.markdown(
    f"**Universe exclusions:** REITs **{universe_stats['excluded_reit']}** · "
    f"Business trusts/trusts **{universe_stats['excluded_business_trust']}** · "
    f"ETFs/funds **{universe_stats['excluded_etf_fund']}** · "
    f"Global Quote/SDR **{universe_stats['excluded_global_quote']}**"
)
st.caption(
    f"Universe source: {universe_source}. SGX Global Quote names discovered for classification: "
    f"{universe_stats['global_quote_names_loaded']}. Penny stocks are retained; no minimum price, market-cap or volume filter is applied."
)

if universe_stats["source_records"] < 400:
    st.error(
        "The broad market source returned fewer than 400 symbols. The app will not describe this as full-market coverage. "
        "Try again later before relying on the shortlist."
    )

state_key = f"scan_{mode.lower()}_{'hh_only' if price_mode == 'HH2 close breakout only' else 'hh_ll'}"
if state_key not in st.session_state:
    st.session_state[state_key] = {"results": pd.DataFrame(), "recent": [], "coverage": {}}

scan_clicked = st.button(
    f"Scan all eligible SGX stocks — {mode} — {price_mode}",
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
            if price_mode == "HH2 close breakout only":
                setup = most_recent_hh_close_breakout(history, eligible_dates=recent, exact_timestamp=exact_timestamp)
            else:
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

            if price_mode == "HH2 close breakout only":
                entry_price = float(setup.breakout_close)
                entry_type = "Close"
                ll2_stop = None
            elif setup.breakout_open is not None and setup.breakout_open > setup.upper_trigger:
                entry_price = float(setup.breakout_open)
                entry_type = "Open"
                ll2_stop = float(setup.lower_invalidation)
            else:
                entry_price = float(setup.breakout_close)
                entry_type = "Close"
                ll2_stop = float(setup.lower_invalidation)

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
                "LL2 Stop": round(ll2_stop, 4) if ll2_stop is not None else None,
                "Current Close": round(current_close, 4),
                "MACD": round(macd_details["macd"], 6),
                "MACD Signal": round(macd_details["signal"], 6),
                "MACD % of Price": round(macd_details["macd_pct"], 4),
                "HH2 Trigger": round(setup.upper_trigger, 4),
                "HH1": pd.Timestamp(setup.hh1_date),
                "HH2": pd.Timestamp(setup.hh2_date),
                "HH3": pd.Timestamp(setup.hh3_date),
                "LL1": pd.Timestamp(setup.ll1_date) if hasattr(setup, "ll1_date") else pd.NaT,
                "LL2": pd.Timestamp(setup.ll2_date) if hasattr(setup, "ll2_date") else pd.NaT,
                "LL3": pd.Timestamp(setup.ll3_date) if hasattr(setup, "ll3_date") else pd.NaT,
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
            "price_mode": price_mode,
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
    st.subheader(f"{mode} shortlist — {price_mode} — research candidates")
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
        use_container_width=True,
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
    if pd.notna(selected["LL2 Stop"]):
        fig.add_hline(y=float(selected["LL2 Stop"]), line_dash="dot", annotation_text="LL2 stop")
    fig.add_hline(y=float(selected["+10% Target"]), line_dash="dashdot", annotation_text="+10% target")
    fig.update_layout(
        height=500,
        xaxis_rangeslider_visible=False,
        title=f"{ticker_choice} — {mode} — {price_mode}",
        margin=dict(l=8, r=8, t=55, b=20),
        legend=dict(orientation="h"),
    )
    st.plotly_chart(fig, use_container_width=True)

st.caption(
    "Technical research screener only — not an investment recommendation. REITs and business trusts are excluded; "
    "penny stocks remain eligible. Condition 2 / transaction activity has been removed."
)

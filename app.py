"""
Stock Analysis Machine
-----------------------
Enter any ticker and get a live, data-driven grade (0-10) and a BUY / HOLD /
SELL signal, based on revenue growth, margins, debt, valuation, and dividends
-- all benchmarked against live industry peer data pulled fresh every run.
"""

import time

import pandas as pd
import streamlit as st

from src.data_fetcher import fetch_stock_data
from src.metrics import build_metrics
from src.scoring import WEIGHTS, grade_stock

st.set_page_config(page_title="Stock Analysis Machine", page_icon="📈", layout="centered")

CACHE_TTL_SECONDS = 15 * 60  # short TTL: fresh data, but avoids hammering Yahoo on every widget click


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _cached_analysis(ticker: str, _cache_bust: int):
    data = fetch_stock_data(ticker)
    metrics = build_metrics(data)
    grade = grade_stock(metrics)
    return grade


def run_analysis(ticker: str, force_refresh: bool):
    if force_refresh:
        _cached_analysis.clear()
    cache_bust = int(time.time() // CACHE_TTL_SECONDS)
    return _cached_analysis(ticker.upper().strip(), cache_bust)


SIGNAL_COLOR = {"BUY": "🟢", "HOLD": "🟡", "SELL": "🔴"}
CATEGORY_LABELS = {
    "growth": "Revenue Growth",
    "profitability": "Profitability",
    "financial_health": "Financial Health (Debt)",
    "valuation": "Valuation",
    "dividend": "Dividend",
    "liquidity": "Liquidity",
}

st.title("📈 Stock Analysis Machine")
st.caption(
    "Grades any stock 0-10 using revenue growth, margins, debt, valuation, "
    "and dividends -- benchmarked live against industry peers on every run."
)

col1, col2 = st.columns([3, 1])
with col1:
    ticker_input = st.text_input("Ticker symbol", value="AAPL", placeholder="e.g. AAPL, MSFT, TSLA").upper()
with col2:
    st.write("")
    st.write("")
    analyze_clicked = st.button("Analyze", type="primary", use_container_width=True)

force_refresh = st.checkbox(
    "Force fresh data (ignore 15-min cache)",
    value=False,
    help="Every analysis fetches live data. This just bypasses the short cache "
    "used to avoid re-hitting Yahoo Finance on every UI click.",
)

if analyze_clicked and ticker_input:
    with st.spinner(f"Fetching live data for {ticker_input}..."):
        try:
            grade = run_analysis(ticker_input, force_refresh)
        except ValueError as e:
            st.error(str(e))
            st.stop()
        except Exception as e:
            st.error(f"Something went wrong fetching data for {ticker_input}: {e}")
            st.stop()

    m = grade.metrics
    st.divider()

    name = m.company_name or m.ticker
    st.subheader(f"{name} ({m.ticker})")
    st.caption(f"{m.sector or 'Unknown sector'} — {m.industry or 'Unknown industry'} — {m.peer_count} peers used for benchmarking")

    score_col, signal_col = st.columns(2)
    score_col.metric("Score", f"{grade.total_score:.1f} / 10")
    signal_col.metric("Signal", f"{SIGNAL_COLOR[grade.signal]} {grade.signal}")

    st.subheader("Score Breakdown")
    breakdown_df = pd.DataFrame(
        [
            {"Category": CATEGORY_LABELS[k], "Points": round(v, 2), "Max": WEIGHTS[k]}
            for k, v in grade.category_scores.items()
        ]
    )
    st.dataframe(breakdown_df, hide_index=True, use_container_width=True)

    st.subheader("Key Metrics")
    metrics_df = pd.DataFrame(
        [
            {"Metric": "Price", "Value": f"${m.price:,.2f}" if m.price else "N/A"},
            {
                "Metric": f"Revenue CAGR ({max(m.years_of_revenue_data - 1, 0)}yr)",
                "Value": f"{m.revenue_growth_5y:.1%}" if m.revenue_growth_5y is not None else "N/A",
            },
            {
                "Metric": "Industry Avg Revenue Growth",
                "Value": f"{m.peer_avg_revenue_growth:.1%}" if m.peer_avg_revenue_growth is not None else "N/A",
            },
            {"Metric": "Gross Margin", "Value": f"{m.gross_margin:.1%}" if m.gross_margin is not None else "N/A"},
            {"Metric": "Operating Margin", "Value": f"{m.operating_margin:.1%}" if m.operating_margin is not None else "N/A"},
            {"Metric": "Net Margin", "Value": f"{m.net_margin:.1%}" if m.net_margin is not None else "N/A"},
            {"Metric": "Total Debt", "Value": f"${m.total_debt:,.0f}" if m.total_debt else "N/A"},
            {"Metric": "Debt-to-Equity", "Value": f"{m.debt_to_equity:.2f}" if m.debt_to_equity is not None else "N/A"},
            {"Metric": "P/E Ratio", "Value": f"{m.pe_ratio:.1f}" if m.pe_ratio is not None else "N/A"},
            {"Metric": "Industry Avg P/E", "Value": f"{m.peer_avg_pe_ratio:.1f}" if m.peer_avg_pe_ratio is not None else "N/A"},
            {"Metric": "Avg Volume", "Value": f"{m.avg_volume:,.0f}" if m.avg_volume else "N/A"},
            {"Metric": "Dividend Yield", "Value": f"{m.dividend_yield:.2%}" if m.dividend_yield else "No dividend"},
            {"Metric": "Dividend Streak", "Value": f"{m.dividend_streak_years} yrs" if m.dividend_yield else "N/A"},
        ]
    )
    st.dataframe(metrics_df, hide_index=True, use_container_width=True)

    with st.expander("Why this grade? (scoring notes)"):
        for note in grade.notes:
            st.write(f"- {note}")

    if not m.history.empty:
        st.subheader("1-Year Price History")
        st.line_chart(m.history["Close"])

else:
    st.info("Enter a ticker and click **Analyze** to grab live data and grade the stock.")

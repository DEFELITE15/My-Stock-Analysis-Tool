"""
Stock Analysis Machine
-----------------------
Enter any ticker and get a live, data-driven grade (0-10) and a BUY / HOLD /
SELL signal, based on revenue growth, margins, debt, valuation, and dividends
-- all benchmarked against live industry peer data pulled fresh every run.
"""

import time

import altair as alt
import pandas as pd
import streamlit as st

from src.data_fetcher import fetch_stock_data
from src.metrics import build_metrics
from src.scoring import WEIGHTS, grade_stock

st.set_page_config(page_title="Stock Analysis Machine", page_icon="📈", layout="wide")

CACHE_TTL_SECONDS = 15 * 60  # short TTL: fresh data, but avoids hammering Yahoo on every widget click

# Dark, data-terminal palette
BG = "#0a0a0a"
CARD_BG = "rgba(255,255,255,0.035)"
CARD_BORDER = "rgba(255,255,255,0.09)"
TEXT_MUTED = "rgba(200,200,200,0.62)"
GREEN, AMBER, RED = "#22c55e", "#eab308", "#f87171"

SIGNAL_STYLE = {
    "BUY": {"color": GREEN, "bg": "rgba(34,197,94,0.14)", "emoji": "▲"},
    "HOLD": {"color": AMBER, "bg": "rgba(234,179,8,0.14)", "emoji": "●"},
    "SELL": {"color": RED, "bg": "rgba(248,113,113,0.14)", "emoji": "▼"},
}
VERDICT_COLOR = {
    "Excellent": GREEN,
    "Strong": GREEN,
    "Average": AMBER,
    "Weak": RED,
    "Poor": RED,
}
CATEGORY_ICONS = {
    "growth": "📈",
    "profitability": "💰",
    "financial_health": "🛡️",
    "valuation": "⚖️",
    "dividend": "💵",
    "liquidity": "🌊",
}

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap');

    html, body, [class*="css"]  {{ font-family: 'Inter', sans-serif; }}

    .block-container {{ padding-top: 2rem; max-width: 1150px; }}

    .sam-hero {{
        padding: 0.25rem 0 1.25rem 0;
        border-bottom: 1px solid {CARD_BORDER};
        margin-bottom: 1.5rem;
    }}
    .sam-hero h1 {{
        font-size: 2.1rem;
        font-weight: 800;
        margin-bottom: 0.15rem;
        letter-spacing: -0.02em;
    }}
    .sam-hero p {{
        color: {TEXT_MUTED};
        font-size: 0.95rem;
        margin: 0;
    }}

    .sam-card {{
        border-radius: 14px;
        padding: 1.1rem 1.3rem;
        background: {CARD_BG};
        border: 1px solid {CARD_BORDER};
        height: 100%;
    }}

    .sam-signal-badge {{
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 1.6rem;
        font-weight: 800;
        font-family: 'JetBrains Mono', monospace;
        padding: 0.55rem 1.1rem;
        border-radius: 999px;
        letter-spacing: 0.03em;
    }}

    .sam-score-number {{
        font-size: 2.6rem;
        font-weight: 800;
        line-height: 1;
        font-family: 'JetBrains Mono', monospace;
    }}
    .sam-score-max {{ font-size: 1.1rem; color: {TEXT_MUTED}; font-weight: 600; }}

    .sam-progress-track {{
        width: 100%;
        height: 10px;
        border-radius: 999px;
        background: rgba(255,255,255,0.08);
        overflow: hidden;
        margin-top: 0.6rem;
    }}
    .sam-progress-fill {{ height: 100%; border-radius: 999px; }}

    .sam-metric-label {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: {TEXT_MUTED}; margin-bottom: 0.2rem; }}
    .sam-metric-value {{ font-size: 1.2rem; font-weight: 700; font-family: 'JetBrains Mono', monospace; }}
    .sam-metric-sub {{ font-size: 0.78rem; color: {TEXT_MUTED}; margin-top: 0.1rem; }}

    .sam-section-title {{
        font-size: 1.05rem;
        font-weight: 700;
        margin: 1.8rem 0 0.8rem 0;
        display: flex;
        align-items: center;
        gap: 0.4rem;
    }}

    .sam-detail-card {{
        border-radius: 14px;
        padding: 1.2rem 1.4rem;
        background: {CARD_BG};
        border: 1px solid {CARD_BORDER};
        margin-bottom: 0.9rem;
    }}
    .sam-detail-head {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 0.6rem;
    }}
    .sam-detail-title {{ font-size: 1.05rem; font-weight: 700; }}
    .sam-verdict-pill {{
        font-size: 0.72rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        padding: 0.2rem 0.65rem;
        border-radius: 999px;
    }}
    .sam-detail-meta {{ font-size: 0.85rem; color: {TEXT_MUTED}; margin-bottom: 0.5rem; }}
    .sam-detail-compare {{
        display: flex;
        gap: 1.8rem;
        margin: 0.6rem 0 0.7rem 0;
        font-family: 'JetBrains Mono', monospace;
    }}
    .sam-detail-compare div span {{ display: block; }}
    .sam-compare-label {{ font-size: 0.7rem; color: {TEXT_MUTED}; text-transform: uppercase; letter-spacing: 0.04em; font-family: 'Inter', sans-serif; }}
    .sam-compare-value {{ font-size: 0.95rem; font-weight: 700; margin-top: 0.1rem; }}
    .sam-detail-explanation {{ font-size: 0.88rem; line-height: 1.55; color: rgba(230,230,230,0.9); }}
    .sam-points-tag {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.85rem;
        font-weight: 700;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


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


def metric_card(label: str, value: str, sub: str = ""):
    st.markdown(
        f"""
        <div class="sam-card">
            <div class="sam-metric-label">{label}</div>
            <div class="sam-metric-value">{value}</div>
            <div class="sam-metric-sub">{sub}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _themed(chart):
    return chart.configure_axis(
        labelColor=TEXT_MUTED,
        titleColor=TEXT_MUTED,
        gridColor="rgba(255,255,255,0.06)",
        domainColor="rgba(255,255,255,0.12)",
    ).configure_view(strokeWidth=0).properties(background="transparent")


def category_bar_chart(category_scores: dict, category_titles: dict):
    rows = []
    for k, v in category_scores.items():
        max_pts = WEIGHTS[k]
        pct = v / max_pts if max_pts else 0
        color = GREEN if pct >= 0.65 else AMBER if pct >= 0.35 else RED
        rows.append(
            {
                "Category": f"{CATEGORY_ICONS[k]} {category_titles[k]}",
                "Points": round(v, 2),
                "Max": max_pts,
                "Color": color,
                "Label": f"{v:.2f} / {max_pts}",
            }
        )
    df = pd.DataFrame(rows)
    order = df.sort_values("Max", ascending=False)["Category"].tolist()

    base = alt.Chart(df).encode(y=alt.Y("Category:N", sort=order, title=None, axis=alt.Axis(labelFontSize=13)))
    bars = base.mark_bar(cornerRadiusEnd=6, height=22).encode(
        x=alt.X("Points:Q", scale=alt.Scale(domain=[0, 2.6]), title="Points earned"),
        color=alt.Color("Color:N", scale=None),
        tooltip=["Category", "Label"],
    )
    text = base.mark_text(align="left", dx=6, fontSize=12, fontWeight="bold", color="#e5e5e5").encode(
        x="Points:Q", text="Label:N"
    )
    chart = _themed((bars + text).properties(height=220))
    st.altair_chart(chart, use_container_width=True)


def price_chart(history: pd.DataFrame, color: str):
    if history is None or history.empty:
        return
    df = history.reset_index()
    date_col = df.columns[0]
    line = (
        alt.Chart(df)
        .mark_line(color=color, size=2)
        .encode(x=alt.X(f"{date_col}:T", title=None), y=alt.Y("Close:Q", title="Price ($)", scale=alt.Scale(zero=False)))
    )
    area = line.mark_area(interpolate="monotone", line=False, opacity=0.12, color=color).encode(
        tooltip=[date_col, "Close"]
    )
    chart = _themed((area + line).properties(height=260))
    st.altair_chart(chart, use_container_width=True)


def detail_card(detail):
    color = VERDICT_COLOR[detail.verdict]
    st.markdown(
        f"""
        <div class="sam-detail-card">
            <div class="sam-detail-head">
                <div class="sam-detail-title">{CATEGORY_ICONS[detail.key]} {detail.title}</div>
                <div>
                    <span class="sam-verdict-pill" style="color:{color}; background:{color}22;">{detail.verdict}</span>
                    <span class="sam-points-tag" style="color:{color};">&nbsp;{detail.points:.2f}/{detail.max_points} pts</span>
                </div>
            </div>
            <div class="sam-detail-meta"><b>What it measures:</b> {detail.what_it_measures}</div>
            <div class="sam-detail-meta"><b>Why it matters:</b> {detail.why_it_matters}</div>
            <div class="sam-detail-compare">
                <div><span class="sam-compare-label">This stock</span><span class="sam-compare-value">{detail.your_value}</span></div>
                <div><span class="sam-compare-label">Benchmark</span><span class="sam-compare-value" style="color:{TEXT_MUTED};">{detail.benchmark_value}</span></div>
            </div>
            <div class="sam-detail-explanation">{detail.explanation}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown(
    """
    <div class="sam-hero">
        <h1>📈 Stock Analysis Machine</h1>
        <p>Live-graded 0-10 with a BUY / HOLD / SELL signal — benchmarked against
        real industry peers, fetched fresh every time you run it.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

input_col, button_col, refresh_col = st.columns([3, 1, 1.4])
with input_col:
    ticker_input = st.text_input(
        "Ticker symbol", value="AAPL", placeholder="e.g. AAPL, MSFT, TSLA", label_visibility="collapsed"
    ).upper()
with button_col:
    analyze_clicked = st.button("Analyze", type="primary", use_container_width=True)
with refresh_col:
    force_refresh = st.checkbox("Force fresh data", value=False, help="Bypass the 15-min cache and re-fetch everything now.")

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
    style = SIGNAL_STYLE[grade.signal]
    category_titles = {d.key: d.title for d in grade.details}

    name = m.company_name or m.ticker
    st.markdown(
        f"### {name} <span style='color:{TEXT_MUTED}; font-weight:500;'>({m.ticker})</span>",
        unsafe_allow_html=True,
    )
    st.caption(f"{m.sector or 'Unknown sector'} · {m.industry or 'Unknown industry'} · {m.peer_count} live peers used for benchmarking")

    score_col, signal_col = st.columns([2, 1])
    with score_col:
        pct = max(0, min(1, grade.total_score / 10))
        st.markdown(
            f"""
            <div class="sam-card">
                <div class="sam-metric-label">Overall Score</div>
                <span class="sam-score-number" style="color:{style['color']}">{grade.total_score:.1f}</span>
                <span class="sam-score-max">/ 10</span>
                <div class="sam-progress-track">
                    <div class="sam-progress-fill" style="width:{pct*100:.0f}%; background:{style['color']};"></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with signal_col:
        st.markdown(
            f"""
            <div class="sam-card" style="display:flex; align-items:center; justify-content:center;">
                <span class="sam-signal-badge" style="color:{style['color']}; background:{style['bg']};">
                    {style['emoji']} {grade.signal}
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown('<div class="sam-section-title">📊 Score Breakdown</div>', unsafe_allow_html=True)
    category_bar_chart(grade.category_scores, category_titles)

    st.markdown('<div class="sam-section-title">🔑 Key Metrics</div>', unsafe_allow_html=True)

    row1 = st.columns(4)
    with row1[0]:
        metric_card("Price", f"${m.price:,.2f}" if m.price else "N/A")
    with row1[1]:
        rev_label = f"Revenue CAGR ({max(m.years_of_revenue_data - 1, 0)}yr)"
        rev_val = f"{m.revenue_growth_5y:.1%}" if m.revenue_growth_5y is not None else "N/A"
        peer_growth = f"vs. industry {m.peer_avg_revenue_growth:.1%}" if m.peer_avg_revenue_growth is not None else ""
        metric_card(rev_label, rev_val, peer_growth)
    with row1[2]:
        metric_card(
            "P/E Ratio",
            f"{m.pe_ratio:.1f}" if m.pe_ratio is not None else "N/A",
            f"vs. industry {m.peer_avg_pe_ratio:.1f}" if m.peer_avg_pe_ratio is not None else "",
        )
    with row1[3]:
        metric_card(
            "Debt-to-Equity",
            f"{m.debt_to_equity:.2f}" if m.debt_to_equity is not None else "N/A",
            f"vs. industry {m.peer_avg_debt_to_equity:.2f}" if m.peer_avg_debt_to_equity is not None else "",
        )

    st.write("")
    row2 = st.columns(4)
    with row2[0]:
        metric_card("Gross Margin", f"{m.gross_margin:.1%}" if m.gross_margin is not None else "N/A")
    with row2[1]:
        metric_card("Operating Margin", f"{m.operating_margin:.1%}" if m.operating_margin is not None else "N/A")
    with row2[2]:
        metric_card("Net Margin", f"{m.net_margin:.1%}" if m.net_margin is not None else "N/A")
    with row2[3]:
        metric_card("Avg Volume", f"{m.avg_volume:,.0f}" if m.avg_volume else "N/A")

    st.write("")
    row3 = st.columns(4)
    with row3[0]:
        metric_card("Dividend Yield", f"{m.dividend_yield:.2%}" if m.dividend_yield else "No dividend")
    with row3[1]:
        metric_card("Dividend Streak", f"{m.dividend_streak_years} yrs" if m.dividend_yield else "N/A")
    with row3[2]:
        metric_card("Total Debt", f"${m.total_debt:,.0f}" if m.total_debt else "N/A")
    with row3[3]:
        metric_card("Peers Benchmarked", f"{m.peer_count}")

    st.markdown('<div class="sam-section-title">🧠 Why This Grade</div>', unsafe_allow_html=True)
    st.caption("A full, plain-language breakdown of every category — what it measures, why it matters, and exactly how the score was calculated.")
    for detail in grade.details:
        detail_card(detail)

    if m.history is not None and not m.history.empty:
        st.markdown('<div class="sam-section-title">📉 1-Year Price History</div>', unsafe_allow_html=True)
        price_chart(m.history, style["color"])

    st.caption("Research/screening tool only — not financial advice.")

else:
    st.info("Enter a ticker and click **Analyze** to grab live data and grade the stock.")

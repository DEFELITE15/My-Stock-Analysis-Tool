"""
The Stock Analysis Machine's grading engine.

Grades a stock 0-10 across six categories for long-term (buy-and-hold)
investors, most of it scored *relative to live industry peers* rather than
fixed thresholds (a 15% net margin means something very different for a
software company than for a grocery chain). A handful of durability checks
(balance-sheet coverage ratios, earnings quality, dividend safety) are scored
against fixed floors instead, since "how much interest coverage is enough"
doesn't really depend on what industry you're in.

Category weights (sum to 10, "medium" risk tolerance -- the default):
  Growth (revenue CAGR vs. industry + YoY consistency)      2.0
  Profitability (margins, ROE/ROA, cash-earnings quality)   2.5
  Financial health (debt, FCF coverage, current ratio,      2.0
    interest coverage)
  Valuation (P/E, P/FCF, P/B -- growth-adjusted)             1.5
  Capital allocation (dividend safety + buybacks/dilution)   1.5
  Liquidity (avg. volume)                                    0.5

Growth-adjusted valuation (PEG-style logic) avoids unfairly punishing
high-growth names for a higher P/E. Capital allocation replaces a plain
"dividend" category -- long-term compounders that return cash via buybacks
instead of dividends (or on top of them) should get credit for that too,
not just yield.

Risk tolerance mode re-weights those same six categories and shifts the
BUY/HOLD/SELL thresholds, without changing how any individual category is
scored:
  - Low risk tilts weight toward financial health, capital allocation, and
    profitability (stability/downside protection) and raises the bar for a
    BUY signal.
  - High risk tilts weight toward growth and valuation upside and lowers the
    bar for a BUY signal, accepting more volatility for more potential
    reward.
  - Medium is the balanced default above.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .metrics import Metrics

WEIGHTS = {
    "growth": 2.0,
    "profitability": 2.5,
    "financial_health": 2.0,
    "valuation": 1.5,
    "capital_allocation": 1.5,
    "liquidity": 0.5,
}

RISK_PROFILES = {
    "low": {
        "growth": 1.2,
        "profitability": 2.7,
        "financial_health": 3.0,
        "valuation": 0.8,
        "capital_allocation": 1.8,
        "liquidity": 0.5,
    },
    "medium": WEIGHTS,
    "high": {
        "growth": 3.5,
        "profitability": 2.0,
        "financial_health": 1.0,
        "valuation": 2.5,
        "capital_allocation": 0.5,
        "liquidity": 0.5,
    },
}

# (buy_at, hold_at) total-score thresholds. Low risk tolerance demands a
# bigger margin of safety before signaling BUY; high risk tolerance accepts a
# lower bar in exchange for more upside potential.
SIGNAL_THRESHOLDS = {
    "low": (8.5, 6.0),
    "medium": (8.0, 5.0),
    "high": (7.0, 4.0),
}


@dataclass
class CategoryDetail:
    key: str
    title: str
    what_it_measures: str
    why_it_matters: str
    your_value: str
    benchmark_value: str
    verdict: str  # Excellent / Strong / Average / Weak / Poor
    explanation: str  # plain-language sentence on how this score was reached
    points: float
    max_points: float


@dataclass
class StockGrade:
    metrics: Metrics
    category_scores: dict  # category -> points earned
    total_score: float  # 0-10
    signal: str  # BUY / HOLD / SELL
    details: list = field(default_factory=list)  # list[CategoryDetail]
    risk_tolerance: str = "medium"  # low / medium / high
    weights: dict = field(default_factory=lambda: dict(WEIGHTS))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _verdict(pct: float) -> str:
    if pct >= 0.85:
        return "Excellent"
    if pct >= 0.65:
        return "Strong"
    if pct >= 0.45:
        return "Average"
    if pct >= 0.2:
        return "Weak"
    return "Poor"


def _relative_score(
    value: float | None,
    benchmark: float | None,
    max_points: float,
    higher_is_better: bool = True,
) -> float:
    """Score a metric relative to an industry benchmark.

    - Matching the benchmark exactly earns half the available points.
    - Beating it by 2x (or being at half the benchmark, for lower-is-better
      metrics like debt/PE) earns full points.
    - Missing data returns a neutral half-credit score so one missing field
      doesn't tank the whole grade.
    """
    if value is None or benchmark is None or benchmark == 0:
        return round(max_points * 0.5, 3)

    if higher_is_better:
        if value <= 0:
            return 0.0
        ratio = value / benchmark
    else:
        if value <= 0:
            return 0.0
        ratio = benchmark / value

    if ratio <= 0:
        return 0.0
    if ratio <= 1:
        return round(max_points / 2 * ratio, 3)
    if ratio <= 2:
        return round(max_points / 2 + max_points / 2 * (ratio - 1), 3)
    return max_points


def _fmt_pct(v: float | None) -> str:
    return f"{v:.1%}" if v is not None else "N/A"


def _floor_score(
    value: float | None,
    max_points: float,
    good_at: float,
    zero_at: float,
) -> float:
    """Score a metric against fixed floors rather than a peer benchmark --
    for things like coverage ratios where "enough" doesn't really depend on
    industry. `good_at` earns full points; `zero_at` earns zero; linear
    between them (works whether higher-is-better or lower-is-better, based
    on which side `good_at` falls on)."""
    if value is None:
        return round(max_points * 0.5, 3)
    span = good_at - zero_at
    if span == 0:
        return round(max_points * 0.5, 3)
    ratio = _clamp((value - zero_at) / span, 0, 1)
    return round(ratio * max_points, 3)


def _score_growth(m: Metrics, weights: dict) -> tuple[float, CategoryDetail]:
    max_pts = weights["growth"]
    cagr_max = max_pts * 0.75
    steady_max = max_pts * 0.25
    span = f"{max(m.years_of_revenue_data - 1, 0)}-year" if m.years_of_revenue_data else "N/A"

    if m.revenue_growth_5y is None:
        score = round(max_pts * 0.5, 3)
        return score, CategoryDetail(
            key="growth",
            title="Revenue Growth",
            what_it_measures="How fast the company's revenue has grown, annually, over the years of data available (up to 5), and how steady that growth has been year to year.",
            why_it_matters="Consistent revenue growth funds future earnings and often justifies a higher valuation. Stalling or shrinking revenue is an early warning sign, and lumpy/erratic growth is harder to underwrite for a long-term hold than steady growth.",
            your_value="No revenue history available",
            benchmark_value="N/A",
            verdict="Average",
            explanation="Not enough financial history was available to calculate a growth rate, so this category was given neutral (half) credit instead of being penalized.",
            points=score,
            max_points=max_pts,
        )

    benchmark = m.peer_avg_revenue_growth
    cagr_score = _relative_score(m.revenue_growth_5y, benchmark, cagr_max, higher_is_better=True)

    if m.growth_steadiness is not None:
        steady_score = round(m.growth_steadiness * steady_max, 3)
        steady_sentence = (
            f" Year-to-year growth has been "
            f"{'steady' if m.growth_steadiness >= 0.65 else 'somewhat erratic' if m.growth_steadiness >= 0.35 else 'lumpy/erratic'} "
            f"(steadiness score {m.growth_steadiness:.0%}) -- a long-term hold is easier to underwrite when growth doesn't swing wildly year to year."
        )
    else:
        steady_score = round(steady_max * 0.5, 3)
        steady_sentence = " Not enough year-over-year history was available to assess growth consistency, so that portion earned neutral credit."

    score = cagr_score + steady_score
    pct = score / max_pts

    if benchmark is not None:
        comparison = "faster than" if m.revenue_growth_5y > benchmark else "slower than"
        explanation = (
            f"Over the last {span} period of available financials, revenue grew at a "
            f"{m.revenue_growth_5y:.1%} annual rate ({comparison} the {benchmark:.1%} "
            f"average of live industry peers). Growth at 2x the peer average or higher "
            f"earns full points on this sub-metric; growth below the peer average earns "
            f"proportionally less.{steady_sentence}"
        )
        benchmark_str = f"{benchmark:.1%} (industry avg)"
    else:
        explanation = (
            f"Revenue grew at a {m.revenue_growth_5y:.1%} annual rate over the last "
            f"{span}, but no peer data was available for comparison, so this earned "
            f"neutral credit based on the raw growth rate alone.{steady_sentence}"
        )
        benchmark_str = "N/A"

    if m.earnings_growth is not None:
        eg_comparison = (
            "outpacing revenue growth (margins likely expanding)"
            if m.earnings_growth > m.revenue_growth_5y
            else "trailing revenue growth (margins likely compressing)"
        )
        explanation += (
            f" For context (not scored here): the most recent year's earnings grew "
            f"{m.earnings_growth:.1%}, {eg_comparison}."
        )

    return score, CategoryDetail(
        key="growth",
        title="Revenue Growth",
        what_it_measures="How fast the company's revenue has grown, annually, over the years of data available (up to 5), and how steady that growth has been year to year.",
        why_it_matters="Consistent revenue growth funds future earnings and often justifies a higher valuation. Stalling or shrinking revenue is an early warning sign, and lumpy/erratic growth is harder to underwrite for a long-term hold than steady growth.",
        your_value=f"{m.revenue_growth_5y:.1%} / yr ({span} CAGR)" + (f", {m.growth_steadiness:.0%} steady" if m.growth_steadiness is not None else ""),
        benchmark_value=benchmark_str,
        verdict=_verdict(pct),
        explanation=explanation,
        points=score,
        max_points=max_pts,
    )


def _score_profitability(m: Metrics, weights: dict) -> tuple[float, CategoryDetail]:
    total_max = weights["profitability"]
    # Margins: 40% of the category. Capital efficiency (ROE/ROA): 35%.
    # Earnings quality (cash conversion): 25%.
    gross_max, op_max, net_max = total_max * 0.10, total_max * 0.10, total_max * 0.20
    roe_max, roa_max = total_max * 0.20, total_max * 0.15
    quality_max = total_max * 0.25

    gross = _relative_score(m.gross_margin, m.peer_avg_gross_margin, gross_max)
    op = _relative_score(m.operating_margin, m.peer_avg_operating_margin, op_max)
    net = _relative_score(m.net_margin, m.peer_avg_net_margin, net_max)
    roe = _relative_score(m.return_on_equity, m.peer_avg_roe, roe_max)
    roa = _relative_score(m.return_on_assets, m.peer_avg_roa, roa_max)

    if m.cash_conversion_ratio is not None:
        quality = _floor_score(m.cash_conversion_ratio, quality_max, good_at=1.2, zero_at=0.0)
        quality_sentence = (
            f"Free cash flow ran at {m.cash_conversion_ratio:.0%} of reported net income -- "
            f"{'a sign reported earnings are backed by real cash' if m.cash_conversion_ratio >= 0.9 else 'somewhat below reported earnings, worth a closer look at accruals' if m.cash_conversion_ratio >= 0.5 else 'well below reported earnings, a potential red flag on earnings quality'}."
        )
        quality_value = f"{m.cash_conversion_ratio:.0%}"
    elif m.free_cashflow is not None and m.free_cashflow > 0 and (m.net_income is None or m.net_income <= 0):
        quality = round(quality_max * 0.7, 3)
        quality_sentence = "The company posts an accounting loss (or near-breakeven) but still generates positive free cash flow -- a reasonably good sign, common for reinvestment-heavy growth companies."
        quality_value = "Cash-positive despite accounting loss"
    else:
        quality = round(quality_max * 0.5, 3)
        quality_sentence = "Not enough data was available to assess how well reported earnings convert to cash, so this sub-metric earned neutral credit."
        quality_value = "N/A"

    score = gross + op + net + roe + roa + quality
    pct = score / total_max if total_max else 0

    peer_gross = _fmt_pct(m.peer_avg_gross_margin)
    peer_op = _fmt_pct(m.peer_avg_operating_margin)
    peer_net = _fmt_pct(m.peer_avg_net_margin)
    peer_roe = _fmt_pct(m.peer_avg_roe)
    peer_roa = _fmt_pct(m.peer_avg_roa)

    explanation = (
        f"Gross margin (revenue left after cost of goods sold) was {_fmt_pct(m.gross_margin)} "
        f"vs. an industry average of {peer_gross}. Operating margin (after running the "
        f"business) was {_fmt_pct(m.operating_margin)} vs. {peer_op}. Net margin (the "
        f"actual bottom-line profit per dollar of sales) was {_fmt_pct(m.net_margin)} vs. "
        f"{peer_net}. Return on Equity (profit generated per dollar of shareholder capital) "
        f"was {_fmt_pct(m.return_on_equity)} vs. {peer_roe}, and Return on Assets (profit "
        f"generated per dollar of total assets, independent of how much is debt-funded) was "
        f"{_fmt_pct(m.return_on_assets)} vs. {peer_roa}. Net margin and ROE carry the most "
        f"weight among the peer-relative sub-metrics since they best capture bottom-line "
        f"profitability and capital efficiency. Earnings quality: {quality_sentence}"
    )

    return score, CategoryDetail(
        key="profitability",
        title="Profitability",
        what_it_measures="How much profit the company keeps from every dollar of sales (gross/operating/net margin), how efficiently it turns shareholder capital (ROE) and total assets (ROA) into profit, and whether reported earnings are actually backed by cash.",
        why_it_matters="Higher margins and returns mean the business runs more efficiently and has more cushion to absorb rising costs or competition. ROE/ROA catch efficient capital use that margins alone can miss, and cash conversion catches earnings that look good on paper but aren't showing up in the bank -- a classic long-term red flag.",
        your_value=f"Gross {_fmt_pct(m.gross_margin)} · Op {_fmt_pct(m.operating_margin)} · Net {_fmt_pct(m.net_margin)} · ROE {_fmt_pct(m.return_on_equity)} · ROA {_fmt_pct(m.return_on_assets)} · FCF/NI {quality_value}",
        benchmark_value=f"Gross {peer_gross} · Op {peer_op} · Net {peer_net} · ROE {peer_roe} · ROA {peer_roa} (industry avg)",
        verdict=_verdict(pct),
        explanation=explanation,
        points=score,
        max_points=total_max,
    )


def _score_financial_health(m: Metrics, weights: dict) -> tuple[float, CategoryDetail]:
    max_pts = weights["financial_health"]
    debt_max = max_pts * 0.30
    cash_max = max_pts * 0.25
    current_max = max_pts * 0.25
    interest_max = max_pts * 0.20

    # -- Debt-to-Equity sub-score (30%) --
    debt_score = _relative_score(
        m.debt_to_equity, m.peer_avg_debt_to_equity, debt_max, higher_is_better=False
    )
    if m.debt_to_equity is None:
        debt_sentence = "No debt-to-equity data was available for this sub-metric, so it earned neutral credit."
        de_value = "N/A"
        de_bench = "N/A"
    else:
        bench = m.peer_avg_debt_to_equity
        de_bench = f"{bench:.2f}" if bench else "N/A"
        de_value = f"{m.debt_to_equity:.2f}"
        if bench:
            comparison = "less leveraged than" if m.debt_to_equity < bench else "more leveraged than"
            debt_sentence = (
                f"Debt-to-Equity is {m.debt_to_equity:.2f} (${m.debt_to_equity:.2f} of debt per "
                f"$1 of shareholder equity), {comparison} the industry average of {bench:.2f}. "
                f"Carrying half the industry's typical debt load or less earns full points on "
                f"this sub-metric; double or more earns zero."
            )
        else:
            debt_sentence = f"Debt-to-Equity is {m.debt_to_equity:.2f}, but no peer data was available for comparison."

    # -- Free cash flow / debt coverage sub-score (25%) --
    if m.total_debt is None or m.total_debt <= 0:
        if m.free_cashflow is not None and m.free_cashflow > 0:
            cash_score = cash_max
            cash_sentence = (
                "The company carries no meaningful debt and generates positive free cash flow, "
                "so this sub-metric earns full marks."
            )
        else:
            cash_score = round(cash_max * 0.5, 3)
            cash_sentence = "Free cash flow data was unavailable, so this sub-metric earned neutral credit."
        fcf_value = f"{m.free_cashflow:,.0f}" if m.free_cashflow is not None else "N/A"
        fcf_bench = "N/A"
    else:
        cash_score = _relative_score(m.fcf_to_debt, m.peer_avg_fcf_to_debt, cash_max, higher_is_better=True)
        if m.fcf_to_debt is not None and m.peer_avg_fcf_to_debt is not None:
            comparison = "stronger" if m.fcf_to_debt > m.peer_avg_fcf_to_debt else "weaker"
            cash_sentence = (
                f"Free cash flow covers {m.fcf_to_debt:.0%} of total debt annually -- {comparison} "
                f"coverage than the industry average of {m.peer_avg_fcf_to_debt:.0%}. Higher coverage "
                f"means debt could be paid down faster from cash the business actually generates."
            )
        else:
            cash_sentence = "Free cash flow-to-debt coverage data was incomplete, so this sub-metric earned neutral credit."
        fcf_value = f"{m.fcf_to_debt:.0%} of debt/yr" if m.fcf_to_debt is not None else "N/A"
        fcf_bench = f"{m.peer_avg_fcf_to_debt:.0%} (industry avg)" if m.peer_avg_fcf_to_debt is not None else "N/A"

    # -- Current ratio sub-score (25%): fixed floor, not peer-relative --
    current_score = _floor_score(m.current_ratio, current_max, good_at=1.5, zero_at=0.75)
    if m.current_ratio is not None:
        current_sentence = (
            f"The current ratio (short-term assets vs. short-term liabilities) is "
            f"{m.current_ratio:.2f} -- {'a healthy cushion' if m.current_ratio >= 1.5 else 'an adequate but thinner cushion' if m.current_ratio >= 1.0 else 'a thin cushion, worth watching'} "
            f"to cover obligations due within a year. 1.5x or higher earns full points; below 0.75x earns zero."
        )
        current_value = f"{m.current_ratio:.2f}"
    else:
        current_sentence = "Current ratio data was unavailable, so this sub-metric earned neutral credit."
        current_value = "N/A"

    # -- Interest coverage sub-score (20%): fixed floor, not peer-relative --
    if m.interest_coverage is None:
        if m.total_debt is None or m.total_debt <= 0:
            interest_score = interest_max
            interest_sentence = "The company carries no meaningful debt, so there's essentially no interest burden to cover -- full marks."
            interest_value = "No meaningful interest burden"
        else:
            interest_score = round(interest_max * 0.5, 3)
            interest_sentence = "Interest coverage data was unavailable, so this sub-metric earned neutral credit."
            interest_value = "N/A"
    else:
        interest_score = _floor_score(m.interest_coverage, interest_max, good_at=8.0, zero_at=1.5)
        interest_sentence = (
            f"Operating earnings (EBIT) cover interest expense {m.interest_coverage:.1f}x over -- "
            f"{'a comfortable margin' if m.interest_coverage >= 8 else 'an adequate margin' if m.interest_coverage >= 3 else 'a tight margin, worth watching'}. "
            f"8x or higher earns full points; 1.5x or below (barely covering interest) earns zero."
        )
        interest_value = f"{m.interest_coverage:.1f}x"

    score = debt_score + cash_score + current_score + interest_score
    pct = score / max_pts if max_pts else 0
    explanation = f"{debt_sentence} {cash_sentence} {current_sentence} {interest_sentence}"

    return score, CategoryDetail(
        key="financial_health",
        title="Financial Health",
        what_it_measures="Leverage (Debt-to-Equity), debt coverage (FCF vs. total debt), short-term liquidity (current ratio), and how comfortably operating earnings cover interest payments.",
        why_it_matters="Excess debt raises risk — interest payments eat into profits, and heavily indebted companies are more vulnerable during downturns. A thin current ratio or weak interest coverage are early warning signs of balance-sheet stress that debt-to-equity alone can miss.",
        your_value=f"D/E {de_value} · FCF/Debt {fcf_value} · Current {current_value} · Int. Cov {interest_value}",
        benchmark_value=f"D/E {de_bench} · FCF/Debt {fcf_bench} · Current 1.5x floor · Int. Cov 8x floor",
        verdict=_verdict(pct),
        explanation=explanation,
        points=score,
        max_points=max_pts,
    )


def _score_valuation(m: Metrics, weights: dict) -> tuple[float, CategoryDetail]:
    max_pts = weights["valuation"]
    pe_max = max_pts * 0.60
    pfcf_max = max_pts * 0.25
    pb_max = max_pts * 0.15

    # -- P/E sub-score (60%), growth-adjusted PEG-style --
    if m.pe_ratio is None or m.pe_ratio <= 0:
        pe_score = 0.0
        pe_value = "No positive P/E"
        pe_bench_str = "N/A"
        pe_sentence = (
            "No positive P/E ratio is available, typically meaning the company isn't "
            "currently GAAP-profitable, so this sub-metric scores zero."
        )
    else:
        raw_benchmark = m.peer_avg_pe_ratio
        pe_benchmark = raw_benchmark
        growth_note = ""
        if raw_benchmark and m.revenue_growth_5y is not None and m.peer_avg_revenue_growth:
            growth_ratio = (
                (1 + m.revenue_growth_5y) / (1 + m.peer_avg_revenue_growth)
                if m.peer_avg_revenue_growth > -1
                else 1.0
            )
            adjustment = _clamp(growth_ratio, 0.7, 1.5)
            pe_benchmark = raw_benchmark * adjustment
            if adjustment > 1.02:
                growth_note = (
                    f" Because this stock is growing faster than its peers, the fair-value "
                    f"benchmark was raised from {raw_benchmark:.1f} to {pe_benchmark:.1f} "
                    f"(similar to how the PEG ratio rewards growth) so it isn't unfairly "
                    f"penalized for a higher price tag."
                )
            elif adjustment < 0.98:
                growth_note = (
                    f" Because this stock is growing slower than its peers, the fair-value "
                    f"benchmark was lowered from {raw_benchmark:.1f} to {pe_benchmark:.1f}."
                )

        pe_score = _relative_score(m.pe_ratio, pe_benchmark, pe_max, higher_is_better=False)
        pe_value = f"{m.pe_ratio:.1f}"
        pe_bench_str = f"{pe_benchmark:.1f}" if pe_benchmark else "N/A"
        if pe_benchmark:
            comparison = "cheaper than" if m.pe_ratio < pe_benchmark else "more expensive than"
            pe_sentence = (
                f"The stock trades at a P/E of {m.pe_ratio:.1f}, which is {comparison} its "
                f"growth-adjusted fair-value benchmark of {pe_bench_str}.{growth_note}"
            )
        else:
            pe_sentence = f"The stock trades at a P/E of {m.pe_ratio:.1f}, but no peer data was available for comparison."

    # -- P/FCF sub-score (25%): harder to distort with accounting choices than P/E --
    pfcf_score = _relative_score(m.price_to_fcf, m.peer_avg_price_to_fcf, pfcf_max, higher_is_better=False)
    if m.price_to_fcf is not None and m.peer_avg_price_to_fcf is not None:
        comparison = "cheaper than" if m.price_to_fcf < m.peer_avg_price_to_fcf else "more expensive than"
        pfcf_sentence = (
            f"Price-to-Free-Cash-Flow is {m.price_to_fcf:.1f}x, {comparison} the industry "
            f"average of {m.peer_avg_price_to_fcf:.1f}x. Unlike P/E, this can't be flattered "
            f"by non-cash accounting choices."
        )
        pfcf_value = f"{m.price_to_fcf:.1f}x"
        pfcf_bench_str = f"{m.peer_avg_price_to_fcf:.1f}x"
    else:
        pfcf_sentence = "Price-to-Free-Cash-Flow data was unavailable, so this sub-metric earned neutral credit."
        pfcf_value = f"{m.price_to_fcf:.1f}x" if m.price_to_fcf is not None else "N/A"
        pfcf_bench_str = "N/A"

    # -- P/B sub-score (15%) --
    pb_score = _relative_score(m.price_to_book, m.peer_avg_price_to_book, pb_max, higher_is_better=False)
    if m.price_to_book is not None and m.peer_avg_price_to_book is not None:
        comparison = "cheaper than" if m.price_to_book < m.peer_avg_price_to_book else "more expensive than"
        pb_sentence = (
            f"Price-to-Book is {m.price_to_book:.1f}x, {comparison} the industry average of "
            f"{m.peer_avg_price_to_book:.1f}x."
        )
        pb_value = f"{m.price_to_book:.1f}x"
        pb_bench_str = f"{m.peer_avg_price_to_book:.1f}x"
    else:
        pb_sentence = "Price-to-Book data was unavailable, so this sub-metric earned neutral credit."
        pb_value = f"{m.price_to_book:.1f}x" if m.price_to_book is not None else "N/A"
        pb_bench_str = "N/A"

    score = pe_score + pfcf_score + pb_score
    pct = score / max_pts if max_pts else 0
    explanation = f"{pe_sentence} {pfcf_sentence} {pb_sentence}"

    return score, CategoryDetail(
        key="valuation",
        title="Valuation",
        what_it_measures="Whether the stock's price is reasonable, blending three lenses: earnings (P/E, growth-adjusted), free cash flow (P/FCF), and net assets (P/B), each vs. live industry peers.",
        why_it_matters="A cheap stock isn't automatically a good deal, and an expensive one isn't automatically bad — what matters is whether the price is fair given the growth and quality you're paying for. Blending in P/FCF and P/B guards against a single accounting-sensitive multiple (P/E) driving the whole score.",
        your_value=f"P/E {pe_value} · P/FCF {pfcf_value} · P/B {pb_value}",
        benchmark_value=f"P/E {pe_bench_str} (growth-adj.) · P/FCF {pfcf_bench_str} · P/B {pb_bench_str} (industry avg)",
        verdict=_verdict(pct),
        explanation=explanation,
        points=score,
        max_points=max_pts,
    )


def _score_capital_allocation(m: Metrics, weights: dict) -> tuple[float, CategoryDetail]:
    """How well management returns cash to long-term shareholders: dividend
    yield + consistency + sustainability, plus buybacks vs. dilution. A
    company with no dividend can still earn most of this category's points
    through aggressive, well-covered buybacks -- e.g. Alphabet or Meta."""
    max_pts = weights["capital_allocation"]
    yield_max = max_pts * 0.25
    streak_max = max_pts * 0.25
    payout_max = max_pts * 0.20
    buyback_max = max_pts * 0.30

    if not m.dividend_yield:
        yield_score, streak_score, payout_score = 0.0, 0.0, 0.0
        div_sentence = (
            "This company doesn't currently pay a dividend, so it earns none of the "
            "yield/consistency/payout-safety points -- but it can still earn credit below "
            "for returning cash via buybacks instead."
        )
        div_value = "No dividend"
    else:
        yield_score = _relative_score(m.dividend_yield, m.peer_avg_dividend_yield, yield_max)
        streak_score = min(streak_max, (m.dividend_streak_years / 10) * streak_max)
        if m.payout_ratio is not None and m.payout_ratio > 0:
            payout_score = _floor_score(m.payout_ratio, payout_max, good_at=0.4, zero_at=1.1)
            payout_note = (
                f"payout ratio is {m.payout_ratio:.0%} of earnings "
                f"({'comfortably covered' if m.payout_ratio <= 0.6 else 'covered, but leaves less margin of safety' if m.payout_ratio <= 1.0 else 'exceeding earnings -- a sustainability red flag'})"
            )
        else:
            payout_score = round(payout_max * 0.5, 3)
            payout_note = "payout ratio data was unavailable"
        peer_yield = f"{m.peer_avg_dividend_yield:.2%}" if m.peer_avg_dividend_yield else "N/A"
        div_sentence = (
            f"Dividend yield is {m.dividend_yield:.2%} vs. an industry average of {peer_yield}. "
            f"It has paid a flat-or-growing dividend for {m.dividend_streak_years} consecutive "
            f"year(s) -- a 10-year streak earns full consistency credit. And its {payout_note}, "
            f"40% or less earns full sustainability credit; above 110% of earnings earns zero, "
            f"since paying out more than you earn isn't sustainable indefinitely."
        )
        div_value = f"{m.dividend_yield:.2%} yield, {m.dividend_streak_years}yr streak, {f'{m.payout_ratio:.0%} payout' if m.payout_ratio is not None else 'payout N/A'}"

    # -- Buybacks vs. dilution (30%): declining share count = capital returned --
    if m.shares_cagr is None:
        buyback_score = round(buyback_max * 0.5, 3)
        buyback_sentence = "Share count history was unavailable, so the buyback/dilution sub-metric earned neutral credit."
        buyback_value = "N/A"
    else:
        buyback_score = _floor_score(-m.shares_cagr, buyback_max, good_at=0.01, zero_at=-0.03)
        if m.shares_cagr <= -0.005:
            tone = "actively buying back stock"
        elif m.shares_cagr <= 0.005:
            tone = "keeping share count roughly flat"
        else:
            tone = "diluting shareholders (issuing more shares than it retires)"
        buyback_sentence = (
            f"Average share count has changed {m.shares_cagr:+.1%}/yr -- {tone}. Net buybacks "
            f"of 1%/yr or more earn full points here; dilution of 3%/yr or more earns zero."
        )
        buyback_value = f"{m.shares_cagr:+.1%}/yr shares"

    score = yield_score + streak_score + payout_score + buyback_score
    pct = score / max_pts if max_pts else 0
    explanation = f"{div_sentence} {buyback_sentence}"

    return score, CategoryDetail(
        key="capital_allocation",
        title="Capital Allocation",
        what_it_measures="How management returns cash to long-term shareholders: dividend yield, consistency, and payout sustainability, plus whether the share count is shrinking (buybacks) or growing (dilution).",
        why_it_matters="A rising, well-covered dividend and a shrinking share count both signal disciplined, shareholder-friendly management. Dividends aren't required — some of the best long-term compounders return capital purely through buybacks — but unsustainable payouts or persistent dilution quietly erode long-term returns.",
        your_value=f"{div_value} · {buyback_value}",
        benchmark_value=f"Payout ≤40% floor · Buybacks ≥1%/yr floor",
        verdict=_verdict(pct),
        explanation=explanation,
        points=score,
        max_points=max_pts,
    )


def _score_liquidity(m: Metrics, weights: dict) -> tuple[float, CategoryDetail]:
    max_pts = weights["liquidity"]

    if not m.avg_volume:
        score = round(max_pts * 0.5, 3)
        return score, CategoryDetail(
            key="liquidity",
            title="Liquidity",
            what_it_measures="Average daily trading volume — how many shares change hands per day.",
            why_it_matters="Highly-traded (liquid) stocks are easier to buy and sell at a fair price. Thinly-traded stocks can have unpredictable price swings and wide bid-ask spreads.",
            your_value="No volume data available",
            benchmark_value="300,000 shares/day floor",
            verdict="Average",
            explanation="No trading volume data was available, so this category was given neutral (half) credit.",
            points=score,
            max_points=max_pts,
        )

    floor_volume = 300_000  # below this, thin trading can distort price signals
    score = round(_clamp(m.avg_volume / floor_volume, 0, 1) * max_pts, 3)
    pct = score / max_pts if max_pts else 0
    explanation = (
        f"Average daily volume is {m.avg_volume:,.0f} shares. This category treats "
        f"{floor_volume:,.0f} shares/day as the minimum for healthy liquidity — at or "
        f"above that, it earns full points; below it, points scale down proportionally."
    )

    return score, CategoryDetail(
        key="liquidity",
        title="Liquidity",
        what_it_measures="Average daily trading volume — how many shares change hands per day.",
        why_it_matters="Highly-traded (liquid) stocks are easier to buy and sell at a fair price. Thinly-traded stocks can have unpredictable price swings and wide bid-ask spreads.",
        your_value=f"{m.avg_volume:,.0f} shares/day",
        benchmark_value=f"{floor_volume:,.0f} shares/day floor",
        verdict=_verdict(pct),
        explanation=explanation,
        points=score,
        max_points=max_pts,
    )


def _signal_for(total: float, risk_tolerance: str = "medium") -> str:
    buy_at, hold_at = SIGNAL_THRESHOLDS.get(risk_tolerance, SIGNAL_THRESHOLDS["medium"])
    if total >= buy_at:
        return "BUY"
    if total >= hold_at:
        return "HOLD"
    return "SELL"


def grade_stock(m: Metrics, risk_tolerance: str = "medium") -> StockGrade:
    weights = RISK_PROFILES.get(risk_tolerance, WEIGHTS)
    scorers = [
        _score_growth,
        _score_profitability,
        _score_financial_health,
        _score_valuation,
        _score_capital_allocation,
        _score_liquidity,
    ]

    scores = {}
    details = []
    for scorer in scorers:
        score, detail = scorer(m, weights)
        scores[detail.key] = score
        details.append(detail)

    total = round(sum(scores.values()), 2)
    total = _clamp(total, 0, 10)
    return StockGrade(
        metrics=m,
        category_scores=scores,
        total_score=total,
        signal=_signal_for(total, risk_tolerance),
        details=details,
        risk_tolerance=risk_tolerance,
        weights=weights,
    )

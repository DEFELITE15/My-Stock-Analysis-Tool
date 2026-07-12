"""
The Stock Analysis Machine's grading engine.

Grades a stock 0-10 across six categories, each scored *relative to its
industry peers* rather than fixed thresholds (a 15% net margin means
something very different for a software company than for a grocery chain).
Growth-adjusted valuation (PEG-style logic) avoids unfairly punishing
high-growth names for a higher P/E.

Category weights (sum to 10, "medium" risk tolerance -- the default):
  Growth (revenue CAGR vs. industry)               2.5
  Profitability (margins + ROE/ROA)                2.5
  Financial health (debt-to-equity + FCF coverage) 2.0
  Valuation (P/E, growth-adjusted)                 1.5
  Dividend (yield + consistency)                   1.0
  Liquidity (avg. volume)                          0.5

Risk tolerance mode re-weights those same six categories and shifts the
BUY/HOLD/SELL thresholds, without changing how any individual category is
scored:
  - Low risk tilts weight toward financial health, dividends, and
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
    "growth": 2.5,
    "profitability": 2.5,
    "financial_health": 2.0,
    "valuation": 1.5,
    "dividend": 1.0,
    "liquidity": 0.5,
}

RISK_PROFILES = {
    "low": {
        "growth": 1.5,
        "profitability": 2.5,
        "financial_health": 3.0,
        "valuation": 1.0,
        "dividend": 1.5,
        "liquidity": 0.5,
    },
    "medium": WEIGHTS,
    "high": {
        "growth": 3.5,
        "profitability": 2.0,
        "financial_health": 1.0,
        "valuation": 2.5,
        "dividend": 0.5,
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


def _score_growth(m: Metrics, weights: dict) -> tuple[float, CategoryDetail]:
    max_pts = weights["growth"]
    span = f"{max(m.years_of_revenue_data - 1, 0)}-year" if m.years_of_revenue_data else "N/A"

    if m.revenue_growth_5y is None:
        score = round(max_pts * 0.5, 3)
        return score, CategoryDetail(
            key="growth",
            title="Revenue Growth",
            what_it_measures="How fast the company's revenue has grown, annually, over the years of data available (up to 5).",
            why_it_matters="Consistent revenue growth funds future earnings and often justifies a higher valuation. Stalling or shrinking revenue is an early warning sign.",
            your_value="No revenue history available",
            benchmark_value="N/A",
            verdict="Average",
            explanation="Not enough financial history was available to calculate a growth rate, so this category was given neutral (half) credit instead of being penalized.",
            points=score,
            max_points=max_pts,
        )

    benchmark = m.peer_avg_revenue_growth
    score = _relative_score(m.revenue_growth_5y, benchmark, max_pts, higher_is_better=True)
    pct = score / max_pts

    if benchmark is not None:
        comparison = "faster than" if m.revenue_growth_5y > benchmark else "slower than"
        explanation = (
            f"Over the last {span} period of available financials, revenue grew at a "
            f"{m.revenue_growth_5y:.1%} annual rate ({comparison} the {benchmark:.1%} "
            f"average of live industry peers). Growth at 2x the peer average or higher "
            f"earns full points; growth below the peer average earns proportionally less."
        )
        benchmark_str = f"{benchmark:.1%} (industry avg)"
    else:
        explanation = (
            f"Revenue grew at a {m.revenue_growth_5y:.1%} annual rate over the last "
            f"{span}, but no peer data was available for comparison, so this earned "
            f"neutral credit based on the raw growth rate alone."
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
        what_it_measures="How fast the company's revenue has grown, annually, over the years of data available (up to 5).",
        why_it_matters="Consistent revenue growth funds future earnings and often justifies a higher valuation. Stalling or shrinking revenue is an early warning sign.",
        your_value=f"{m.revenue_growth_5y:.1%} / yr ({span} CAGR)",
        benchmark_value=benchmark_str,
        verdict=_verdict(pct),
        explanation=explanation,
        points=score,
        max_points=max_pts,
    )


def _score_profitability(m: Metrics, weights: dict) -> tuple[float, CategoryDetail]:
    total_max = weights["profitability"]
    # Margins: 55% of the category. Capital efficiency (ROE/ROA): 45%.
    gross_max, op_max, net_max = total_max * 0.15, total_max * 0.15, total_max * 0.25
    roe_max, roa_max = total_max * 0.25, total_max * 0.2

    gross = _relative_score(m.gross_margin, m.peer_avg_gross_margin, gross_max)
    op = _relative_score(m.operating_margin, m.peer_avg_operating_margin, op_max)
    net = _relative_score(m.net_margin, m.peer_avg_net_margin, net_max)
    roe = _relative_score(m.return_on_equity, m.peer_avg_roe, roe_max)
    roa = _relative_score(m.return_on_assets, m.peer_avg_roa, roa_max)
    score = gross + op + net + roe + roa
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
        f"weight since they best capture bottom-line profitability and capital efficiency."
    )

    return score, CategoryDetail(
        key="profitability",
        title="Profitability",
        what_it_measures="How much profit the company keeps from every dollar of sales (gross/operating/net margin), and how efficiently it turns shareholder capital (ROE) and total assets (ROA) into profit.",
        why_it_matters="Higher margins and returns mean the business runs more efficiently and has more cushion to absorb rising costs or competition. ROE/ROA catch efficient capital use that margins alone can miss.",
        your_value=f"Gross {_fmt_pct(m.gross_margin)} · Op {_fmt_pct(m.operating_margin)} · Net {_fmt_pct(m.net_margin)} · ROE {_fmt_pct(m.return_on_equity)} · ROA {_fmt_pct(m.return_on_assets)}",
        benchmark_value=f"Gross {peer_gross} · Op {peer_op} · Net {peer_net} · ROE {peer_roe} · ROA {peer_roa} (industry avg)",
        verdict=_verdict(pct),
        explanation=explanation,
        points=score,
        max_points=total_max,
    )


def _score_financial_health(m: Metrics, weights: dict) -> tuple[float, CategoryDetail]:
    max_pts = weights["financial_health"]
    debt_max = max_pts * 0.6
    cash_max = max_pts * 0.4

    # -- Debt-to-Equity sub-score (60%) --
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

    # -- Free cash flow / debt coverage sub-score (40%) --
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

    score = debt_score + cash_score
    pct = score / max_pts if max_pts else 0
    explanation = f"{debt_sentence} {cash_sentence}"

    return score, CategoryDetail(
        key="financial_health",
        title="Financial Health",
        what_it_measures="Leverage (Debt-to-Equity) and debt coverage (how much of total debt could be paid off with one year of free cash flow).",
        why_it_matters="Excess debt raises risk — interest payments eat into profits, and heavily indebted companies are more vulnerable during downturns. Strong free cash flow relative to debt means that risk is more theoretical than real.",
        your_value=f"D/E {de_value} · FCF/Debt {fcf_value}",
        benchmark_value=f"D/E {de_bench} · FCF/Debt {fcf_bench}",
        verdict=_verdict(pct),
        explanation=explanation,
        points=score,
        max_points=max_pts,
    )


def _score_valuation(m: Metrics, weights: dict) -> tuple[float, CategoryDetail]:
    max_pts = weights["valuation"]

    if m.pe_ratio is None or m.pe_ratio <= 0:
        return 0.0, CategoryDetail(
            key="valuation",
            title="Valuation",
            what_it_measures="Whether the stock's price is reasonable relative to its earnings (P/E ratio), adjusted for how fast it's growing compared to peers.",
            why_it_matters="A cheap stock isn't automatically a good deal, and an expensive one isn't automatically bad — what matters is whether the price is fair given the growth and quality you're paying for.",
            your_value="No positive P/E (no earnings, or data unavailable)",
            benchmark_value="N/A",
            verdict="Poor",
            explanation="The company has no positive P/E ratio available, typically meaning it isn't currently profitable. Without positive earnings this category scores zero, since valuation can't be meaningfully assessed on price-to-earnings alone.",
            points=0.0,
            max_points=max_pts,
        )

    raw_benchmark = m.peer_avg_pe_ratio
    benchmark = raw_benchmark
    growth_note = ""
    if raw_benchmark and m.revenue_growth_5y is not None and m.peer_avg_revenue_growth:
        growth_ratio = (
            (1 + m.revenue_growth_5y) / (1 + m.peer_avg_revenue_growth)
            if m.peer_avg_revenue_growth > -1
            else 1.0
        )
        adjustment = _clamp(growth_ratio, 0.7, 1.5)
        benchmark = raw_benchmark * adjustment
        if adjustment > 1.02:
            growth_note = (
                f" Because this stock is growing faster than its peers, the fair-value "
                f"benchmark was raised from {raw_benchmark:.1f} to {benchmark:.1f} "
                f"(similar to how the PEG ratio rewards growth) so it isn't unfairly "
                f"penalized for a higher price tag."
            )
        elif adjustment < 0.98:
            growth_note = (
                f" Because this stock is growing slower than its peers, the fair-value "
                f"benchmark was lowered from {raw_benchmark:.1f} to {benchmark:.1f}."
            )

    score = _relative_score(m.pe_ratio, benchmark, max_pts, higher_is_better=False)
    pct = score / max_pts if max_pts else 0
    bench_str = f"{benchmark:.1f}" if benchmark else "N/A"

    if benchmark:
        comparison = "cheaper than" if m.pe_ratio < benchmark else "more expensive than"
        explanation = (
            f"The stock trades at a P/E of {m.pe_ratio:.1f}, which is {comparison} its "
            f"growth-adjusted fair-value benchmark of {bench_str}.{growth_note}"
        )
    else:
        explanation = f"The stock trades at a P/E of {m.pe_ratio:.1f}, but no peer data was available for comparison."

    return score, CategoryDetail(
        key="valuation",
        title="Valuation",
        what_it_measures="Whether the stock's price is reasonable relative to its earnings (P/E ratio), adjusted for how fast it's growing compared to peers.",
        why_it_matters="A cheap stock isn't automatically a good deal, and an expensive one isn't automatically bad — what matters is whether the price is fair given the growth and quality you're paying for.",
        your_value=f"P/E {m.pe_ratio:.1f}",
        benchmark_value=f"{bench_str} (growth-adjusted industry avg)",
        verdict=_verdict(pct),
        explanation=explanation,
        points=score,
        max_points=max_pts,
    )


def _score_dividend(m: Metrics, weights: dict) -> tuple[float, CategoryDetail]:
    max_pts = weights["dividend"]

    if not m.dividend_yield:
        return 0.0, CategoryDetail(
            key="dividend",
            title="Dividend",
            what_it_measures="The dividend yield (cash paid back to shareholders as a % of share price) and how many consecutive years the dividend has held steady or grown.",
            why_it_matters="A rising, reliable dividend often signals financial discipline and shareholder-friendly management. It's a bonus, not a requirement — plenty of great growth companies pay no dividend at all.",
            your_value="No dividend paid",
            benchmark_value="N/A",
            verdict="Poor",
            explanation="This company doesn't currently pay a dividend, so it earns 0 of the available dividend points. This is not held against it anywhere else in the grade — it's simply a missed bonus, common for growth-focused companies reinvesting profits instead.",
            points=0.0,
            max_points=max_pts,
        )

    yield_score = _relative_score(m.dividend_yield, m.peer_avg_dividend_yield, max_pts * 0.5)
    streak_score = min(max_pts * 0.5, (m.dividend_streak_years / 10) * (max_pts * 0.5))
    score = yield_score + streak_score
    pct = score / max_pts if max_pts else 0

    peer_yield = f"{m.peer_avg_dividend_yield:.2%}" if m.peer_avg_dividend_yield else "N/A"
    explanation = (
        f"Dividend yield is {m.dividend_yield:.2%} vs. an industry average of {peer_yield} "
        f"(half the category's points). It has paid a flat-or-growing dividend for "
        f"{m.dividend_streak_years} consecutive year(s) — a 10-year streak earns full "
        f"credit on the consistency half of this category."
    )

    return score, CategoryDetail(
        key="dividend",
        title="Dividend",
        what_it_measures="The dividend yield (cash paid back to shareholders as a % of share price) and how many consecutive years the dividend has held steady or grown.",
        why_it_matters="A rising, reliable dividend often signals financial discipline and shareholder-friendly management. It's a bonus, not a requirement — plenty of great growth companies pay no dividend at all.",
        your_value=f"{m.dividend_yield:.2%} yield, {m.dividend_streak_years}yr streak",
        benchmark_value=f"{peer_yield} (industry avg)",
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
        _score_dividend,
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

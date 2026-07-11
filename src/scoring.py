"""
The Stock Analysis Machine's grading engine.

Grades a stock 0-10 across five categories, each scored *relative to its
industry peers* rather than fixed thresholds (a 15% net margin means
something very different for a software company than for a grocery chain).
Growth-adjusted valuation (PEG-style logic) avoids unfairly punishing
high-growth names for a higher P/E.

Category weights (sum to 10):
  Growth (revenue CAGR vs. industry)     2.5
  Profitability (gross/op/net margin)    2.5
  Financial health (debt-to-equity)      2.0
  Valuation (P/E, growth-adjusted)       1.5
  Dividend (yield + consistency)         1.0
  Liquidity (avg. volume)                0.5
"""

from __future__ import annotations

from dataclasses import dataclass

from .metrics import Metrics

WEIGHTS = {
    "growth": 2.5,
    "profitability": 2.5,
    "financial_health": 2.0,
    "valuation": 1.5,
    "dividend": 1.0,
    "liquidity": 0.5,
}


@dataclass
class StockGrade:
    metrics: Metrics
    category_scores: dict  # category -> points earned
    total_score: float  # 0-10
    signal: str  # BUY / HOLD / SELL
    notes: list  # human-readable explanations


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


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


def _score_growth(m: Metrics, notes: list) -> float:
    max_pts = WEIGHTS["growth"]
    if m.revenue_growth_5y is None:
        notes.append("Growth: no revenue history available, neutral credit given.")
        return round(max_pts * 0.5, 3)

    benchmark = m.peer_avg_revenue_growth
    score = _relative_score(m.revenue_growth_5y, benchmark, max_pts, higher_is_better=True)
    span = f"{m.years_of_revenue_data - 1}-yr" if m.years_of_revenue_data else "N/A"
    if benchmark is not None:
        notes.append(
            f"Growth: {span} revenue CAGR {m.revenue_growth_5y:.1%} vs. "
            f"industry avg {benchmark:.1%} -> {score:.2f}/{max_pts} pts."
        )
    else:
        notes.append(
            f"Growth: {span} revenue CAGR {m.revenue_growth_5y:.1%}, no peer "
            f"data available -> neutral {score:.2f}/{max_pts} pts."
        )
    return score


def _score_profitability(m: Metrics, notes: list) -> float:
    total_max = WEIGHTS["profitability"]
    gross_max, op_max, net_max = total_max * 0.3, total_max * 0.3, total_max * 0.4

    gross = _relative_score(m.gross_margin, m.peer_avg_gross_margin, gross_max)
    op = _relative_score(m.operating_margin, m.peer_avg_operating_margin, op_max)
    net = _relative_score(m.net_margin, m.peer_avg_net_margin, net_max)

    score = gross + op + net
    notes.append(
        f"Profitability: gross {_fmt_pct(m.gross_margin)}, operating "
        f"{_fmt_pct(m.operating_margin)}, net {_fmt_pct(m.net_margin)} "
        f"vs. industry -> {score:.2f}/{total_max} pts."
    )
    return score


def _score_financial_health(m: Metrics, notes: list) -> float:
    max_pts = WEIGHTS["financial_health"]
    score = _relative_score(
        m.debt_to_equity, m.peer_avg_debt_to_equity, max_pts, higher_is_better=False
    )
    if m.debt_to_equity is None:
        notes.append("Financial health: no debt data available, neutral credit given.")
    else:
        bench = f"{m.peer_avg_debt_to_equity:.2f}" if m.peer_avg_debt_to_equity else "N/A"
        notes.append(
            f"Financial health: D/E {m.debt_to_equity:.2f} vs. industry avg "
            f"{bench} -> {score:.2f}/{max_pts} pts."
        )
    return score


def _score_valuation(m: Metrics, notes: list) -> float:
    max_pts = WEIGHTS["valuation"]
    if m.pe_ratio is None or m.pe_ratio <= 0:
        notes.append("Valuation: no positive P/E available (no earnings?), scored 0.")
        return 0.0

    benchmark = m.peer_avg_pe_ratio
    if benchmark and m.revenue_growth_5y is not None and m.peer_avg_revenue_growth:
        # PEG-style adjustment: a faster grower than its peers earns the
        # right to trade at a higher P/E without being penalized for it.
        growth_ratio = (
            (1 + m.revenue_growth_5y) / (1 + m.peer_avg_revenue_growth)
            if m.peer_avg_revenue_growth > -1
            else 1.0
        )
        adjustment = _clamp(growth_ratio, 0.7, 1.5)
        benchmark = benchmark * adjustment

    score = _relative_score(m.pe_ratio, benchmark, max_pts, higher_is_better=False)
    bench_str = f"{benchmark:.1f}" if benchmark else "N/A"
    notes.append(
        f"Valuation: P/E {m.pe_ratio:.1f} vs. growth-adjusted industry "
        f"benchmark {bench_str} -> {score:.2f}/{max_pts} pts."
    )
    return score


def _score_dividend(m: Metrics, notes: list) -> float:
    max_pts = WEIGHTS["dividend"]
    if not m.dividend_yield:
        notes.append("Dividend: no dividend paid, 0 pts (not penalized elsewhere).")
        return 0.0

    yield_score = _relative_score(
        m.dividend_yield, m.peer_avg_dividend_yield, max_pts * 0.5
    )
    streak_score = min(max_pts * 0.5, (m.dividend_streak_years / 10) * (max_pts * 0.5))
    score = yield_score + streak_score
    notes.append(
        f"Dividend: yield {m.dividend_yield:.2%}, {m.dividend_streak_years}yr "
        f"non-decreasing streak -> {score:.2f}/{max_pts} pts."
    )
    return score


def _score_liquidity(m: Metrics, notes: list) -> float:
    max_pts = WEIGHTS["liquidity"]
    if not m.avg_volume:
        notes.append("Liquidity: no volume data available, neutral credit given.")
        return round(max_pts * 0.5, 3)

    floor_volume = 300_000  # below this, thin trading can distort price signals
    score = round(_clamp(m.avg_volume / floor_volume, 0, 1) * max_pts, 3)
    notes.append(f"Liquidity: avg volume {m.avg_volume:,.0f} -> {score:.2f}/{max_pts} pts.")
    return score


def _fmt_pct(v: float | None) -> str:
    return f"{v:.1%}" if v is not None else "N/A"


def _signal_for(total: float) -> str:
    if total >= 8.0:
        return "BUY"
    if total >= 5.0:
        return "HOLD"
    return "SELL"


def grade_stock(m: Metrics) -> StockGrade:
    notes: list = []
    scores = {
        "growth": _score_growth(m, notes),
        "profitability": _score_profitability(m, notes),
        "financial_health": _score_financial_health(m, notes),
        "valuation": _score_valuation(m, notes),
        "dividend": _score_dividend(m, notes),
        "liquidity": _score_liquidity(m, notes),
    }
    total = round(sum(scores.values()), 2)
    total = _clamp(total, 0, 10)
    return StockGrade(
        metrics=m,
        category_scores=scores,
        total_score=total,
        signal=_signal_for(total),
        notes=notes,
    )

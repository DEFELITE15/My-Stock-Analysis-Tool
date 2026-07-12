"""
Grading engine for ETFs and mutual funds.

Funds are scored differently from individual stocks -- there's no revenue,
margin, or debt to analyze. Instead this benchmarks cost, performance, and
yield against a live S&P 500 ETF (SPY) proxy, fetched fresh every run.

Category weights (sum to 10, "medium" risk tolerance -- the default):
  Cost (expense ratio, lower is better)      3.0
  Performance (YTD / 3yr / 5yr vs. SPY)      4.5
  Dividend yield (vs. SPY)                   1.0
  Liquidity (avg. daily volume)              1.5

Risk tolerance mode re-weights those same four categories and shifts the
BUY/HOLD/SELL thresholds (see src/scoring.py for the shared philosophy):
  - Low risk tilts weight toward cost and liquidity (the two most
    predictable, lowest-volatility factors) and raises the bar for BUY.
  - High risk tilts weight toward performance and lowers the bar for BUY,
    prioritizing return over fees.
"""

from __future__ import annotations

from .fund_metrics import FundMetrics
from .scoring import CategoryDetail, StockGrade, _clamp, _relative_score, _signal_for, _verdict

WEIGHTS_FUND = {
    "cost": 3.0,
    "performance": 4.5,
    "dividend": 1.0,
    "liquidity": 1.5,
}

RISK_PROFILES_FUND = {
    "low": {
        "cost": 4.0,
        "performance": 3.0,
        "dividend": 1.0,
        "liquidity": 2.0,
    },
    "medium": WEIGHTS_FUND,
    "high": {
        "cost": 2.0,
        "performance": 6.0,
        "dividend": 0.5,
        "liquidity": 1.5,
    },
}


def _fmt_pct(v: float | None) -> str:
    return f"{v:.1%}" if v is not None else "N/A"


def _score_cost(fm: FundMetrics, weights: dict) -> tuple[float, CategoryDetail]:
    max_pts = weights["cost"]

    if fm.expense_ratio is None:
        score = round(max_pts * 0.5, 3)
        return score, CategoryDetail(
            key="cost",
            title="Cost (Expense Ratio)",
            what_it_measures="The fund's annual expense ratio -- the percentage of your investment taken as fees every year.",
            why_it_matters="Fees compound over decades. A 1% expense ratio can quietly cost tens of thousands of dollars over a long holding period versus a low-cost index fund.",
            your_value="N/A",
            benchmark_value="N/A",
            verdict="Average",
            explanation="No expense ratio data was available, so this category was given neutral (half) credit.",
            points=score,
            max_points=max_pts,
        )

    bench = fm.benchmark_expense_ratio
    score = _relative_score(fm.expense_ratio, bench, max_pts, higher_is_better=False)
    pct = score / max_pts if max_pts else 0
    bench_str = f"{bench:.2f}%" if bench is not None else "N/A"

    if bench:
        comparison = "cheaper than" if fm.expense_ratio < bench else "more expensive than"
        explanation = (
            f"This fund charges {fm.expense_ratio:.2f}% per year, {comparison} the "
            f"{fm.benchmark_ticker} benchmark's {bench:.2f}%. Costing half the benchmark or "
            f"less earns full points; costing double or more earns zero -- fees are one of the "
            f"few things about a fund's future return you actually know in advance."
        )
    else:
        explanation = f"This fund charges {fm.expense_ratio:.2f}% per year, but no benchmark data was available for comparison."

    return score, CategoryDetail(
        key="cost",
        title="Cost (Expense Ratio)",
        what_it_measures="The fund's annual expense ratio -- the percentage of your investment taken as fees every year.",
        why_it_matters="Fees compound over decades. A 1% expense ratio can quietly cost tens of thousands of dollars over a long holding period versus a low-cost index fund.",
        your_value=f"{fm.expense_ratio:.2f}%/yr",
        benchmark_value=f"{bench_str} ({fm.benchmark_ticker})",
        verdict=_verdict(pct),
        explanation=explanation,
        points=score,
        max_points=max_pts,
    )


def _score_performance(fm: FundMetrics, weights: dict) -> tuple[float, CategoryDetail]:
    max_pts = weights["performance"]
    # Split proportionally across YTD / 3yr / 5yr, 3yr weighted heaviest
    # (smooths out short-term noise) regardless of the overall category weight.
    ytd_max, three_max, five_max = max_pts * (1 / 4.5), max_pts * (2 / 4.5), max_pts * (1.5 / 4.5)

    ytd_score = _relative_score(fm.ytd_return, fm.benchmark_ytd_return, ytd_max, higher_is_better=True)
    three_score = _relative_score(fm.three_year_return, fm.benchmark_three_year_return, three_max, higher_is_better=True)
    five_score = _relative_score(fm.five_year_return, fm.benchmark_five_year_return, five_max, higher_is_better=True)
    score = ytd_score + three_score + five_score
    pct = score / max_pts if max_pts else 0

    explanation = (
        f"YTD return is {_fmt_pct(fm.ytd_return)} vs. {fm.benchmark_ticker}'s "
        f"{_fmt_pct(fm.benchmark_ytd_return)}. 3-year annualized return is "
        f"{_fmt_pct(fm.three_year_return)} vs. {_fmt_pct(fm.benchmark_three_year_return)} "
        f"(weighted most heavily, since it smooths out short-term noise). 5-year annualized "
        f"return is {_fmt_pct(fm.five_year_return)} vs. {_fmt_pct(fm.benchmark_five_year_return)}. "
        f"Matching the benchmark earns half credit per period; beating it by 2x or more earns "
        f"full credit."
    )

    return score, CategoryDetail(
        key="performance",
        title="Performance",
        what_it_measures="Total return over three time horizons (YTD, 3-year, and 5-year annualized), compared to a live S&P 500 ETF benchmark.",
        why_it_matters="Past performance doesn't guarantee future results, but consistent multi-year out- or under-performance versus a simple index fund is the clearest signal of whether a fund's strategy and fees are working for you.",
        your_value=f"YTD {_fmt_pct(fm.ytd_return)} · 3yr {_fmt_pct(fm.three_year_return)} · 5yr {_fmt_pct(fm.five_year_return)}",
        benchmark_value=f"YTD {_fmt_pct(fm.benchmark_ytd_return)} · 3yr {_fmt_pct(fm.benchmark_three_year_return)} · 5yr {_fmt_pct(fm.benchmark_five_year_return)} ({fm.benchmark_ticker})",
        verdict=_verdict(pct),
        explanation=explanation,
        points=score,
        max_points=max_pts,
    )


def _score_dividend(fm: FundMetrics, weights: dict) -> tuple[float, CategoryDetail]:
    max_pts = weights["dividend"]

    if not fm.dividend_yield:
        return 0.0, CategoryDetail(
            key="dividend",
            title="Dividend Yield",
            what_it_measures="Cash distributions paid out to shareholders, as a percentage of the fund's price.",
            why_it_matters="Higher-yielding funds return more cash to you along the way, though that's a trade-off against growth, not automatically 'better'.",
            your_value="No dividend paid",
            benchmark_value="N/A",
            verdict="Poor",
            explanation="This fund doesn't currently pay a distribution, so it earns 0 of the available points here.",
            points=0.0,
            max_points=max_pts,
        )

    score = _relative_score(fm.dividend_yield, fm.benchmark_dividend_yield, max_pts, higher_is_better=True)
    pct = score / max_pts if max_pts else 0
    bench = f"{fm.benchmark_dividend_yield:.2%}" if fm.benchmark_dividend_yield is not None else "N/A"
    explanation = (
        f"This fund yields {fm.dividend_yield:.2%} vs. {fm.benchmark_ticker}'s {bench}. "
        f"Yielding 2x the benchmark or more earns full points."
    )

    return score, CategoryDetail(
        key="dividend",
        title="Dividend Yield",
        what_it_measures="Cash distributions paid out to shareholders, as a percentage of the fund's price.",
        why_it_matters="Higher-yielding funds return more cash to you along the way, though that's a trade-off against growth, not automatically 'better'.",
        your_value=f"{fm.dividend_yield:.2%}",
        benchmark_value=f"{bench} ({fm.benchmark_ticker})",
        verdict=_verdict(pct),
        explanation=explanation,
        points=score,
        max_points=max_pts,
    )


def _score_liquidity(fm: FundMetrics, weights: dict) -> tuple[float, CategoryDetail]:
    max_pts = weights["liquidity"]

    if not fm.avg_volume:
        score = round(max_pts * 0.5, 3)
        return score, CategoryDetail(
            key="liquidity",
            title="Liquidity",
            what_it_measures="Average daily trading volume -- how many shares change hands per day.",
            why_it_matters="Highly-traded funds are easier to buy and sell at a fair price, with tighter bid-ask spreads.",
            your_value="No volume data available",
            benchmark_value="300,000 shares/day floor",
            verdict="Average",
            explanation="No trading volume data was available, so this category was given neutral (half) credit.",
            points=score,
            max_points=max_pts,
        )

    floor_volume = 300_000
    score = round(_clamp(fm.avg_volume / floor_volume, 0, 1) * max_pts, 3)
    pct = score / max_pts if max_pts else 0
    explanation = (
        f"Average daily volume is {fm.avg_volume:,.0f} shares. This category treats "
        f"{floor_volume:,.0f} shares/day as the minimum for healthy liquidity -- at or above "
        f"that, it earns full points; below it, points scale down proportionally."
    )

    return score, CategoryDetail(
        key="liquidity",
        title="Liquidity",
        what_it_measures="Average daily trading volume -- how many shares change hands per day.",
        why_it_matters="Highly-traded funds are easier to buy and sell at a fair price, with tighter bid-ask spreads.",
        your_value=f"{fm.avg_volume:,.0f} shares/day",
        benchmark_value=f"{floor_volume:,.0f} shares/day floor",
        verdict=_verdict(pct),
        explanation=explanation,
        points=score,
        max_points=max_pts,
    )


def grade_fund(fm: FundMetrics, risk_tolerance: str = "medium") -> StockGrade:
    weights = RISK_PROFILES_FUND.get(risk_tolerance, WEIGHTS_FUND)
    scorers = [_score_cost, _score_performance, _score_dividend, _score_liquidity]

    scores = {}
    details = []
    for scorer in scorers:
        score, detail = scorer(fm, weights)
        scores[detail.key] = score
        details.append(detail)

    total = round(sum(scores.values()), 2)
    total = _clamp(total, 0, 10)
    return StockGrade(
        metrics=fm,
        category_scores=scores,
        total_score=total,
        signal=_signal_for(total, risk_tolerance),
        details=details,
        risk_tolerance=risk_tolerance,
        weights=weights,
    )

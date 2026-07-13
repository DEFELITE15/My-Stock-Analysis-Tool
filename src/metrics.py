"""
Extracts clean, comparable financial metrics from raw yfinance data.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .data_fetcher import StockData


@dataclass
class Metrics:
    ticker: str
    company_name: str | None
    sector: str | None
    industry: str | None
    price: float | None
    history: pd.DataFrame

    revenue_growth_5y: float | None  # CAGR, as decimal (0.12 = 12%)
    years_of_revenue_data: int

    gross_margin: float | None
    operating_margin: float | None
    net_margin: float | None

    return_on_equity: float | None  # as a decimal (1.4 = 140%)
    return_on_assets: float | None  # as a decimal

    debt_to_equity: float | None  # as a ratio (1.5 = 150%)
    total_debt: float | None
    free_cashflow: float | None
    fcf_to_debt: float | None  # free cash flow / total debt -- debt coverage

    pe_ratio: float | None

    avg_volume: float | None

    dividend_yield: float | None
    dividend_streak_years: int  # consecutive years of flat-or-rising dividends

    earnings_growth: float | None  # decimal, YoY EPS/earnings growth
    beta: float | None  # volatility vs. the overall market (1.0 = moves with the market)

    target_mean_price: float | None
    target_high_price: float | None
    target_low_price: float | None

    held_percent_insiders: float | None  # decimal
    held_percent_institutions: float | None  # decimal
    short_percent_of_float: float | None  # decimal

    peer_avg_revenue_growth: float | None
    peer_avg_gross_margin: float | None
    peer_avg_operating_margin: float | None
    peer_avg_net_margin: float | None
    peer_avg_roe: float | None
    peer_avg_roa: float | None
    peer_avg_debt_to_equity: float | None
    peer_avg_fcf_to_debt: float | None
    peer_avg_pe_ratio: float | None
    peer_avg_dividend_yield: float | None
    peer_avg_price_to_book: float | None
    peer_avg_price_to_fcf: float | None
    peer_count: int

    # -- Earnings quality --
    net_income: float | None
    cash_conversion_ratio: float | None  # free cash flow / net income

    # -- Balance sheet depth --
    current_ratio: float | None
    interest_coverage: float | None  # EBIT / interest expense

    # -- Multi-multiple valuation --
    price_to_book: float | None
    price_to_fcf: float | None

    # -- Capital allocation (buybacks vs. dilution) --
    payout_ratio: float | None
    shares_cagr: float | None  # CAGR of average share count; negative = net buybacks

    # -- Growth consistency --
    growth_steadiness: float | None  # 0-1, higher = steadier year-over-year growth


def _find_row(stmt: pd.DataFrame, *labels: str) -> pd.Series | None:
    if stmt is None or stmt.empty:
        return None
    for label in labels:
        if label in stmt.index:
            return stmt.loc[label]
    return None


def _annual_series(stmt: pd.DataFrame, *labels: str) -> pd.Series:
    """Latest-first yfinance column ordering, flipped to oldest-first."""
    row = _find_row(stmt, *labels)
    if row is None:
        return pd.Series(dtype=float)
    series = row.dropna()
    return series[list(series.index)[::-1]] if not series.empty else series


def _cagr_from_series(series: pd.Series) -> tuple[float | None, int]:
    if series is None or len(series) < 2:
        return None, 0 if series is None else len(series)
    start, end = float(series.iloc[0]), float(series.iloc[-1])
    years = len(series) - 1
    if start <= 0 or end <= 0 or years <= 0:
        return None, len(series)
    return (end / start) ** (1 / years) - 1, len(series)


def _revenue_cagr(income_stmt: pd.DataFrame) -> tuple[float | None, int]:
    """CAGR of Total Revenue across whatever annual history Yahoo provides
    (usually up to 4 years, occasionally 5)."""
    series = _annual_series(income_stmt, "Total Revenue", "TotalRevenue")
    return _cagr_from_series(series)


def _shares_cagr(income_stmt: pd.DataFrame) -> float | None:
    """CAGR of average share count -- negative means the company has been net
    buying back stock, positive means it's been diluting shareholders."""
    series = _annual_series(income_stmt, "Basic Average Shares", "Diluted Average Shares")
    cagr, years = _cagr_from_series(series)
    return cagr if years >= 2 else None


def _growth_steadiness(income_stmt: pd.DataFrame) -> float | None:
    """0-1 score for how consistent year-over-year revenue growth has been
    (vs. lumpy/erratic), based on the coefficient of variation of the
    year-over-year growth rates. None if there isn't enough history."""
    series = _annual_series(income_stmt, "Total Revenue", "TotalRevenue")
    if len(series) < 3:
        return None
    values = [float(v) for v in series.values]
    yoy = [
        (values[i] / values[i - 1]) - 1
        for i in range(1, len(values))
        if values[i - 1] > 0
    ]
    if len(yoy) < 2:
        return None
    mean = sum(yoy) / len(yoy)
    variance = sum((r - mean) ** 2 for r in yoy) / len(yoy)
    stdev = variance ** 0.5
    return max(0.0, min(1.0, 1 - stdev / (abs(mean) + 0.05)))


def _interest_coverage(income_stmt: pd.DataFrame) -> tuple[float | None, float | None, float | None]:
    """Returns (coverage_ratio, ebit, interest_expense) using the most recent
    annual column where both are actually reported -- Yahoo sometimes leaves
    Interest Expense blank for the latest period even when EBIT is present.
    None coverage if there's no meaningful interest expense (handled as a
    no-debt-burden special case in scoring)."""
    ebit_row = _find_row(income_stmt, "EBIT", "Operating Income")
    interest_row = _find_row(income_stmt, "Interest Expense", "Interest Expense Non Operating")
    if ebit_row is None or ebit_row.empty or interest_row is None or interest_row.empty:
        return None, None, None
    for col in ebit_row.index:
        ebit = _as_float(ebit_row.get(col))
        interest = _as_float(interest_row.get(col)) if col in interest_row.index else None
        if interest is not None:
            interest = abs(interest)
        if ebit is not None and interest is not None and interest != 0:
            return ebit / interest, ebit, interest
    return None, _as_float(ebit_row.iloc[0]) if not ebit_row.empty else None, None


def _dividend_streak(dividends: pd.Series) -> int:
    """Count consecutive years (ending most recently) where total annual
    dividends paid did not decrease year-over-year."""
    if dividends is None or dividends.empty:
        return 0
    annual = dividends.groupby(dividends.index.year).sum().sort_index()
    if len(annual) < 2:
        return 1 if len(annual) == 1 else 0

    streak = 1
    values = list(annual.values)
    for i in range(len(values) - 1, 0, -1):
        if values[i] >= values[i - 1] * 0.999:  # tiny tolerance for rounding
            streak += 1
        else:
            break
    return streak


def _as_float(value) -> float | None:
    """yfinance occasionally returns dirty data (e.g. the literal string
    'NaN' instead of a real float) for fields like trailingAnnualDividendYield.
    Coerce to a clean float or None."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN check
        return None
    return f


def _avg(values: list[float | None]) -> float | None:
    clean = [_as_float(v) for v in values]
    clean = [v for v in clean if v is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _fcf_to_debt(fcf: float | None, debt: float | None) -> float | None:
    """Free cash flow as a fraction of total debt -- how much of its debt a
    company could retire with a single year of free cash flow. None for
    debt-free companies (handled as a special case in scoring, not here)."""
    fcf, debt = _as_float(fcf), _as_float(debt)
    if fcf is None or debt is None or debt <= 0:
        return None
    return fcf / debt


def build_metrics(data: StockData) -> Metrics:
    info = data.info
    growth, years = _revenue_cagr(data.income_stmt)

    debt_to_equity = _as_float(info.get("debtToEquity"))
    if debt_to_equity is not None:
        debt_to_equity = debt_to_equity / 100  # yfinance reports as percent

    avg_volume = info.get("averageVolume") or info.get("averageDailyVolume10Day")

    # yfinance's `dividendYield` is always in percentage-point form (5.28 == 5.28%),
    # never a decimal fraction -- always divide by 100. Fall back to the
    # trailing-twelve-month yield (already a decimal) if it's missing.
    # Note: yfinance occasionally returns dirty data (e.g. the literal string
    # 'NaN') for these fields, so everything is passed through _as_float.
    div_yield = _as_float(info.get("dividendYield"))
    if div_yield is not None:
        div_yield = div_yield / 100
    else:
        div_yield = _as_float(info.get("trailingAnnualDividendYield"))

    free_cashflow = _as_float(info.get("freeCashflow"))
    fcf_to_debt = _fcf_to_debt(free_cashflow, info.get("totalDebt"))

    net_income = _as_float(info.get("netIncomeToCommon"))
    cash_conversion_ratio = None
    if free_cashflow is not None and net_income is not None and net_income > 0:
        cash_conversion_ratio = free_cashflow / net_income

    market_cap = _as_float(info.get("marketCap"))
    price_to_fcf = market_cap / free_cashflow if market_cap and free_cashflow and free_cashflow > 0 else None

    interest_coverage, _ebit, _interest = _interest_coverage(data.income_stmt)

    peer_growths, peer_gms, peer_oms, peer_nms = [], [], [], []
    peer_roes, peer_roas = [], []
    peer_des, peer_pes, peer_divs, peer_fcf_to_debts = [], [], [], []
    peer_pbs, peer_pfcfs = [], []
    peer_stmts = data.peer_income_stmts or [None] * len(data.peer_info)
    for p, stmt in zip(data.peer_info, peer_stmts):
        peer_gms.append(p.get("grossMargins"))
        peer_oms.append(p.get("operatingMargins"))
        peer_nms.append(p.get("profitMargins"))
        peer_roes.append(p.get("returnOnEquity"))
        peer_roas.append(p.get("returnOnAssets"))
        de = _as_float(p.get("debtToEquity"))
        peer_des.append(de / 100 if de is not None else None)
        peer_pes.append(p.get("trailingPE") or p.get("forwardPE"))
        dy = _as_float(p.get("dividendYield"))
        dy = dy / 100 if dy is not None else _as_float(p.get("trailingAnnualDividendYield"))
        peer_divs.append(dy)
        peer_fcf_to_debts.append(_fcf_to_debt(p.get("freeCashflow"), p.get("totalDebt")))
        peer_growth, _ = _revenue_cagr(stmt) if stmt is not None else (None, 0)
        peer_growths.append(peer_growth)
        peer_pbs.append(p.get("priceToBook"))
        p_mcap, p_fcf = _as_float(p.get("marketCap")), _as_float(p.get("freeCashflow"))
        peer_pfcfs.append(p_mcap / p_fcf if p_mcap and p_fcf and p_fcf > 0 else None)

    return Metrics(
        ticker=data.ticker,
        company_name=info.get("longName") or info.get("shortName"),
        sector=info.get("sector"),
        industry=info.get("industry"),
        price=info.get("currentPrice") or info.get("regularMarketPrice"),
        history=data.history,
        revenue_growth_5y=growth,
        years_of_revenue_data=years,
        gross_margin=info.get("grossMargins"),
        operating_margin=info.get("operatingMargins"),
        net_margin=info.get("profitMargins"),
        return_on_equity=_as_float(info.get("returnOnEquity")),
        return_on_assets=_as_float(info.get("returnOnAssets")),
        debt_to_equity=debt_to_equity,
        total_debt=info.get("totalDebt"),
        free_cashflow=free_cashflow,
        fcf_to_debt=fcf_to_debt,
        pe_ratio=info.get("trailingPE") or info.get("forwardPE"),
        avg_volume=avg_volume,
        dividend_yield=div_yield,
        dividend_streak_years=_dividend_streak(data.dividends),
        earnings_growth=_as_float(info.get("earningsGrowth")),
        beta=_as_float(info.get("beta")),
        target_mean_price=_as_float(info.get("targetMeanPrice")),
        target_high_price=_as_float(info.get("targetHighPrice")),
        target_low_price=_as_float(info.get("targetLowPrice")),
        held_percent_insiders=_as_float(info.get("heldPercentInsiders")),
        held_percent_institutions=_as_float(info.get("heldPercentInstitutions")),
        short_percent_of_float=_as_float(info.get("shortPercentOfFloat")),
        peer_avg_revenue_growth=_avg(peer_growths),
        peer_avg_gross_margin=_avg(peer_gms),
        peer_avg_operating_margin=_avg(peer_oms),
        peer_avg_net_margin=_avg(peer_nms),
        peer_avg_roe=_avg(peer_roes),
        peer_avg_roa=_avg(peer_roas),
        peer_avg_debt_to_equity=_avg(peer_des),
        peer_avg_fcf_to_debt=_avg(peer_fcf_to_debts),
        peer_avg_pe_ratio=_avg(peer_pes),
        peer_avg_dividend_yield=_avg(peer_divs),
        peer_avg_price_to_book=_avg(peer_pbs),
        peer_avg_price_to_fcf=_avg(peer_pfcfs),
        peer_count=len(data.peer_info),
        net_income=net_income,
        cash_conversion_ratio=cash_conversion_ratio,
        current_ratio=_as_float(info.get("currentRatio")),
        interest_coverage=interest_coverage,
        price_to_book=_as_float(info.get("priceToBook")),
        price_to_fcf=price_to_fcf,
        payout_ratio=_as_float(info.get("payoutRatio")),
        shares_cagr=_shares_cagr(data.income_stmt),
        growth_steadiness=_growth_steadiness(data.income_stmt),
    )

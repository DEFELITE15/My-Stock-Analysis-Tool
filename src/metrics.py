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

    debt_to_equity: float | None  # as a ratio (1.5 = 150%)
    total_debt: float | None

    pe_ratio: float | None

    avg_volume: float | None

    dividend_yield: float | None
    dividend_streak_years: int  # consecutive years of flat-or-rising dividends

    peer_avg_revenue_growth: float | None
    peer_avg_gross_margin: float | None
    peer_avg_operating_margin: float | None
    peer_avg_net_margin: float | None
    peer_avg_debt_to_equity: float | None
    peer_avg_pe_ratio: float | None
    peer_avg_dividend_yield: float | None
    peer_count: int


def _revenue_cagr(income_stmt: pd.DataFrame) -> tuple[float | None, int]:
    """CAGR of Total Revenue across whatever annual history Yahoo provides
    (usually up to 4 years, occasionally 5)."""
    if income_stmt is None or income_stmt.empty:
        return None, 0
    row = None
    for label in ("Total Revenue", "TotalRevenue"):
        if label in income_stmt.index:
            row = income_stmt.loc[label]
            break
    if row is None:
        return None, 0

    series = row.dropna()
    # yfinance columns are period-end dates, most recent first
    series = series[list(series.index)[::-1]] if not series.empty else series
    if len(series) < 2:
        return None, len(series)

    start, end = float(series.iloc[0]), float(series.iloc[-1])
    years = len(series) - 1
    if start <= 0 or end <= 0 or years <= 0:
        return None, len(series)

    cagr = (end / start) ** (1 / years) - 1
    return cagr, len(series)


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


def _avg(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def build_metrics(data: StockData) -> Metrics:
    info = data.info
    growth, years = _revenue_cagr(data.income_stmt)

    debt_to_equity = info.get("debtToEquity")
    if debt_to_equity is not None:
        debt_to_equity = debt_to_equity / 100  # yfinance reports as percent

    avg_volume = info.get("averageVolume") or info.get("averageDailyVolume10Day")

    # yfinance's `dividendYield` is always in percentage-point form (5.28 == 5.28%),
    # never a decimal fraction -- always divide by 100. Fall back to the
    # trailing-twelve-month yield (already a decimal) if it's missing.
    div_yield = info.get("dividendYield")
    if div_yield is not None:
        div_yield = div_yield / 100
    else:
        div_yield = info.get("trailingAnnualDividendYield")

    peer_growths, peer_gms, peer_oms, peer_nms = [], [], [], []
    peer_des, peer_pes, peer_divs = [], [], []
    peer_stmts = data.peer_income_stmts or [None] * len(data.peer_info)
    for p, stmt in zip(data.peer_info, peer_stmts):
        peer_gms.append(p.get("grossMargins"))
        peer_oms.append(p.get("operatingMargins"))
        peer_nms.append(p.get("profitMargins"))
        de = p.get("debtToEquity")
        peer_des.append(de / 100 if de is not None else None)
        peer_pes.append(p.get("trailingPE") or p.get("forwardPE"))
        dy = p.get("dividendYield")
        dy = dy / 100 if dy is not None else p.get("trailingAnnualDividendYield")
        peer_divs.append(dy)
        peer_growth, _ = _revenue_cagr(stmt) if stmt is not None else (None, 0)
        peer_growths.append(peer_growth)

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
        debt_to_equity=debt_to_equity,
        total_debt=info.get("totalDebt"),
        pe_ratio=info.get("trailingPE") or info.get("forwardPE"),
        avg_volume=avg_volume,
        dividend_yield=div_yield,
        dividend_streak_years=_dividend_streak(data.dividends),
        peer_avg_revenue_growth=_avg(peer_growths),
        peer_avg_gross_margin=_avg(peer_gms),
        peer_avg_operating_margin=_avg(peer_oms),
        peer_avg_net_margin=_avg(peer_nms),
        peer_avg_debt_to_equity=_avg(peer_des),
        peer_avg_pe_ratio=_avg(peer_pes),
        peer_avg_dividend_yield=_avg(peer_divs),
        peer_count=len(data.peer_info),
    )

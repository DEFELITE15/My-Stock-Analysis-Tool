"""
Extracts clean, comparable metrics for ETFs and mutual funds from raw
yfinance data.

Funds don't have revenue, margins, or debt like operating companies, so
instead of industry peers they're benchmarked against a live S&P 500 ETF
(SPY) proxy, fetched fresh every run -- the same "compare against something
real, not a fixed number" philosophy used for stocks.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .data_fetcher import StockData
from .metrics import _as_float

FUND_QUOTE_TYPES = {"ETF", "MUTUALFUND"}


def is_fund(info: dict) -> bool:
    return (info or {}).get("quoteType") in FUND_QUOTE_TYPES


@dataclass
class FundMetrics:
    ticker: str
    name: str | None
    quote_type: str | None
    category: str | None
    fund_family: str | None
    price: float | None
    history: pd.DataFrame

    expense_ratio: float | None  # percentage points, e.g. 0.03 == 0.03%
    ytd_return: float | None  # decimal, 0.12 == 12%
    three_year_return: float | None  # annualized, decimal
    five_year_return: float | None  # annualized, decimal
    dividend_yield: float | None  # decimal
    total_assets: float | None
    avg_volume: float | None

    benchmark_ticker: str
    benchmark_expense_ratio: float | None
    benchmark_ytd_return: float | None
    benchmark_three_year_return: float | None
    benchmark_five_year_return: float | None
    benchmark_dividend_yield: float | None
    benchmark_avg_volume: float | None


def _div_yield(info: dict) -> float | None:
    # Same yfinance quirk as stocks: dividendYield is always percentage-point
    # form (1.07 == 1.07%), never a decimal fraction.
    dy = _as_float(info.get("dividendYield"))
    return dy / 100 if dy is not None else None


def _ytd_return(info: dict) -> float | None:
    # Unlike threeYearAverageReturn/fiveYearAverageReturn (already decimal
    # fractions), yfinance's ytdReturn is percentage-point form (10.19 ==
    # 10.19%) -- yet another inconsistent-units quirk in the same info dict.
    ytd = _as_float(info.get("ytdReturn"))
    return ytd / 100 if ytd is not None else None


def build_fund_metrics(data: StockData, benchmark: StockData) -> FundMetrics:
    info = data.info
    b = benchmark.info

    return FundMetrics(
        ticker=data.ticker,
        name=info.get("longName") or info.get("shortName"),
        quote_type=info.get("quoteType"),
        category=info.get("category"),
        fund_family=info.get("fundFamily"),
        price=info.get("regularMarketPrice") or info.get("currentPrice") or info.get("navPrice"),
        history=data.history,
        expense_ratio=_as_float(info.get("netExpenseRatio")),
        ytd_return=_ytd_return(info),
        three_year_return=_as_float(info.get("threeYearAverageReturn")),
        five_year_return=_as_float(info.get("fiveYearAverageReturn")),
        dividend_yield=_div_yield(info),
        total_assets=_as_float(info.get("totalAssets")),
        avg_volume=info.get("averageVolume") or info.get("averageDailyVolume10Day"),
        benchmark_ticker=benchmark.ticker,
        benchmark_expense_ratio=_as_float(b.get("netExpenseRatio")),
        benchmark_ytd_return=_ytd_return(b),
        benchmark_three_year_return=_as_float(b.get("threeYearAverageReturn")),
        benchmark_five_year_return=_as_float(b.get("fiveYearAverageReturn")),
        benchmark_dividend_yield=_div_yield(b),
        benchmark_avg_volume=b.get("averageVolume") or b.get("averageDailyVolume10Day"),
    )

"""
Data fetcher for the Stock Analysis Machine.

Pulls live fundamental + price data from Yahoo Finance (via yfinance) for a
given ticker, plus a peer/industry sample used to compute industry-relative
benchmarks (growth, margins, valuation, debt).

Everything here hits the network fresh -- no stale hardcoded numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import yfinance as yf

MAX_PEERS = 8


@dataclass
class StockData:
    ticker: str
    info: dict
    income_stmt: pd.DataFrame
    dividends: pd.Series
    history: pd.DataFrame
    peer_tickers: list = field(default_factory=list)
    peer_info: list = field(default_factory=list)  # list of dicts
    peer_income_stmts: list = field(default_factory=list)  # list of DataFrames


def _safe_get(d: dict, *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def _candidate_symbols(key: str, kind: str, exclude: str) -> list[str]:
    """Raw candidate peer symbols from an Industry or Sector's top-companies list."""
    if not key:
        return []
    try:
        group = yf.Industry(key) if kind == "industry" else yf.Sector(key)
        top = group.top_companies
        if top is None or top.empty:
            return []
        return [s for s in top.index if s != exclude]
    except Exception:
        return []


def _is_comparable_size(candidate_market_cap: float | None, target_market_cap: float | None) -> bool:
    """Reject peers that are wildly different in size (e.g. nano-caps sitting in
    the same narrow Yahoo 'industry' bucket as a mega-cap) -- they distort
    averages more than they inform them."""
    if not candidate_market_cap or not target_market_cap:
        return False
    ratio = candidate_market_cap / target_market_cap
    return 0.03 <= ratio <= 30


def build_peer_set(t: yf.Ticker, info: dict) -> tuple[list[str], list[dict], list]:
    """Build a peer set for benchmarking: try the narrow industry classification
    first, and fall back to (and blend in) the broader sector if the industry
    doesn't have enough comparably-sized companies."""
    target_market_cap = info.get("marketCap")
    industry_candidates = _candidate_symbols(info.get("industryKey"), "industry", t.ticker)
    sector_candidates = _candidate_symbols(info.get("sectorKey"), "sector", t.ticker)

    ordered_candidates = list(dict.fromkeys(industry_candidates + sector_candidates))

    peer_tickers, peer_info, peer_income_stmts = [], [], []
    for sym in ordered_candidates:
        if len(peer_tickers) >= MAX_PEERS:
            break
        try:
            peer_obj = yf.Ticker(sym)
            pinfo = peer_obj.info
            if not pinfo or not _is_comparable_size(pinfo.get("marketCap"), target_market_cap):
                continue
            peer_tickers.append(sym)
            peer_info.append(pinfo)
            try:
                peer_income_stmts.append(peer_obj.income_stmt)
            except Exception:
                peer_income_stmts.append(pd.DataFrame())
        except Exception:
            continue

    return peer_tickers, peer_info, peer_income_stmts


def fetch_stock_data(ticker: str) -> StockData:
    """Fetch everything needed to score `ticker`, live, on every call."""
    t = yf.Ticker(ticker)
    info = t.info or {}
    if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
        # Still allow it through -- some valid tickers (ETFs, etc.) lack these fields,
        # but a totally empty info dict usually means an invalid ticker.
        if not info or len(info) < 3:
            raise ValueError(f"No data found for ticker '{ticker}'. Check the symbol.")

    try:
        income_stmt = t.income_stmt if t.income_stmt is not None else pd.DataFrame()
    except Exception:
        income_stmt = pd.DataFrame()

    try:
        dividends = t.dividends if t.dividends is not None else pd.Series(dtype=float)
    except Exception:
        dividends = pd.Series(dtype=float)

    try:
        history = t.history(period="1y")
    except Exception:
        history = pd.DataFrame()

    peer_tickers, peer_info, peer_income_stmts = build_peer_set(t, info)

    return StockData(
        ticker=ticker.upper(),
        info=info,
        income_stmt=income_stmt,
        dividends=dividends,
        history=history,
        peer_tickers=peer_tickers,
        peer_info=peer_info,
        peer_income_stmts=peer_income_stmts,
    )

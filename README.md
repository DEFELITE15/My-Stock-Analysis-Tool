# Stock Analysis Machine

Enter any stock, ETF, or mutual fund ticker and get a live grade out of 10,
plus a **BUY / HOLD / SELL** signal. Every run pulls fresh data straight from
Yahoo Finance — no stale or hardcoded numbers. The stock rubric is built for
**long-term, buy-and-hold investors**: on top of standard growth/valuation
metrics, it digs into earnings quality, balance-sheet durability, and
whether management actually returns cash to shareholders responsibly — the
things that matter most over a multi-year hold, not a quarterly trade.

## How it's graded

### Stocks

Each stock is scored 0-10 across six categories. Most sub-metrics are scored
**relative to a live sample of its industry/sector peers** (also pulled
fresh every run) rather than fixed thresholds — a 15% net margin means
something very different for a software company than for a grocery chain.
A few durability checks (coverage ratios, earnings quality, dividend safety)
are scored against fixed floors instead, since "how much interest coverage
is enough" doesn't really depend on what industry you're in.

| Category | Points | Logic |
|---|---|---|
| Revenue Growth | 2.0 | Revenue CAGR (up to 5yr) vs. peer average (75%), plus **year-over-year growth consistency** — steady growth scores higher than lumpy/erratic growth of the same average rate (25%) |
| Profitability | 2.5 | Gross / operating / net margin plus ROE and ROA vs. peer average (75%), plus **cash-earnings quality** — how much of reported net income actually shows up as free cash flow (25%) |
| Financial Health | 2.0 | Debt-to-equity (30%) and FCF-to-debt coverage (25%) vs. peer average, plus **current ratio** (25%) and **interest coverage** (20%) against fixed safety floors |
| Valuation | 1.5 | Blended across three lenses vs. peer average: growth-adjusted P/E (60%), **P/FCF** (25%), and **P/B** (15%) — so one accounting-sensitive multiple doesn't drive the whole score |
| Capital Allocation | 1.5 | Dividend yield (25%), consistency (25%), and **payout-ratio sustainability** (20%) vs. peer average/fixed floor, plus **buybacks vs. dilution** — a shrinking share count earns credit even with no dividend at all (30%) |
| Liquidity | 0.5 | Average trading volume, as a sanity check against thin/illiquid stocks |

**Signal:** 8.0-10 = BUY, 5.0-7.9 = HOLD, below 5.0 = SELL.

Peers are pulled from Yahoo's industry classification first; if that group is
too narrow (e.g. a mega-cap that dominates its own "industry" bucket), it
blends in the broader sector and filters out companies that are too different
in size (market cap) to be a meaningful comparison.

**Why capital allocation instead of a plain dividend category:** some of the
best long-term compounders (Alphabet, Meta) return cash almost entirely
through buybacks rather than dividends. Grading dividends in isolation used
to shut those companies out of a whole category's points; now a shrinking
share count earns credit on its own.

**Why cash-earnings quality and coverage ratios:** margins and growth can
look great on an income statement while the underlying cash generation or
balance sheet cushion is quietly weak — the kind of thing that doesn't
matter for a quarter but matters a lot over a multi-year hold.

The app also surfaces an **Ownership & Risk** panel (analyst price target,
beta, insider/institutional ownership, short interest) for extra context —
this is informational only and isn't factored into the 0-10 score, since the
grade is built purely from hard fundamentals, not forecasts or sentiment.

### ETFs & Mutual Funds

Funds (e.g. VOO, VTI, VFIAX) don't have revenue, margins, or debt, so they're
graded on a separate rubric — benchmarked live against a S&P 500 ETF (SPY)
proxy instead of industry peers:

| Category | Points | Logic |
|---|---|---|
| Cost | 3.0 | Expense ratio vs. SPY's (lower is better — fees compound over decades) |
| Performance | 4.5 | YTD / 3yr / 5yr annualized return vs. SPY (3yr weighted heaviest) |
| Dividend Yield | 1.0 | Distribution yield vs. SPY's |
| Liquidity | 1.5 | Average daily trading volume |

Same 8.0/5.0 BUY/HOLD/SELL thresholds apply.

Click "Why this grade?" in the app to see the exact numbers and reasoning
behind every category score.

## Setup (local)

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the local URL it prints (usually http://localhost:8501).

## Deploy for free (so it's a real website)

1. Push this repo to GitHub (see below).
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
3. Click **New app**, pick this repo, branch `main`, and file `app.py`.
4. Deploy. You'll get a free public URL, and every page load / ticker search
   fetches live data — no separate "update" step needed.

## Notes / limitations

- Data comes from Yahoo Finance's free, unofficial API via `yfinance`. It can
  occasionally hiccup or rate-limit — the app is built to fail gracefully and
  fall back to neutral scoring for any single missing field rather than crash.
- Revenue growth is calculated from however many years of annual data Yahoo's
  free tier exposes (typically 3-4 years, sometimes 5).
- This is a research/screening tool, not financial advice.

## License

All Rights Reserved — see [LICENSE](LICENSE). This code is public for
portfolio/demonstration purposes only; copying, reuse, or redistribution is
not permitted without permission.

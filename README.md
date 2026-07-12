# Stock Analysis Machine

Enter any stock, ETF, or mutual fund ticker and get a live grade out of 10,
plus a **BUY / HOLD / SELL** signal. Every run pulls fresh data straight from
Yahoo Finance — no stale or hardcoded numbers.

## How it's graded

### Stocks

Each stock is scored 0-10 across six categories, **relative to a live sample of
its industry/sector peers** (also pulled fresh every run) rather than fixed
thresholds — a 15% net margin means something very different for a software
company than for a grocery chain.

| Category | Points | Logic |
|---|---|---|
| Revenue Growth | 2.5 | Revenue CAGR (up to 5yr, based on available data) vs. peer average |
| Profitability | 2.5 | Gross / operating / net margin **plus ROE and ROA** (capital efficiency) vs. peer average |
| Financial Health | 2.0 | Debt-to-equity (60%) **plus free-cash-flow-to-debt coverage** (40%) vs. peer average |
| Valuation | 1.5 | P/E vs. peer average, **growth-adjusted** (PEG-style) so high-growth stocks aren't unfairly punished for a higher P/E |
| Dividend | 1.0 | Yield vs. peer average + consecutive years of flat-or-rising dividends |
| Liquidity | 0.5 | Average trading volume, as a sanity check against thin/illiquid stocks |

**Signal:** 8.0-10 = BUY, 5.0-7.9 = HOLD, below 5.0 = SELL.

Peers are pulled from Yahoo's industry classification first; if that group is
too narrow (e.g. a mega-cap that dominates its own "industry" bucket), it
blends in the broader sector and filters out companies that are too different
in size (market cap) to be a meaningful comparison.

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

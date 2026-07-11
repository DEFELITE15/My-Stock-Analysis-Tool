# Stock Analysis Machine

Enter any stock ticker and get a live grade out of 10, plus a **BUY / HOLD / SELL**
signal. Every run pulls fresh data straight from Yahoo Finance — no stale or
hardcoded numbers.

## How it's graded

Each stock is scored 0-10 across six categories, **relative to a live sample of
its industry/sector peers** (also pulled fresh every run) rather than fixed
thresholds — a 15% net margin means something very different for a software
company than for a grocery chain.

| Category | Points | Logic |
|---|---|---|
| Revenue Growth | 2.5 | Revenue CAGR (up to 5yr, based on available data) vs. peer average |
| Profitability | 2.5 | Gross / operating / net margin vs. peer average |
| Financial Health | 2.0 | Debt-to-equity vs. peer average (lower is better) |
| Valuation | 1.5 | P/E vs. peer average, **growth-adjusted** (PEG-style) so high-growth stocks aren't unfairly punished for a higher P/E |
| Dividend | 1.0 | Yield vs. peer average + consecutive years of flat-or-rising dividends |
| Liquidity | 0.5 | Average trading volume, as a sanity check against thin/illiquid stocks |

**Signal:** 8.0-10 = BUY, 5.0-7.9 = HOLD, below 5.0 = SELL.

Peers are pulled from Yahoo's industry classification first; if that group is
too narrow (e.g. a mega-cap that dominates its own "industry" bucket), it
blends in the broader sector and filters out companies that are too different
in size (market cap) to be a meaningful comparison.

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

## Pushing to GitHub

```bash
git add -A
git commit -m "Initial Stock Analysis Machine"
git branch -M main
git remote add origin https://github.com/<your-username>/stock-analysis-machine.git
git push -u origin main
```

(Create the empty repo on github.com first, without a README, then run the
commands above.)

## Notes / limitations

- Data comes from Yahoo Finance's free, unofficial API via `yfinance`. It can
  occasionally hiccup or rate-limit — the app is built to fail gracefully and
  fall back to neutral scoring for any single missing field rather than crash.
- Revenue growth is calculated from however many years of annual data Yahoo's
  free tier exposes (typically 3-4 years, sometimes 5).
- This is a research/screening tool, not financial advice.

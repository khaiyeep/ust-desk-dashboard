# UST Desk Dashboard

A refreshable dashboard for a US Treasury desk that runs active duration and
curve positions against a benchmark. It comes in two forms:

- **Website (`site/`)** works on desktop and phone with no Python. See below.
- **Local report (`refresh.py`)** writes one self-contained HTML file plus an
  Excel snapshot.

## Website

The site is static: `index.html`, `app.js`, `analytics.js` and `data.json`,
hosted on GitHub Pages.

**How the data stays fresh:**

| What | How it updates |
|---|---|
| Treasury nominal and TIPS curves, coupon auctions, EFFR, SOFR | Fetched **live in your browser** each time the page opens and whenever you tap **Refresh** |
| History, term premium, S&P 500, VIX, USD, USD/MYR, reserves, TGA, RRP, FOMC dates | Rebuilt into `data.json` by GitHub Actions at 06:30 and 21:00 Malaysia time on weekdays |

You can also run the build yourself: in the GitHub app or website, go to
**Actions → Refresh data and publish site → Run workflow**.

**Your positions.** Enter key-rate durations under **Book setup**, either by
typing them or pasting rows copied from Excel or PORT. They are saved in that
browser only and are never uploaded. To get the same numbers on your phone,
use **Copy setup link** and open the link there. The numbers travel in the part
of the link after `#`, which browsers don't send to the server.

**Public page, public data.** The page and `data.json` contain only public
market data. Anyone with the URL can see them, and search engines are asked
not to index the page. Don't commit real positions to the repo. Keep them in
Book setup.

**Preview locally:**

```
python3 -m http.server 8000 --directory site
```

Then open http://localhost:8000.

## Local report

```
python refresh.py
```

Or double-click `refresh.command` (macOS) or `refresh.bat` (Windows).

## Setup (once)

```
pip install -r requirements.txt
```

Python 3.10+. Behind a corporate proxy, set `HTTPS_PROXY` before running.

## Daily use

1. Export key-rate durations for **your portfolio and the benchmark** from
   Bloomberg PORT or your risk system into `positions.csv`
   (tenors `3M,6M,1Y,2Y,3Y,5Y,7Y,10Y,20Y,30Y`, values in years).
2. Run `python refresh.py`. It opens `output/latest.html`.
3. A dated copy (`output/ust_dashboard_YYYY-MM-DD.html`) and an Excel snapshot
   are kept, so you can look back at what the book looked like on any day.

| Flag | Use |
|---|---|
| `--offline` | Rebuild from cached data only (no network needed) |
| `--no-open` | Don't open the browser. Use this for scheduled runs |
| `--positions path.csv` | Use another KRD file, for example a proposed trade |
| `--no-excel` | Skip the Excel export |

**What-if trades:** copy `positions.csv` to `whatif.csv`, change the KRDs to
reflect the trade, run `python refresh.py --positions whatif.csv`, and compare
tracking error, scenario P&L and carry with the live book.

## Settings: `config.py`

Replace these placeholders first: `PORTFOLIO_MV_USD`, `TE_BUDGET_BP` and
`ACTIVE_DURATION_LIMIT_YRS`. You can also change the scenarios, the spreads and
flies, the carry horizon, the funding tenor and the look-back windows.

## What's on the page

| Section | What it answers |
|---|---|
| Morning brief | Key levels and 1d/1w/1m changes, plus auto-drafted talking points for the morning call |
| Curve | Where the curve is versus 1w/1m/1y ago, and which tenors did the moving |
| Spreads & flies | 2s10s, 5s30s, 2s5s10s and others with 1y z-scores and percentiles (the RV screen) |
| Policy, inflation, term premium | Front end versus EFFR, TIPS real yields, breakevens, Kim-Wright term premium |
| Active book | Active KRD, ex-ante TE versus budget, VaR, TE contribution by tenor, scenario P&L, carry of the active book, PCA factor exposure |
| Carry / PCA | 3m carry and roll-down breakevens by tenor, level/slope/curvature loadings, recent factor moves in σ |
| Cross-asset | Stock-bond correlation (the key TPA number), realised vol, reserves/TGA/RRP, USD/MYR, broad USD, VIX |
| Supply | Next FOMC dates, announced coupon auctions, recent auction results versus the 6-auction average |

## Scheduling

**macOS (cron, 7:30am MYT on weekdays):** run `crontab -e` and add:

```
30 7 * * 1-5 cd ~/Documents/ust_desk_dashboard && /usr/bin/python3 refresh.py --no-open
```

**Windows:** in Task Scheduler, create a Basic Task that runs daily. Set the action to
`python` with arguments `refresh.py --no-open`, and set "Start in" to this folder.

The Treasury curve updates after the NY close (about 6am MYT). FRED series lag by
1 to 5 days, and each tile shows its own as-of date.

## Data sources

| Data | Source |
|---|---|
| Nominal and real par curves | U.S. Treasury Daily Treasury Par Yield Curve Rates |
| EFFR, SOFR, IORB, TIPS, breakevens, term premium, VIX, S&P 500, USD, USD/MYR, reserves, TGA, RRP | FRED (St. Louis Fed) |
| Auction schedule and results | Treasury FiscalData `auctions_query` API |
| FOMC dates | federalreserve.gov (falls back to `FOMC_FALLBACK` in config) |

Every source is cached in `data/cache/`. If a fetch fails, the dashboard uses
the cache and lists a warning in the footer.

## Moving to Bloomberg

On the desk you'll have better data. Each loader in `ust_dash/sources.py`
returns a plain DataFrame (dates × tenors, in %), so you can swap one out
without touching the analytics. For example, replace `load_treasury_curve`
with a `BDH` pull using `xbbg` or `blpapi` on generic tickers
(`USGG2YR Index`, `USGG10YR Index`, …; check each on your terminal). A good
first upgrade is to replace par yields with **on-the-run bond yields** and add
SOFR swap spreads.

## Known simplifications

- **Par curve, not bonds.** Carry and roll use par yields with linear
  interpolation. That works for tenor-level comparison. For individual bonds,
  use YAS or a fitted-curve model.
- **Rates-only risk.** TE and VaR come from 1y historical covariance of
  par-yield changes at the key rates. They exclude spread, bond selection,
  TIPS and futures basis risk, so your risk system's TE will be higher.
- **Crude policy pricing.** 1Y bill minus EFFR includes the bill/OIS basis and
  term premium. Use WIRP or SOFR futures for the real implied path.
- **No auction tail.** The public data has no when-issued yield. Take tails
  from Bloomberg or dealer recaps.

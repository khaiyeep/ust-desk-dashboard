"""
Desk settings. This is the only file you should need to edit day to day
(plus positions.csv).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "data" / "cache"
OUTPUT_DIR = ROOT / "output"
POSITIONS_FILE = ROOT / "positions.csv"

# ---------------------------------------------------------------------------
# Book
# ---------------------------------------------------------------------------
# Market value of the UST portfolio you manage against the benchmark (USD).
# Used to turn KRD / bp numbers into dollars. PLACEHOLDER - set to your mandate.
PORTFOLIO_MV_USD = 5_000_000_000

# Tracking-error budget for the desk (bp per year, ex-ante). PLACEHOLDER.
TE_BUDGET_BP = 50

# Active duration limit vs benchmark (years, +/-). PLACEHOLDER.
ACTIVE_DURATION_LIMIT_YRS = 0.50

# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
HISTORY_YEARS = 3            # years of curve history pulled from Treasury
ZSCORE_WINDOW = 252          # trading days for z-scores / percentiles
COV_WINDOW = 252             # trading days for covariance (TE, VaR, PCA)
CORR_WINDOW = 63             # trading days for rolling stock-bond correlation
CARRY_HORIZON_YRS = 0.25     # carry & roll-down horizon (3 months)
FUNDING_TENOR = "3M"         # cash alternative for carry (T-bill). Reserve managers
                             # usually fund an overweight by selling bills, not repo.

# Key-rate tenors. Matches Bloomberg PORT's default KRD buckets.
KEY_RATES = ["3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]

# PCA runs on 1Y-30Y: bills are pinned by policy and would dominate the
# slope/curvature factors if included.
PCA_TENORS = ["1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]

TENOR_YEARS = {
    "1M": 1 / 12, "1.5M": 1.5 / 12, "2M": 2 / 12, "3M": 0.25, "4M": 4 / 12,
    "6M": 0.5, "1Y": 1, "2Y": 2, "3Y": 3, "5Y": 5, "7Y": 7, "10Y": 10,
    "20Y": 20, "30Y": 30,
}

# Curve spreads (bp). Flies are 2*belly - wings: positive = belly cheap.
SPREADS = {
    "3M10Y":    {"10Y": 1, "3M": -1},
    "2s10s":    {"10Y": 1, "2Y": -1},
    "5s30s":    {"30Y": 1, "5Y": -1},
    "10s30s":   {"30Y": 1, "10Y": -1},
    "2s5s10s":  {"5Y": 2, "2Y": -1, "10Y": -1},
    "5s10s30s": {"10Y": 2, "5Y": -1, "30Y": -1},
}

# Parametric curve scenarios: {tenor_years: shift_bp}. Linear in between,
# flat beyond the end points. Edit/add freely.
SCENARIOS = {
    "Parallel +25":      {0.25: 25, 30: 25},
    "Parallel -25":      {0.25: -25, 30: -25},
    "Bull steepener":    {0.25: -25, 2: -25, 10: -5, 30: 0},
    "Bear steepener":    {0.25: 0, 2: 0, 10: 20, 30: 25},
    "Bull flattener":    {0.25: 0, 2: -5, 10: -20, 30: -25},
    "Bear flattener":    {0.25: 25, 2: 25, 10: 5, 30: 0},
    "Belly cheapens +10": {2: 0, 5: 10, 10: 0},
    "Fed cuts repriced -50 front": {0.25: -50, 1: -40, 2: -30, 5: -15, 10: -5, 30: 0},
    "Term-premium shock +40 long": {0.25: 0, 2: 5, 10: 30, 30: 40},
}

# ---------------------------------------------------------------------------
# Data (all free, no API keys). Proxy: set HTTPS_PROXY in your environment.
# ---------------------------------------------------------------------------
FRED_SERIES = {
    "EFFR": "Effective fed funds",
    "IORB": "Interest on reserve balances",
    "SOFR": "SOFR",
    "DFII5": "5Y TIPS real yield",
    "DFII10": "10Y TIPS real yield",
    "DFII30": "30Y TIPS real yield",
    "T5YIE": "5Y breakeven",
    "T10YIE": "10Y breakeven",
    "T5YIFR": "5Y5Y forward breakeven",
    "THREEFYTP10": "10Y term premium (Kim-Wright)",
    "VIXCLS": "VIX",
    "SP500": "S&P 500",
    "DTWEXBGS": "Broad USD index",
    "DEXMAUS": "USD/MYR",
    "WRESBAL": "Reserve balances ($mn)",
    "WTREGEN": "Treasury General Account ($mn)",
    "RRPONTSYD": "ON RRP ($bn)",
}

# Fallback if the Fed calendar page can't be parsed. Verified from
# federalreserve.gov on 2026-09-27. (*) = SEP / dot-plot meeting.
FOMC_FALLBACK = [
    "2026-01-28", "2026-03-18*", "2026-04-29", "2026-06-17*",
    "2026-07-29", "2026-09-16*", "2026-10-28", "2026-12-09*",
]

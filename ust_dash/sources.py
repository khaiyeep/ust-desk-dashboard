"""
Data loaders. Every loader caches to data/cache and falls back to the cache
when the network is unavailable, so the dashboard still builds offline.

Sources (free, no keys):
  - US Treasury daily par nominal & real yield curves   home.treasury.gov
  - FRED single-series CSV                              fred.stlouisfed.org
  - Treasury auctions (announced + results)             api.fiscaldata.treasury.gov
  - FOMC calendar                                       federalreserve.gov
"""
from __future__ import annotations

import io
import os
import re
import time
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

import config

HEADERS = {"User-Agent": "Mozilla/5.0 (UST desk dashboard)"}
TIMEOUT = 30

TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all?type={kind}&field_tdr_date_value={year}&page&_format=csv"
)
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}"
FRED_API = "https://api.stlouisfed.org/fred/series/observations"
NYFED = "https://markets.newyorkfed.org/api"
DTS_CASH = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance"
AUCTIONS_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query"
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

TREASURY_COLS = {
    "1 Mo": "1M", "1.5 Month": "1.5M", "2 Mo": "2M", "3 Mo": "3M", "4 Mo": "4M",
    "6 Mo": "6M", "1 Yr": "1Y", "2 Yr": "2Y", "3 Yr": "3Y", "5 YR": "5Y", "5 Yr": "5Y",
    "7 YR": "7Y", "7 Yr": "7Y", "10 YR": "10Y", "10 Yr": "10Y", "20 YR": "20Y",
    "20 Yr": "20Y", "30 YR": "30Y", "30 Yr": "30Y",
}

log_lines: list[str] = []


def _log(msg: str) -> None:
    log_lines.append(msg)
    print(msg)


def _get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r


def _cache_path(name: str):
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return config.CACHE_DIR / name


# ---------------------------------------------------------------------------
# Treasury par curves
# ---------------------------------------------------------------------------
def _treasury_year(kind: str, year: int, offline: bool) -> pd.DataFrame:
    path = _cache_path(f"treasury_{kind}_{year}.csv")
    this_year = dt.date.today().year
    # Past years never change once the year is over - reuse the cache.
    if path.exists() and (offline or year < this_year):
        return pd.read_csv(path, index_col=0, parse_dates=True)
    try:
        text = _get(TREASURY_URL.format(year=year, kind=kind)).text
        df = pd.read_csv(io.StringIO(text))
        df["Date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y")
        df = df.set_index("Date").rename(columns=TREASURY_COLS).sort_index()
        df = df.apply(pd.to_numeric, errors="coerce")
        df.to_csv(path)
        return df
    except Exception as e:  # network down, site change...
        if path.exists():
            _log(f"[warn] Treasury {kind} {year}: {e} - using cache")
            return pd.read_csv(path, index_col=0, parse_dates=True)
        raise


def load_treasury_curve(kind: str = "nominal", years: int = config.HISTORY_YEARS,
                        offline: bool = False) -> pd.DataFrame:
    """Daily par yields (%) indexed by date, columns = tenor labels."""
    t = {"nominal": "daily_treasury_yield_curve",
         "real": "daily_treasury_real_yield_curve"}[kind]
    this_year = dt.date.today().year
    frames = [_treasury_year(t, y, offline) for y in range(this_year - years, this_year + 1)]
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    order = [c for c in config.TENOR_YEARS if c in df.columns]
    return df[order]


# ---------------------------------------------------------------------------
# FRED
# ---------------------------------------------------------------------------
def _fred_fetch(sid: str, start: str) -> pd.Series:
    """FRED API when FRED_API_KEY is set (reliable from cloud runners), else the public CSV."""
    key = os.environ.get("FRED_API_KEY")
    last_err = None
    for attempt in range(2):
        try:
            if key:
                obs = _get(FRED_API, params={"series_id": sid, "api_key": key, "file_type": "json",
                                             "observation_start": start}).json()["observations"]
                s = pd.Series({pd.Timestamp(o["date"]): o["value"] for o in obs})
            else:
                text = _get(FRED_URL.format(sid=sid, start=start)).text
                s = pd.read_csv(io.StringIO(text), index_col=0, parse_dates=True).iloc[:, 0]
            s = pd.to_numeric(s, errors="coerce").dropna()
            s.name = sid
            return s
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(3 * (attempt + 1))
    raise last_err


def _fred_one(sid: str, start: str, offline: bool) -> pd.Series:
    path = _cache_path(f"fred_{sid}.csv")
    if offline and path.exists():
        return pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
    try:
        s = _fred_fetch(sid, start)
        s.to_frame().to_csv(path)
        return s
    except Exception as e:
        if path.exists():
            _log(f"[warn] FRED {sid}: {e} - using cache")
            return pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
        _log(f"[warn] FRED {sid}: {e} - no cache, series skipped")
        return pd.Series(dtype=float, name=sid)


def load_fred(series=None, years: int = config.HISTORY_YEARS + 1,
              offline: bool = False) -> dict[str, pd.Series]:
    series = list(series or config.FRED_SERIES)
    start = (dt.date.today() - dt.timedelta(days=365 * years)).isoformat()
    with ThreadPoolExecutor(max_workers=4) as ex:
        out = list(ex.map(lambda s: _fred_one(s, start, offline), series))
    return dict(zip(series, out))


# ---------------------------------------------------------------------------
# NY Fed rates and reverse repo, Treasury cash balance (TGA)
# ---------------------------------------------------------------------------
def load_nyfed_rate(kind: str, years: int = config.HISTORY_YEARS + 1) -> pd.Series:
    """EFFR or SOFR (%), daily, from the NY Fed markets API."""
    path = {"EFFR": "rates/unsecured/effr", "SOFR": "rates/secured/sofr"}[kind]
    start = (dt.date.today() - dt.timedelta(days=365 * years)).isoformat()
    rows = _get(f"{NYFED}/{path}/search.json",
                params={"startDate": start, "endDate": dt.date.today().isoformat()}).json()["refRates"]
    s = pd.Series({pd.Timestamp(r["effectiveDate"]): r["percentRate"] for r in rows}, name=kind)
    return pd.to_numeric(s, errors="coerce").dropna().sort_index()


def load_nyfed_rrp(years: int = config.HISTORY_YEARS + 1) -> pd.Series:
    """Overnight reverse repo take-up ($bn), daily, from the NY Fed markets API."""
    start = (dt.date.today() - dt.timedelta(days=365 * years)).isoformat()
    ops = _get(f"{NYFED}/rp/reverserepo/propositions/search.json",
               params={"startDate": start, "endDate": dt.date.today().isoformat()}).json()["repo"]["operations"]
    s = pd.Series({pd.Timestamp(o["operationDate"]): o["totalAmtAccepted"] for o in ops}, name="RRP")
    return (pd.to_numeric(s, errors="coerce").dropna() / 1e9).groupby(level=0).sum().sort_index()


def load_tga(years: int = config.HISTORY_YEARS + 1) -> pd.Series:
    """Treasury General Account closing balance ($mn), daily, from the Daily Treasury Statement."""
    start = (dt.date.today() - dt.timedelta(days=365 * years)).isoformat()
    params = {"filter": f"record_date:gte:{start},account_type:eq:Treasury General Account (TGA) Closing Balance",
              "fields": "record_date,open_today_bal", "page[size]": 10000}
    rows = _get(DTS_CASH, params=params).json()["data"]
    s = pd.Series({pd.Timestamp(r["record_date"]): r["open_today_bal"] for r in rows}, name="TGA")
    return pd.to_numeric(s, errors="coerce").dropna().sort_index()


# ---------------------------------------------------------------------------
# Treasury auctions
# ---------------------------------------------------------------------------
AUCTION_FIELDS = [
    "cusip", "security_type", "security_term", "auction_date", "issue_date",
    "reopening", "offering_amt", "high_yield", "high_discnt_margin", "bid_to_cover_ratio",
    "comp_accepted", "indirect_bidder_accepted", "direct_bidder_accepted",
    "primary_dealer_accepted", "inflation_index_security", "floating_rate",
]


def load_auctions(days_back: int = 730, offline: bool = False) -> pd.DataFrame:
    """Coupon auctions (notes, bonds, TIPS, FRNs): announced and completed."""
    path = _cache_path("auctions.csv")
    if offline and path.exists():
        return pd.read_csv(path, parse_dates=["auction_date", "issue_date"])
    start = (dt.date.today() - dt.timedelta(days=days_back)).isoformat()
    params = {
        "filter": f"auction_date:gte:{start},security_type:in:(Note,Bond)",
        "fields": ",".join(AUCTION_FIELDS),
        "sort": "-auction_date",
        "page[size]": 10000,
    }
    try:
        data = _get(AUCTIONS_URL, params=params).json()["data"]
        df = pd.DataFrame(data).replace("null", pd.NA)
        for c in ["auction_date", "issue_date"]:
            df[c] = pd.to_datetime(df[c])
        num = ["offering_amt", "high_yield", "high_discnt_margin", "bid_to_cover_ratio",
               "comp_accepted", "indirect_bidder_accepted", "direct_bidder_accepted",
               "primary_dealer_accepted"]
        df[num] = df[num].apply(pd.to_numeric, errors="coerce")
        df.to_csv(path, index=False)
        return df
    except Exception as e:
        if path.exists():
            _log(f"[warn] auctions: {e} - using cache")
            return pd.read_csv(path, parse_dates=["auction_date", "issue_date"])
        _log(f"[warn] auctions: {e} - skipped")
        return pd.DataFrame(columns=AUCTION_FIELDS)


# ---------------------------------------------------------------------------
# FOMC calendar
# ---------------------------------------------------------------------------
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}


def _parse_fomc(html: str) -> list[tuple[dt.date, bool]]:
    out = []
    # Split page into per-year panels, then pull month/date pairs in order.
    for m in re.finditer(r"(\d{4}) FOMC Meetings(.*?)(?=\d{4} FOMC Meetings|$)", html, re.S):
        year = int(m.group(1))
        body = m.group(2)
        months = re.findall(r"fomc-meeting__month[^>]*>\s*<strong>([A-Za-z/]+)", body)
        dates = re.findall(r"fomc-meeting__date[^>]*>\s*([0-9\-]+)(\*?)", body)
        for mon, (days, star) in zip(months, dates):
            last_month = mon.split("/")[-1]
            if last_month not in MONTHS:
                continue
            last_day = int(days.split("-")[-1])
            try:
                out.append((dt.date(year, MONTHS[last_month], last_day), star == "*"))
            except ValueError:
                continue
    return sorted(set(out))


def load_fomc(offline: bool = False) -> list[tuple[dt.date, bool]]:
    """[(decision date, is_SEP_meeting)] - decision date is the 2nd day."""
    fallback = [(dt.date.fromisoformat(d.rstrip("*")), d.endswith("*"))
                for d in config.FOMC_FALLBACK]
    if offline:
        return fallback
    try:
        parsed = _parse_fomc(_get(FOMC_URL).text)
        return parsed if parsed else fallback
    except Exception as e:
        _log(f"[warn] FOMC calendar: {e} - using fallback list in config.py")
        return fallback


# ---------------------------------------------------------------------------
# Positions (active KRD vs benchmark)
# ---------------------------------------------------------------------------
def load_positions(path=config.POSITIONS_FILE) -> pd.DataFrame:
    """
    CSV columns: tenor, portfolio_krd, benchmark_krd (years of duration).
    Export these from Bloomberg PORT (Key Rate Duration view) or your risk system.
    """
    df = pd.read_csv(path, comment="#")
    df["tenor"] = df["tenor"].str.strip().str.upper()
    bad = set(df["tenor"]) - set(config.KEY_RATES)
    if bad:
        raise ValueError(f"positions.csv: unknown tenors {bad}; use {config.KEY_RATES}")
    df = df.set_index("tenor").reindex(config.KEY_RATES).fillna(0.0)
    df["active_krd"] = df["portfolio_krd"] - df["benchmark_krd"]
    return df

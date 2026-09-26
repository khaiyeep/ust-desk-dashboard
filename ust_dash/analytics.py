"""
Curve, relative-value and active-risk analytics. Pure pandas/numpy - no I/O.

Units: yields in %, changes/spreads in bp, KRD in years, P&L in bp of
portfolio market value unless a column says USD.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

import config

KR = config.KEY_RATES
KR_YEARS = np.array([config.TENOR_YEARS[t] for t in KR])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def lookback_dates(idx: pd.DatetimeIndex) -> dict[str, pd.Timestamp]:
    """Last available date on/before each lookback point."""
    asof = idx[-1]
    targets = {
        "1d": idx[-2],
        "1w": asof - pd.Timedelta(days=7),
        "1m": asof - pd.DateOffset(months=1),
        "3m": asof - pd.DateOffset(months=3),
        "1y": asof - pd.DateOffset(years=1),
    }
    return {k: idx[idx <= v][-1] for k, v in targets.items() if (idx <= v).any()}


def interp_curve(row: pd.Series, years) -> np.ndarray:
    row = row.dropna()
    xs = np.array([config.TENOR_YEARS[t] for t in row.index])
    return np.interp(years, xs, row.values)


def par_mod_duration(y_pct: float, T: float) -> float:
    """Modified duration of a par bond (semi-annual coupons); bills use T/(1+yT)."""
    y = y_pct / 100
    if T < 1:
        return T / (1 + y * T)
    return (1 - (1 + y / 2) ** (-2 * T)) / y


def _shift_at_key_rates(pivots: dict[float, float]) -> np.ndarray:
    xs, ys = zip(*sorted(pivots.items()))
    return np.interp(KR_YEARS, xs, ys)


# ---------------------------------------------------------------------------
# Market
# ---------------------------------------------------------------------------
def curve_snapshot(nom: pd.DataFrame) -> pd.DataFrame:
    lb = lookback_dates(nom.index)
    cols = {"Today": nom.iloc[-1]}
    for k in ["1w", "1m", "3m", "1y"]:
        if k in lb:
            cols[f"{k} ago"] = nom.loc[lb[k]]
    return pd.DataFrame(cols)


def curve_changes(nom: pd.DataFrame) -> pd.DataFrame:
    lb = lookback_dates(nom.index)
    last = nom.iloc[-1]
    return pd.DataFrame({f"Δ{k}": (last - nom.loc[d]) * 100
                         for k, d in lb.items() if k != "1y"})


def spreads(nom: pd.DataFrame) -> pd.DataFrame:
    out = {}
    for name, legs in config.SPREADS.items():
        out[name] = sum(w * nom[t] for t, w in legs.items()) * 100
    return pd.DataFrame(out).dropna(how="all")


def level_table(df: pd.DataFrame, window: int = config.ZSCORE_WINDOW,
                scale: float = 1.0) -> pd.DataFrame:
    """Level, changes, z-score and percentile for each column (changes in bp)."""
    df = df.dropna(how="all")
    lb = lookback_dates(df.index)
    rows = {}
    for c in df.columns:
        s = df[c].dropna()
        if s.empty:
            continue
        hist = s.iloc[-window:]
        last = s.iloc[-1]
        rows[c] = {
            "Level": last,
            "Δ1d": (last - s.asof(lb["1d"])) * scale,
            "Δ1w": (last - s.asof(lb["1w"])) * scale,
            "Δ1m": (last - s.asof(lb["1m"])) * scale,
            "1y low": hist.min(),
            "1y high": hist.max(),
            "z (1y)": (last - hist.mean()) / hist.std() if hist.std() > 0 else np.nan,
            "Pctile (1y)": (hist < last).mean() * 100,
        }
    return pd.DataFrame(rows).T


def realized_vol(nom: pd.DataFrame, tenors=("2Y", "10Y", "30Y"), window: int = 21) -> pd.DataFrame:
    """Rolling realised vol of daily yield changes, bp per year."""
    d = nom[list(tenors)].diff() * 100
    return d.rolling(window).std() * np.sqrt(252)


def stock_bond_corr(spx: pd.Series, y10: pd.Series, window: int = config.CORR_WINDOW) -> pd.Series:
    """
    Rolling corr(S&P daily return, 10Y daily yield change).
    Positive = yields fall when equities fall -> Treasuries hedge the risk book.
    Negative = stocks and bonds sell off together (2022-style) -> hedge value is weak.
    """
    df = pd.concat({"spx": np.log(spx).diff(), "dy": y10.diff()}, axis=1).dropna()
    return df["spx"].rolling(window).corr(df["dy"]).dropna()


def carry_roll(nom: pd.DataFrame, horizon: float = config.CARRY_HORIZON_YRS,
               funding_tenor: str = config.FUNDING_TENOR) -> pd.DataFrame:
    """
    Carry + roll-down on the par curve, per key-rate tenor, over `horizon`.
    Carry is vs the T-bill cash alternative. Breakeven = bp the yield can rise
    over the horizon before a long position underperforms cash.
    """
    last = nom.iloc[-1].dropna()
    f = last[funding_tenor]
    rows = {}
    for t, T in zip(KR, KR_YEARS):
        y = last[t]
        D = par_mod_duration(y, T)
        carry_bp = (y - f) * horizon / D * 100
        roll_bp = (y - interp_curve(last, T - horizon)) * 100 if T > horizon else 0.0
        rows[t] = {
            "Yield %": y, "Mod dur": D, "Carry bp": carry_bp, "Roll bp": roll_bp,
            "Breakeven bp": carry_bp + roll_bp,
            "Return bp": (carry_bp + roll_bp) * D,
        }
    return pd.DataFrame(rows).T


def key_rate_changes(nom: pd.DataFrame, window: int = config.COV_WINDOW) -> pd.DataFrame:
    return (nom[KR].diff() * 100).dropna().iloc[-window:]


def pca(dchg: pd.DataFrame, n: int = 3) -> dict:
    """PCA on the covariance of daily key-rate changes (bp), config.PCA_TENORS only."""
    ten = config.PCA_TENORS
    cov = dchg[ten].cov().values
    vals, vecs = np.linalg.eigh(cov)
    order = np.argsort(vals)[::-1][:n]
    vals, vecs = vals[order], vecs[:, order]
    L = pd.DataFrame(vecs, index=ten)
    belly = [t for t in ["2Y", "3Y", "5Y", "7Y"] if t in ten]
    # Sign conventions: level up, curve steepens, belly cheapens = positive.
    checks = [L[0].sum(), L[1].iloc[-1] - L[1].iloc[0],
              L[2][belly].mean() - (L[2].iloc[0] + L[2].iloc[-1]) / 2]
    for j in range(n):
        if checks[j] < 0:
            vecs[:, j] *= -1
    names = ["Level", "Slope", "Curvature"][:n]
    sigma = np.sqrt(vals)
    return {
        "names": names,
        "tenors": ten,
        "vecs": pd.DataFrame(vecs, index=ten, columns=names),
        "loadings_bp": pd.DataFrame(vecs * sigma, index=ten, columns=names),  # bp per 1σ day
        "sigma_daily": pd.Series(sigma, index=names),
        "explained": pd.Series(vals / np.trace(cov) * 100, index=names),
    }


def pca_recent_moves(nom: pd.DataFrame, p: dict) -> pd.DataFrame:
    """How many σ each factor moved over 1w / 1m (σ scaled by √days)."""
    lb = lookback_dates(nom.index)
    ten = p["tenors"]
    last = nom[ten].iloc[-1]
    out = {}
    for k in ["1w", "1m", "3m"]:
        d = lb[k]
        n_days = max(len(nom.loc[d:]) - 1, 1)
        move = (last - nom.loc[d, ten]) * 100
        scores = move.values @ p["vecs"].values
        out[k] = scores / (p["sigma_daily"].values * np.sqrt(n_days))
    return pd.DataFrame(out, index=p["names"])


# ---------------------------------------------------------------------------
# Active book vs benchmark
# ---------------------------------------------------------------------------
def book_risk(pos: pd.DataFrame, dchg: pd.DataFrame, mv: float) -> dict:
    a = pos["active_krd"].reindex(KR).values
    cov = dchg[KR].cov().values                      # bp^2 per day
    var_d = float(a @ cov @ a)
    sd_d = np.sqrt(var_d)
    te = sd_d * np.sqrt(252)
    contrib = (a * (cov @ a)) / var_d * 100 if var_d > 0 else np.zeros_like(a)
    return {
        "port_dur": pos["portfolio_krd"].sum(),
        "bench_dur": pos["benchmark_krd"].sum(),
        "active_dur": a.sum(),
        "active_dv01_usd": a.sum() * mv / 1e4,
        "te_bp": te,
        "var95_1d_bp": 1.645 * sd_d,
        "var95_1d_usd": 1.645 * sd_d * mv / 1e4,
        "te_contrib_pct": pd.Series(contrib, index=KR),
        "active_dv01_by_tenor": pd.Series(a * mv / 1e4, index=KR),
    }


def book_factor_exposure(pos: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Active P&L (bp) for a +1σ move in each PCA factor, daily and monthly."""
    a = pos["active_krd"].reindex(p["tenors"]).values
    per_day = -(a @ p["loadings_bp"].values)
    return pd.DataFrame({"+1σ day (bp)": per_day, "+1σ month (bp)": per_day * np.sqrt(21)},
                        index=p["names"])


def scenario_table(pos: pd.DataFrame, nom: pd.DataFrame, p: dict, mv: float,
                   carry: pd.DataFrame | None = None) -> pd.DataFrame:
    a = pos["active_krd"].reindex(KR).values
    shocks: dict[str, np.ndarray] = {}
    for name, piv in config.SCENARIOS.items():
        shocks[name] = _shift_at_key_rates(piv)
    lb = lookback_dates(nom.index)
    last = nom[KR].iloc[-1]
    for k, label in [("1w", "Replay last 1w"), ("1m", "Replay last 1m"), ("3m", "Replay last 3m")]:
        shocks[label] = ((last - nom.loc[lb[k], KR]) * 100).values
    for f in p["names"]:
        shocks[f"PCA {f} +1σ (1m)"] = (p["loadings_bp"][f].reindex(KR).fillna(0).values
                                        * np.sqrt(21))
    rows = {}
    for name, dy in shocks.items():
        pnl = -float(a @ dy)
        rows[name] = {"2Y Δbp": dy[KR.index("2Y")], "5Y Δbp": dy[KR.index("5Y")],
                      "10Y Δbp": dy[KR.index("10Y")],
                      "30Y Δbp": dy[KR.index("30Y")], "Active P&L bp": pnl,
                      "Active P&L USD": pnl * mv / 1e4}
    return pd.DataFrame(rows).T


def book_carry(pos: pd.DataFrame, carry: pd.DataFrame, mv: float) -> dict:
    """Expected active return from carry + roll over the horizon, if the curve is unchanged."""
    a = pos["active_krd"].reindex(KR)
    by_tenor = a * carry["Breakeven bp"]
    return {"bp": by_tenor.sum(), "usd": by_tenor.sum() * mv / 1e4, "by_tenor": by_tenor}


# ---------------------------------------------------------------------------
# Supply
# ---------------------------------------------------------------------------
def _auction_kind(r) -> str:
    if str(r.get("inflation_index_security")) == "Yes":
        return "TIPS"
    if str(r.get("floating_rate")) == "Yes":
        return "FRN"
    return "Nominal"


def auction_tables(auc: pd.DataFrame, today: dt.date | None = None,
                   recent_days: int = 35) -> tuple[pd.DataFrame, pd.DataFrame]:
    if auc.empty:
        return pd.DataFrame(), pd.DataFrame()
    today = pd.Timestamp(today or dt.date.today())
    auc = auc.copy()
    auc["kind"] = auc.apply(_auction_kind, axis=1)
    auc["size_bn"] = auc["offering_amt"] / 1e9
    for col, src in [("indirect_pct", "indirect_bidder_accepted"),
                     ("direct_pct", "direct_bidder_accepted"),
                     ("dealer_pct", "primary_dealer_accepted")]:
        auc[col] = auc[src] / auc["comp_accepted"] * 100
    done = auc[auc["bid_to_cover_ratio"].notna()].sort_values("auction_date")
    # Compare each result with the average of the previous 6 auctions of the same line.
    g = done.groupby(["kind", "security_term"])
    done["btc_vs_avg6"] = done["bid_to_cover_ratio"] - g["bid_to_cover_ratio"].transform(
        lambda s: s.shift(1).rolling(6, min_periods=3).mean())
    done["dealer_vs_avg6"] = done["dealer_pct"] - g["dealer_pct"].transform(
        lambda s: s.shift(1).rolling(6, min_periods=3).mean())

    upcoming = auc[(auc["auction_date"] >= today.normalize()) &
                   auc["bid_to_cover_ratio"].isna()].sort_values("auction_date")
    upcoming = upcoming[["auction_date", "security_term", "kind", "reopening", "size_bn",
                         "issue_date", "cusip"]]
    recent = done[done["auction_date"] >= today - pd.Timedelta(days=recent_days)]
    recent = recent.sort_values("auction_date", ascending=False)[
        ["auction_date", "security_term", "kind", "reopening", "size_bn", "high_yield",
         "high_discnt_margin", "bid_to_cover_ratio", "btc_vs_avg6", "indirect_pct",
         "direct_pct", "dealer_pct", "dealer_vs_avg6"]]
    return upcoming, recent


# ---------------------------------------------------------------------------
# Auto commentary
# ---------------------------------------------------------------------------
def commentary(nom, chg, sp_tab, cr, fred, risk, pcam, stock_bond) -> list[str]:
    def bp(x):
        return f"{x:+.1f}bp"
    lines = []
    c = chg
    lines.append(
        f"Curve on the week: 2Y {bp(c.loc['2Y', 'Δ1w'])}, 10Y {bp(c.loc['10Y', 'Δ1w'])}, "
        f"30Y {bp(c.loc['30Y', 'Δ1w'])}. 2s10s at {sp_tab.loc['2s10s', 'Level']:.0f}bp "
        f"({bp(sp_tab.loc['2s10s', 'Δ1w'])} w/w, 1y z {sp_tab.loc['2s10s', 'z (1y)']:+.1f})."
    )
    dom = pcam["1w"].abs().idxmax()
    lines.append(
        f"PCA: last week's most unusual factor move was {dom.lower()} ({pcam.loc[dom, '1w']:+.1f}σ); "
        f"1m moves - level {pcam.loc['Level', '1m']:+.1f}σ, slope {pcam.loc['Slope', '1m']:+.1f}σ, "
        f"curvature {pcam.loc['Curvature', '1m']:+.1f}σ."
    )
    best = cr["Breakeven bp"].drop(["3M"]).idxmax()
    lines.append(
        f"Best 3m carry+roll cushion on the curve: {best} ({cr.loc[best, 'Breakeven bp']:.1f}bp of "
        f"yield rise to breakeven vs bills)."
    )
    effr = fred.get("EFFR")
    if effr is not None and not effr.empty:
        gap = (nom["1Y"].iloc[-1] - effr.iloc[-1]) * 100
        lean = "hikes" if gap > 10 else "cuts" if gap < -10 else "roughly no change"
        lines.append(f"1Y bill − EFFR {gap:+.0f}bp: bills lean toward {lean} over 12m "
                     f"(crude - includes bill/OIS basis; check WIRP).")
    if not stock_bond.empty:
        sb = stock_bond.iloc[-1]
        view = "Treasuries are hedging equities" if sb > 0.2 else \
            "stocks and bonds are moving together - weak hedge" if sb < -0.2 else "hedge relationship is weak/unstable"
        lines.append(f"Stock-bond correlation (3m) {sb:+.2f}: {view}.")
    lines.append(
        f"Book: active duration {risk['active_dur']:+.2f}y, ex-ante TE {risk['te_bp']:.0f}bp "
        f"({risk['te_bp'] / config.TE_BUDGET_BP * 100:.0f}% of {config.TE_BUDGET_BP}bp budget)."
    )
    return lines

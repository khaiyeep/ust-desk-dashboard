#!/usr/bin/env python3
"""
Refresh the UST desk dashboard.

    python refresh.py              # pull latest data, build, open in browser
    python refresh.py --offline    # rebuild from cached data only
    python refresh.py --no-open    # for scheduled runs
"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from ust_dash import analytics as A, report, sources as S  # noqa: E402


def build(offline: bool = False, positions: Path = config.POSITIONS_FILE) -> dict:
    print("Loading Treasury curves...")
    nom = S.load_treasury_curve("nominal", offline=offline)
    print(f"  nominal: {len(nom)} days, last {nom.index[-1]:%Y-%m-%d}")
    print("Loading FRED series...")
    fred = S.load_fred(offline=offline)
    print("Loading auctions and FOMC calendar...")
    auc = S.load_auctions(offline=offline)
    fomc = S.load_fomc(offline=offline)
    pos = S.load_positions(positions)
    mv = config.PORTFOLIO_MV_USD
    lb = A.lookback_dates(nom.index)
    sp = A.spreads(nom)
    sp_tab = A.level_table(sp, scale=1.0)
    dchg = A.key_rate_changes(nom)
    p = A.pca(dchg)
    pcam = A.pca_recent_moves(nom, p)
    cr = A.carry_roll(nom)
    risk = A.book_risk(pos, dchg, mv)
    stock_bond = A.stock_bond_corr(fred["SP500"], nom["10Y"]) if not fred["SP500"].empty else fred["SP500"]
    upcoming, recent = A.auction_tables(auc)
    ctx = dict(
        nom=nom, fred=fred, lb=lb, positions=pos,
        snapshot=A.curve_snapshot(nom), changes=A.curve_changes(nom),
        spreads=sp, spread_table=sp_tab, pca=p, pca_moves=pcam, carry=cr, risk=risk,
        factor_exposure=A.book_factor_exposure(pos, p),
        scenarios=A.scenario_table(pos, nom, p, mv),
        book_carry=A.book_carry(pos, cr, mv),
        stock_bond=stock_bond, rvol=A.realized_vol(nom),
        upcoming=upcoming, recent=recent, fomc=fomc, log=S.log_lines,
    )
    ctx["commentary"] = A.commentary(nom, ctx["changes"], sp_tab, cr, fred, risk, pcam, stock_bond)
    return ctx


def export_excel(ctx: dict, path: Path) -> None:
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("  (openpyxl not installed - skipping Excel snapshot)")
        return
    import pandas as pd
    with pd.ExcelWriter(path) as xw:
        pd.concat([ctx["snapshot"], ctx["changes"]], axis=1).to_excel(xw, sheet_name="Curve")
        ctx["spread_table"].to_excel(xw, sheet_name="Spreads")
        ctx["carry"].to_excel(xw, sheet_name="CarryRoll")
        ctx["scenarios"].to_excel(xw, sheet_name="Scenarios")
        ctx["positions"].assign(te_contrib_pct=ctx["risk"]["te_contrib_pct"]).to_excel(xw, sheet_name="Book")
        ctx["pca"]["loadings_bp"].to_excel(xw, sheet_name="PCA")
        ctx["recent"].to_excel(xw, sheet_name="Auctions", index=False)
        ctx["nom"].to_excel(xw, sheet_name="CurveHistory")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="use cached data only")
    ap.add_argument("--no-open", action="store_true", help="don't open the browser")
    ap.add_argument("--positions", type=Path, default=config.POSITIONS_FILE)
    ap.add_argument("--no-excel", action="store_true", help="skip the Excel snapshot")
    args = ap.parse_args()

    ctx = build(offline=args.offline, positions=args.positions)
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = ctx["nom"].index[-1].strftime("%Y-%m-%d")
    out = config.OUTPUT_DIR / f"ust_dashboard_{stamp}.html"
    out.write_text(report.render(ctx), encoding="utf-8")
    latest = config.OUTPUT_DIR / "latest.html"
    shutil.copyfile(out, latest)
    print(f"Dashboard: {out}")
    if not args.no_excel:
        xl = config.OUTPUT_DIR / f"ust_snapshot_{stamp}.xlsx"
        export_excel(ctx, xl)
        if xl.exists():
            print(f"Excel:     {xl}")
    print("\nMorning brief:")
    for line in ctx["commentary"]:
        print(f"  - {line}")
    if not args.no_open:
        webbrowser.open(latest.resolve().as_uri())


if __name__ == "__main__":
    main()

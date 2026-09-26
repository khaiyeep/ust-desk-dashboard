#!/usr/bin/env python3
"""
Build site/data.json for the web dashboard.

Runs on a schedule in GitHub Actions (see .github/workflows/refresh.yml), so
nobody has to run Python by hand. The page itself re-fetches the sources that
allow browser access (Treasury curves, auctions, NY Fed rates) whenever it
opens; this file supplies history plus the FRED-only series.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from ust_dash import sources as S  # noqa: E402

SITE = config.ROOT / "site"

# Series the browser can't fetch itself (FRED has no CORS). TIPS real yields
# and breakevens come from the Treasury real curve instead.
FRED_FOR_SITE = ["EFFR", "SOFR", "IORB", "THREEFYTP10", "VIXCLS", "SP500",
                 "DTWEXBGS", "DEXMAUS", "WRESBAL", "WTREGEN", "RRPONTSYD"]


def _num(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), 4)


def frame_json(df):
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in df.index],
        "tenors": list(df.columns),
        "values": [[_num(v) for v in row] for row in df.itertuples(index=False)],
    }


def series_json(s):
    s = s.dropna()
    return {"dates": [d.strftime("%Y-%m-%d") for d in s.index], "values": [_num(v) for v in s.values]}


def _auctions_json(auc) -> list[dict]:
    keep = ["cusip", "security_term", "auction_date", "issue_date", "reopening", "offering_amt",
            "high_yield", "high_discnt_margin", "bid_to_cover_ratio", "comp_accepted",
            "indirect_bidder_accepted", "direct_bidder_accepted", "primary_dealer_accepted",
            "inflation_index_security", "floating_rate"]
    out = []
    for r in auc[keep].to_dict("records"):
        row = {}
        for k, v in r.items():
            if hasattr(v, "strftime"):
                row[k] = v.strftime("%Y-%m-%d")
            elif isinstance(v, float):
                row[k] = _num(v)
            else:
                row[k] = None if v is None or str(v) in ("<NA>", "nan") else v
        out.append(row)
    return out


def main() -> None:
    out = SITE / "data.json"
    # If a source is down, keep yesterday's section rather than failing the whole build.
    prev = json.loads(out.read_text()) if out.exists() else {}
    data = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")}
    steps = {
        "nominal": lambda: frame_json(S.load_treasury_curve("nominal")),
        "real": lambda: frame_json(S.load_treasury_curve("real")),
        "fred": lambda: {sid: series_json(s) for sid, s in S.load_fred(FRED_FOR_SITE).items()},
        "auctions": lambda: _auctions_json(S.load_auctions()),
        "fomc": lambda: [[d.isoformat(), sep] for d, sep in S.load_fomc()],
    }
    for key, fn in steps.items():
        try:
            data[key] = fn()
        except Exception as e:  # noqa: BLE001
            if key not in prev:
                raise
            S.log_lines.append(f"[warn] {key}: {e} - kept previous build's data")
            data[key] = prev[key]
    # FRED series that failed individually come back empty - fall back to the previous copy.
    for sid, s in data["fred"].items():
        if not s["dates"] and sid in prev.get("fred", {}):
            data["fred"][sid] = prev["fred"][sid]
    if not data["auctions"] and prev.get("auctions"):
        data["auctions"] = prev["auctions"]
    data["warnings"] = S.log_lines
    SITE.mkdir(exist_ok=True)
    out.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size / 1e3:,.0f} kB), curve to {data['nominal']['dates'][-1]}")
    for w in S.log_lines:
        print(w)


if __name__ == "__main__":
    main()

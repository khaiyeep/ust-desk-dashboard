"""
Renders the dashboard as one self-contained HTML file (plotly.js inlined, so it
opens on a locked-down machine with no internet).
"""
from __future__ import annotations

import datetime as dt
import html

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.offline import get_plotlyjs
from plotly.subplots import make_subplots

import config

# Palette: validated categorical slots 1-3, neutral gray for context series,
# blue <-> red diverging pair for signed quantities (long/short, P&L).
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"
GRAY = "#898781"
POS, NEG = "#2a78d6", "#e34948"
INK, INK2, GRID, AXIS = "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'
PLOT_CFG = {"displaylogo": False, "responsive": True,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"]}


# ---------------------------------------------------------------------------
# Plot helpers
# ---------------------------------------------------------------------------
def _layout(fig: go.Figure, height=320, legend=True, hover="x unified", title=None):
    fig.update_layout(
        height=height, margin=dict(l=48, r=16, t=36 if title else 12, b=36),
        title=dict(text=title, x=0, font=dict(size=13)) if title else None,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=12, color=INK),
        hovermode=hover, showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, bgcolor="rgba(0,0,0,0)"),
        barcornerradius=3, bargap=0.3, bargroupgap=0.08,
        hoverlabel=dict(font=dict(family=FONT)),
    )
    fig.update_xaxes(showgrid=False, linecolor=AXIS, ticks="outside", tickcolor=AXIS,
                     zeroline=False)
    fig.update_yaxes(gridcolor=GRID, linecolor=AXIS, zeroline=False, ticks="")
    return fig


def _div(fig: go.Figure) -> str:
    return pio.to_html(fig, full_html=False, include_plotlyjs=False, config=PLOT_CFG)


def _line(series: dict[str, pd.Series], colors, height=300, yfmt=".2f", unit="",
          zero=False, title=None) -> str:
    fig = go.Figure()
    for (name, s), c in zip(series.items(), colors):
        s = s.dropna()
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=name, mode="lines",
                                 line=dict(color=c, width=2),
                                 hovertemplate=f"%{{y:{yfmt}}}{unit}<extra>{name}</extra>"))
    _layout(fig, height=height, legend=len(series) > 1, title=title)
    if zero:
        fig.add_hline(y=0, line=dict(color=AXIS, width=1))
    fig.update_yaxes(tickformat=yfmt.replace("f", "f") if "f" in yfmt else None)
    return _div(fig)


def _signed_bars(s: pd.Series, height=300, fmt=".2f", unit="", horizontal=False,
                 title=None) -> str:
    colors = [POS if v >= 0 else NEG for v in s.values]
    # Label every non-trivial bar; zero buckets stay unlabeled to cut noise.
    text = [f"{v:+{fmt}}{unit}" if abs(v) >= 0.5 * 10 ** -int(fmt[-2]) else "" for v in s.values]
    if horizontal:
        bar = go.Bar(y=s.index, x=s.values, orientation="h", marker_color=colors,
                     text=text, textposition="outside", cliponaxis=False,
                     hovertemplate=f"%{{y}}: %{{x:+{fmt}}}{unit}<extra></extra>")
    else:
        bar = go.Bar(x=s.index, y=s.values, marker_color=colors, text=text,
                     textposition="outside", cliponaxis=False,
                     hovertemplate=f"%{{x}}: %{{y:+{fmt}}}{unit}<extra></extra>")
    fig = _layout(go.Figure(bar), height=height, legend=False, hover="closest", title=title)
    if horizontal:
        fig.add_vline(x=0, line=dict(color=AXIS, width=1))
        fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
        fig.update_xaxes(showgrid=True, gridcolor=GRID, ticksuffix=unit)
        fig.update_layout(margin=dict(l=190, r=60))
    else:
        fig.add_hline(y=0, line=dict(color=AXIS, width=1))
    return _div(fig)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
def chart_curve(snap: pd.DataFrame) -> str:
    fig = go.Figure()
    styles = {"Today": (S1, 2.5), "1w ago": (S2, 2), "1m ago": (S3, 2), "1y ago": (GRAY, 2)}
    for col, (c, w) in styles.items():
        if col not in snap:
            continue
        s = snap[col].dropna()
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=col, mode="lines+markers",
                                 line=dict(color=c, width=w), marker=dict(size=7),
                                 hovertemplate="%{y:.2f}%<extra>" + col + "</extra>"))
    _layout(fig, height=340)
    fig.update_yaxes(ticksuffix="%")
    return _div(fig)


def chart_curve_changes(chg: pd.DataFrame) -> str:
    fig = go.Figure()
    for col, c in zip(["Δ1d", "Δ1w", "Δ1m"], [S1, S2, S3]):
        fig.add_trace(go.Bar(x=chg.index, y=chg[col], name=col, marker_color=c,
                             hovertemplate="%{y:+.1f}bp<extra>" + col + "</extra>"))
    _layout(fig, height=340)
    fig.add_hline(y=0, line=dict(color=AXIS, width=1))
    fig.update_yaxes(ticksuffix="bp")
    return _div(fig)


def chart_spreads(sp: pd.DataFrame, window: int) -> str:
    cols = list(sp.columns)
    rows = int(np.ceil(len(cols) / 3))
    fig = make_subplots(rows=rows, cols=3, subplot_titles=cols, vertical_spacing=0.16,
                        horizontal_spacing=0.07)
    for i, c in enumerate(cols):
        r, k = i // 3 + 1, i % 3 + 1
        s = sp[c].dropna()
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=c, mode="lines",
                                 line=dict(color=S1, width=1.8),
                                 hovertemplate="%{y:.1f}bp<extra>" + c + "</extra>"),
                      row=r, col=k)
        h = s.iloc[-window:]
        m, sd = h.mean(), h.std()
        # 1y mean ± 1σ band over the z-score window
        fig.add_shape(type="rect", x0=h.index[0], x1=h.index[-1], y0=m - sd, y1=m + sd,
                      fillcolor="rgba(137,135,129,0.14)", line_width=0, layer="below",
                      row=r, col=k)
        fig.add_shape(type="line", x0=h.index[0], x1=h.index[-1], y0=m, y1=m,
                      line=dict(color=GRAY, width=1), row=r, col=k)
    _layout(fig, height=260 * rows, legend=False)
    fig.update_yaxes(ticksuffix="bp")
    for a in fig.layout.annotations:
        a.font = dict(size=12)
    return _div(fig)


def chart_pca(p: dict) -> str:
    fig = go.Figure()
    L = p["loadings_bp"]
    for f, c in zip(p["names"], [S1, S2, S3]):
        fig.add_trace(go.Scatter(x=L.index, y=L[f], name=f"{f} ({p['explained'][f]:.0f}%)",
                                 mode="lines+markers", line=dict(color=c, width=2),
                                 marker=dict(size=8),
                                 hovertemplate="%{y:+.2f}bp<extra>" + f + "</extra>"))
    _layout(fig, height=320)
    fig.add_hline(y=0, line=dict(color=AXIS, width=1))
    fig.update_yaxes(ticksuffix="bp", title_text="bp per 1σ daily move")
    return _div(fig)


def chart_small_multiples(series: dict[str, pd.Series], unit="", fmt=".2f", height=250) -> str:
    n = len(series)
    fig = make_subplots(rows=1, cols=n, subplot_titles=list(series), horizontal_spacing=0.08)
    for i, (name, s) in enumerate(series.items(), start=1):
        s = s.dropna()
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=name, mode="lines",
                                 line=dict(color=S1, width=1.8),
                                 hovertemplate=f"%{{y:{fmt}}}{unit}<extra>{name}</extra>"),
                      row=1, col=i)
    _layout(fig, height=height, legend=False)
    for a in fig.layout.annotations:
        a.font = dict(size=12)
    return _div(fig)


# ---------------------------------------------------------------------------
# HTML pieces
# ---------------------------------------------------------------------------
def _fmt(v, f):
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA or pd.isna(v):
        return "–"
    if callable(f):
        return f(v)
    return format(v, f)


def table(df: pd.DataFrame, fmts: dict | None = None, default=".2f", index_name="") -> str:
    fmts = fmts or {}
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    body = []
    for idx, row in df.iterrows():
        cells = []
        for c in df.columns:
            v = row[c]
            f = fmts.get(c, default)
            if isinstance(v, (pd.Timestamp, dt.date)):
                txt = v.strftime("%a %d %b")
            elif isinstance(v, str):
                txt = html.escape(v)
            else:
                txt = _fmt(v, f)
            strong = c.startswith("z") and isinstance(v, float) and abs(v) >= 2
            cells.append(f"<td>{'<b>' + txt + '</b>' if strong else txt}</td>")
        body.append(f"<tr><th scope='row'>{html.escape(str(idx))}</th>{''.join(cells)}</tr>")
    return (f"<div class='tbl'><table><thead><tr><th>{html.escape(index_name)}</th>{head}</tr>"
            f"</thead><tbody>{''.join(body)}</tbody></table></div>")


def tile(label, value, sub="", status=None) -> str:
    st = f"<div class='status {status[0]}'>{status[1]}</div>" if status else ""
    return (f"<div class='tile'><div class='tl'>{html.escape(label)}</div>"
            f"<div class='tv'>{value}</div><div class='ts'>{sub}</div>{st}</div>")


def _chg(x):
    return "–" if pd.isna(x) else f"{x:+.1f}"


def yield_tile(label, s: pd.Series, lb) -> str:
    s = s.dropna()
    last = s.iloc[-1]
    d = {k: (last - s.asof(lb[k])) * 100 for k in ["1d", "1w", "1m"]}
    return tile(label, f"{last:.2f}%",
                f"1d {_chg(d['1d'])} · 1w {_chg(d['1w'])} · 1m {_chg(d['1m'])} bp")


def spread_tile(label, s: pd.Series, lb) -> str:
    s = s.dropna()
    last = s.iloc[-1]
    d = {k: last - s.asof(lb[k]) for k in ["1d", "1w", "1m"]}
    return tile(label, f"{last:.0f}bp",
                f"1d {_chg(d['1d'])} · 1w {_chg(d['1w'])} · 1m {_chg(d['1m'])} bp")


def section(sid, title, body, note="") -> str:
    n = f"<p class='note'>{note}</p>" if note else ""
    return f"<section id='{sid}'><h2>{title}</h2>{n}{body}</section>"


def card(inner, title="", wide=False, note="") -> str:
    t = f"<h3>{title}</h3>" if title else ""
    n = f"<p class='note'>{note}</p>" if note else ""
    return f"<div class='card{' wide' if wide else ''}'>{t}{inner}{n}</div>"


CSS = """
:root{--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--ring:rgba(11,11,11,.10);--good:#0ca30c;--warn:#fab219;--crit:#d03b3b;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--page:#0d0d0d;--surface:#1a1a19;
--ink:#fff;--ink2:#c3c2b7;--grid:#2c2c2a;--ring:rgba(255,255,255,.10);}}
:root[data-theme="dark"]{--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--grid:#2c2c2a;
--ring:rgba(255,255,255,.10);}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--page);border-bottom:1px solid var(--grid);
padding:10px 20px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
header h1{font-size:16px;margin:0;font-weight:650}
header .asof{color:var(--ink2);font-size:13px}
nav{display:flex;gap:12px;flex-wrap:wrap;margin-left:auto}
nav a{color:var(--ink2);text-decoration:none;font-size:13px}nav a:hover{color:var(--ink)}
button.theme{background:none;border:1px solid var(--ring);color:var(--ink2);border-radius:6px;padding:3px 8px;cursor:pointer}
main{max-width:1400px;margin:0 auto;padding:8px 20px 60px}
section{margin-top:28px;scroll-margin-top:64px}
h2{font-size:18px;margin:0 0 4px}h3{font-size:14px;margin:0 0 8px;font-weight:600}
.note{color:var(--ink2);font-size:12.5px;margin:2px 0 10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(460px,1fr));gap:14px}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:14px;min-width:0}
.card.wide{grid-column:1/-1}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px;margin:10px 0 14px}
.tile{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:10px 12px}
.tl{color:var(--ink2);font-size:12px}.tv{font-size:22px;font-weight:600;margin:2px 0}
.ts{color:var(--ink2);font-size:11.5px;font-variant-numeric:tabular-nums}
.status{font-size:12px;margin-top:4px;color:var(--ink2)}
.status:before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:0}
.status.good:before{background:var(--good)}.status.warn:before{background:var(--warn)}.status.crit:before{background:var(--crit)}
ul.brief{margin:6px 0 0;padding-left:18px}ul.brief li{margin:4px 0}
.tbl{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:12.5px}
th,td{padding:5px 8px;text-align:right;border-bottom:1px solid var(--grid);white-space:nowrap}
thead th{color:var(--ink2);font-weight:600}
tbody th{text-align:left;font-weight:500}
thead th:first-child{text-align:left}
footer{color:var(--ink2);font-size:12px;margin-top:40px}
@media (max-width:640px){main{padding:8px 16px 40px}.grid{grid-template-columns:1fr}header{padding:8px 16px;position:static}}
"""

THEME_JS = """
function isDark(){const t=document.documentElement.dataset.theme;
 if(t) return t==='dark'; return window.matchMedia('(prefers-color-scheme: dark)').matches;}
function paint(){const d=isDark();
 const ink=d?'#ffffff':'#0b0b0b', grid=d?'#2c2c2a':'#e1e0d9', axis=d?'#383835':'#c3c2b7';
 document.querySelectorAll('.js-plotly-plot').forEach(gd=>{
  const u={'font.color':ink,'hoverlabel.bgcolor':d?'#1a1a19':'#fcfcfb','hoverlabel.font.color':ink};
  Object.keys(gd.layout).forEach(k=>{ if(/^[xy]axis\\d*$/.test(k)){
    u[k+'.gridcolor']=grid; u[k+'.linecolor']=axis; u[k+'.tickcolor']=axis;}});
  Plotly.relayout(gd,u);});}
function toggleTheme(){document.documentElement.dataset.theme=isDark()?'light':'dark';paint();}
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change',paint);
// Plots render while the page is still parsing, before the grid settles -
// resize them all once layout is final.
window.addEventListener('load',()=>{document.querySelectorAll('.js-plotly-plot')
  .forEach(gd=>Plotly.Plots.resize(gd)); paint();});
"""


def render(ctx: dict) -> str:
    nom, fred, lb = ctx["nom"], ctx["fred"], ctx["lb"]
    sp, sp_tab = ctx["spreads"], ctx["spread_table"]
    risk, pos = ctx["risk"], ctx["positions"]
    asof = nom.index[-1]

    # --- Morning brief -----------------------------------------------------
    tiles = [yield_tile(t, nom[t], lb) for t in ["3M", "2Y", "5Y", "10Y", "30Y"]]
    tiles += [spread_tile(c, sp[c], lb) for c in ["2s10s", "5s30s", "2s5s10s"]]
    for sid, lab in [("DFII10", "10Y real"), ("T10YIE", "10Y breakeven"),
                     ("EFFR", "EFFR"), ("SOFR", "SOFR")]:
        s = fred.get(sid)
        if s is not None and not s.empty:
            tiles.append(yield_tile(lab, s, lb))
    tp = fred.get("THREEFYTP10")
    if tp is not None and not tp.empty:
        tiles.append(tile("10Y term premium (KW)", f"{tp.iloc[-1]:.2f}%",
                          f"as of {tp.index[-1]:%d %b} · 1m {_chg((tp.iloc[-1] - tp.asof(lb['1m'])) * 100)} bp"))
    for sid, lab, f in [("VIXCLS", "VIX", ".1f"), ("DEXMAUS", "USD/MYR", ".4f")]:
        s = fred.get(sid)
        if s is not None and not s.empty:
            tiles.append(tile(lab, format(s.iloc[-1], f), f"as of {s.index[-1]:%d %b}"))
    brief = "".join(f"<li>{html.escape(l)}</li>" for l in ctx["commentary"])
    s_brief = section("brief", "Morning brief",
                      f"<div class='tiles'>{''.join(tiles)}</div>"
                      + card(f"<ul class='brief'>{brief}</ul>", "Auto-generated talking points",
                             note="Starting points for the morning call - sanity-check against news flow."))

    # --- Curve -------------------------------------------------------------
    snap, chg = ctx["snapshot"], ctx["changes"]
    lvl_tab = pd.concat([snap, chg], axis=1)
    s_curve = section("curve", "Curve", "<div class='grid'>"
                      + card(chart_curve(snap), "Par curve: today vs history")
                      + card(chart_curve_changes(chg), "Changes by tenor")
                      + card(table(lvl_tab, {c: "+.1f" for c in chg.columns}, index_name="Tenor"),
                             "Levels (%) and changes (bp)", wide=True)
                      + "</div>")

    # --- Spreads -----------------------------------------------------------
    s_sp = section(
        "rv", "Curve spreads & flies",
        card(chart_spreads(sp.iloc[-config.ZSCORE_WINDOW * 2:], config.ZSCORE_WINDOW), wide=True,
             note="Shaded band = trailing 1y mean ± 1σ. Flies = 2×belly − wings (positive = belly cheap).")
        + "<div style='height:14px'></div>"
        + card(table(sp_tab, {"Level": ".1f", "Δ1d": "+.1f", "Δ1w": "+.1f", "Δ1m": "+.1f",
                              "1y low": ".1f", "1y high": ".1f", "z (1y)": "+.2f",
                              "Pctile (1y)": ".0f"}, index_name="Spread (bp)"),
               "Relative-value screen", note="Bold = |z| ≥ 2. Mean reversion is a tendency, not a law - check the macro driver first."))

    # --- Policy & inflation -------------------------------------------------
    pol = {"EFFR": fred.get("EFFR"), "3M bill": nom["3M"], "2Y": nom["2Y"]}
    pol = {k: v.iloc[-500:] for k, v in pol.items() if v is not None and not v.empty}
    real = {k: fred[s].iloc[-500:] for k, s in [("5Y real", "DFII5"), ("10Y real", "DFII10"),
                                                ("30Y real", "DFII30")] if not fred[s].empty}
    be = {k: fred[s].iloc[-500:] for k, s in [("5Y BE", "T5YIE"), ("10Y BE", "T10YIE"),
                                              ("5Y5Y fwd BE", "T5YIFR")] if not fred[s].empty}
    s_pol = section("policy", "Policy, inflation & term premium", "<div class='grid'>"
                    + card(_line(pol, [S1, S2, S3], unit="%"), "Policy rate vs front end",
                           note="2Y trading above EFFR = market pricing hikes (or a term premium); below = cuts. Use WIRP / SOFR futures for the precise path.")
                    + card(_line({"10Y term premium": fred["THREEFYTP10"].iloc[-750:]}, [S1], unit="%", zero=True),
                           "10Y term premium (Kim-Wright, Fed Board)",
                           note="Rising term premium = investors demanding more to hold duration (supply, fiscal, inflation uncertainty).")
                    + card(_line(real, [S1, S2, S3], unit="%"), "TIPS real yields")
                    + card(_line(be, [S1, S2, S3], unit="%"), "Breakeven inflation")
                    + "</div>")

    # --- Active book ---------------------------------------------------------
    mv = config.PORTFOLIO_MV_USD
    te_pct = risk["te_bp"] / config.TE_BUDGET_BP * 100
    te_status = ("good", "Within budget") if te_pct < 75 else \
        ("warn", "Approaching budget") if te_pct <= 100 else ("crit", "Over budget")
    dur_pct = abs(risk["active_dur"]) / config.ACTIVE_DURATION_LIMIT_YRS * 100
    dur_status = ("good", f"{dur_pct:.0f}% of ±{config.ACTIVE_DURATION_LIMIT_YRS}y limit") if dur_pct < 75 else \
        ("warn", f"{dur_pct:.0f}% of limit") if dur_pct <= 100 else ("crit", f"{dur_pct:.0f}% of limit - breach")
    bc = ctx["book_carry"]
    book_tiles = [
        tile("Portfolio duration", f"{risk['port_dur']:.2f}y", f"Benchmark {risk['bench_dur']:.2f}y"),
        tile("Active duration", f"{risk['active_dur']:+.2f}y",
             f"Active DV01 {'+' if risk['active_dv01_usd'] >= 0 else '−'}${abs(risk['active_dv01_usd']) / 1e3:,.0f}k per bp",
             dur_status),
        tile("Ex-ante tracking error", f"{risk['te_bp']:.0f}bp/yr",
             f"Budget {config.TE_BUDGET_BP}bp · {te_pct:.0f}% used · rates only", te_status),
        tile("1-day VaR 95% (active)", f"{risk['var95_1d_bp']:.1f}bp",
             f"≈ ${risk['var95_1d_usd'] / 1e6:,.1f}mn on ${mv / 1e9:,.1f}bn"),
        tile(f"Carry + roll ({int(config.CARRY_HORIZON_YRS * 12)}m, curve unchanged)",
             f"{bc['bp']:+.1f}bp", f"≈ {'+' if bc['usd'] >= 0 else '−'}${abs(bc['usd']) / 1e6:,.2f}mn active return"),
    ]
    fx = ctx["factor_exposure"]
    kr_tab = pos[["portfolio_krd", "benchmark_krd", "active_krd"]].copy()
    kr_tab["active DV01 $k"] = risk["active_dv01_by_tenor"] / 1e3
    kr_tab["TE contrib %"] = risk["te_contrib_pct"]
    kr_tab["carry+roll bp"] = bc["by_tenor"]
    kr_tab.columns = ["Portfolio KRD", "Benchmark KRD", "Active KRD", "Active DV01 $k",
                      "TE contrib %", "Carry+roll bp"]
    scen = ctx["scenarios"]
    s_book = section(
        "book", "Active book vs benchmark",
        f"<div class='tiles'>{''.join(book_tiles)}</div><div class='grid'>"
        + card(_signed_bars(pos["active_krd"], fmt=".2f", unit="y"),
               "Active key-rate duration (overweight + / underweight −)")
        + card(_signed_bars(risk["te_contrib_pct"], fmt=".0f", unit="%"),
               "Contribution to tracking error",
               note="Where the risk actually sits. Negative = that bucket diversifies the rest of the book.")
        + card(_signed_bars(scen["Active P&L bp"], fmt=".1f", unit="bp", horizontal=True,
                            height=40 + 26 * len(scen)),
               "Scenario P&L vs benchmark (bp of portfolio)", wide=True)
        + card(table(scen, {"2Y Δbp": "+.1f", "5Y Δbp": "+.1f", "10Y Δbp": "+.1f", "30Y Δbp": "+.1f",
                            "Active P&L bp": "+.2f",
                            "Active P&L USD": lambda v: f"{v / 1e6:+,.2f}mn"}, index_name="Scenario"),
               "Scenario detail", wide=True)
        + card(table(kr_tab, {"Active DV01 $k": "+,.0f", "TE contrib %": "+.0f",
                              "Carry+roll bp": "+.2f", "Active KRD": "+.2f"}, index_name="Key rate")
               + "<div style='height:10px'></div>"
               + table(fx, {c: "+.2f" for c in fx.columns}, index_name="Factor"),
               "Key-rate detail & PCA factor exposure", wide=True,
               note="Factor rows: active P&L for a +1σ level (yields up), slope (steeper) or curvature (belly cheaper) move. PCA uses 1Y-30Y, so bill KRDs are excluded.")
        + "</div>",
        note=f"From positions.csv. KRDs in years; P&L in bp of the ${mv / 1e9:,.1f}bn portfolio. "
             f"TE/VaR use {config.COV_WINDOW}d historical covariance of par yields - curve risk only "
             "(no spread, selection or TIPS risk).")

    # --- Carry & PCA -----------------------------------------------------------
    cr = ctx["carry"]
    pcam = ctx["pca_moves"]
    s_cr = section(
        "carry", "Carry, roll-down & curve factors", "<div class='grid'>"
        + card(_signed_bars(cr["Breakeven bp"].drop("3M"), fmt=".1f", unit="bp"),
               f"{int(config.CARRY_HORIZON_YRS * 12)}m carry + roll breakeven by tenor",
               note=f"bp the yield can rise over {int(config.CARRY_HORIZON_YRS * 12)}m before a long underperforms {config.FUNDING_TENOR} bills. Par-curve approximation.")
        + card(table(cr, {"Yield %": ".2f", "Mod dur": ".2f", "Carry bp": "+.1f", "Roll bp": "+.1f",
                          "Breakeven bp": "+.1f", "Return bp": "+.0f"}, index_name="Tenor"),
               "Carry & roll table")
        + card(chart_pca(ctx["pca"]), "PCA loadings (1y of daily changes)",
               note="Shape of a typical 1σ day for each factor. Use these for hedge ratios and to see what your book is really exposed to.")
        + card(table(pcam, {c: "+.2f" for c in pcam.columns}, index_name="Factor move (σ)"),
               "Recent factor moves", note="Cumulative move over the window divided by σ·√days. |σ| > 2 = unusual.")
        + "</div>")

    # --- Cross-asset ------------------------------------------------------------
    sb = ctx["stock_bond"]
    rv = ctx["rvol"]
    liq = {}
    for sid, lab, div in [("WRESBAL", "Bank reserves", 1e3), ("WTREGEN", "TGA", 1e3),
                          ("RRPONTSYD", "ON RRP", 1)]:
        s = fred.get(sid)
        if s is not None and not s.empty:
            liq[f"{lab} ($bn)"] = (s / div).iloc[-800:]
    fxs = {k: fred[s].iloc[-750:] for k, s in [("USD/MYR", "DEXMAUS"), ("Broad USD index", "DTWEXBGS"),
                                               ("VIX", "VIXCLS")] if not fred[s].empty}
    s_x = section(
        "cross", "Cross-asset, vol & liquidity", "<div class='grid'>"
        + card(_line({"Corr(S&P return, 10Y Δy), 3m rolling": sb.iloc[-750:]}, [S1], zero=True),
               "Stock-bond correlation",
               note="The number that matters most under TPA: positive = Treasuries hedge the equity/credit risk elsewhere in the reserves; negative = they don't.")
        + card(_line({c: rv[c].dropna().iloc[-750:] for c in rv.columns}, [S1, S2, S3], yfmt=".0f", unit="bp"),
               "Realised yield vol (1m, annualised)",
               note="Proxy for MOVE. Size positions in vol-adjusted terms - the same DV01 is more risk when vol is high.")
        + card(chart_small_multiples(liq, fmt=",.0f"), "Liquidity plumbing ($bn)", wide=True,
               note="Reserves scarce + TGA rebuild = funding pressure (front end, swap spreads). Weekly data.")
        + card(chart_small_multiples(fxs), "FX & risk sentiment", wide=True)
        + "</div>")

    # --- Supply & calendar ---------------------------------------------------------
    up, rec = ctx["upcoming"], ctx["recent"]
    fomc = ctx["fomc"]
    today = dt.date.today()
    nxt = [(d, sep) for d, sep in fomc if d >= today][:4]
    fomc_html = "".join(
        f"<li><b>{d:%a %d %b %Y}</b> - in {(d - today).days} days{' · SEP / dots' if sep else ''}</li>"
        for d, sep in nxt) or "<li>No future dates parsed - update FOMC_FALLBACK in config.py</li>"
    up_t = up.set_index("auction_date").rename(columns={
        "security_term": "Term", "kind": "Type", "reopening": "Reopen", "size_bn": "Size $bn",
        "issue_date": "Settles", "cusip": "CUSIP"}) if not up.empty else pd.DataFrame()
    up_t.index = [d.strftime("%a %d %b") for d in up_t.index] if not up_t.empty else []
    rec_t = rec.set_index("auction_date").rename(columns={
        "security_term": "Term", "kind": "Type", "reopening": "Reopen", "size_bn": "Size $bn",
        "high_yield": "High yld %", "high_discnt_margin": "DM", "bid_to_cover_ratio": "BTC",
        "btc_vs_avg6": "BTC vs avg6", "indirect_pct": "Indirect %", "direct_pct": "Direct %",
        "dealer_pct": "Dealer %", "dealer_vs_avg6": "Dealer vs avg6"}) if not rec.empty else pd.DataFrame()
    rec_t.index = [d.strftime("%a %d %b") for d in rec_t.index] if not rec_t.empty else []
    s_sup = section(
        "supply", "Supply & calendar", "<div class='grid'>"
        + card(f"<ul class='brief'>{fomc_html}</ul>", "Next FOMC decisions")
        + card(table(up_t, {"Size $bn": ".0f"}, index_name="Auction") if not up_t.empty
               else "<p class='note'>No announced coupon auctions.</p>",
               "Announced coupon auctions",
               note="Treasury announces sizes ~1 week ahead, so this list is often short. Usual rhythm: 3s/10s/30s in the 2nd week, "
                    "20s and TIPS mid-month, 2s/5s/7s and FRN in the last week. Quarterly refunding (Feb/May/Aug/Nov) sets coupon sizes.")
        + card(table(rec_t, {"Size $bn": ".0f", "High yld %": ".3f", "DM": ".3f", "BTC": ".2f",
                             "BTC vs avg6": "+.2f", "Indirect %": ".1f", "Direct %": ".1f",
                             "Dealer %": ".1f", "Dealer vs avg6": "+.1f"}, index_name="Auction")
               if not rec_t.empty else "<p class='note'>No recent results.</p>",
               "Recent coupon auction results", wide=True,
               note="Weak auction = low BTC, high dealer take (dealers absorb what end-investors didn't). "
                    "Tail vs when-issued isn't in the public data - get it from Bloomberg or dealer recaps.")
        + "</div>")

    warn = "".join(f"<li>{html.escape(l)}</li>" for l in ctx["log"]) or "<li>All sources refreshed.</li>"
    foot = (f"<footer><p>Sources: U.S. Treasury daily par yield curves; FRED (St. Louis Fed); "
            f"Treasury FiscalData auctions API; federalreserve.gov FOMC calendar. Generated "
            f"{dt.datetime.now():%Y-%m-%d %H:%M} local. Curve data as of {asof:%Y-%m-%d} (NY close).</p>"
            f"<ul>{warn}</ul></footer>")

    nav = "".join(f"<a href='#{a}'>{b}</a>" for a, b in [
        ("brief", "Brief"), ("curve", "Curve"), ("rv", "Spreads"), ("policy", "Policy"),
        ("book", "Book"), ("carry", "Carry/PCA"), ("cross", "Cross-asset"), ("supply", "Supply")])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>UST Desk Dashboard</title><style>{CSS}</style>
<script>{get_plotlyjs()}</script></head><body>
<header><h1>UST Desk Dashboard</h1><span class="asof">Curve as of {asof:%a %d %b %Y}</span>
<nav>{nav}</nav><button class="theme" onclick="toggleTheme()" aria-label="Toggle dark mode">◐</button></header>
<main>{s_brief}{s_curve}{s_sp}{s_pol}{s_book}{s_cr}{s_x}{s_sup}{foot}</main>
<script>{THEME_JS}</script></body></html>"""

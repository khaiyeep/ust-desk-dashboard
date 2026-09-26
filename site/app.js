/*
 * UST Desk Dashboard - page logic. Loads data.json (built daily by GitHub
 * Actions), then refreshes the browser-accessible sources live.
 */
(function () {
  "use strict";
  const U = window.UA;
  const isNum = U.isNum;
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const MINUS = "−";
  const f = (v, d = 2) => (isNum(v) ? v.toFixed(d).replace("-", MINUS) : "–");
  const fs = (v, d = 1) => {
    if (!isNum(v)) return "–";
    const r = Number(v.toFixed(d));
    return r === 0 ? (0).toFixed(d) : (r < 0 ? MINUS : "+") + Math.abs(r).toFixed(d);
  };
  const money = (usd) => {
    if (!isNum(usd)) return "–";
    if (Math.abs(usd) < 500) return "$0";
    const a = Math.abs(usd), txt = a >= 1e6 ? (a / 1e6).toFixed(2) + "mn" : (a / 1e3).toFixed(0) + "k";
    return `${usd < 0 ? MINUS : "+"}$${txt}`;
  };
  const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const fdate = (iso, year = false) => {
    if (!iso) return "–";
    const d = new Date(iso + "T00:00:00Z");
    return `${DOW[d.getUTCDay()]} ${String(d.getUTCDate()).padStart(2, "0")} ${MON[d.getUTCMonth()]}${year ? " " + d.getUTCFullYear() : ""}`;
  };
  const todayIso = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  const hhmm = (d) => d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const store = {
    get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch (e) { return false; } },
    del(k) { try { localStorage.removeItem(k); } catch (e) { /* ignore */ } },
  };

  // ------------------------------------------------------------ book setup
  const SETUP_KEY = "ustdash.setup.v1";
  const EXAMPLE = {
    example: true, mvBn: 5, teBudget: 50, durLimit: 0.5,
    krd: { "3M": [0.03, 0.02], "6M": [0.05, 0.05], "1Y": [0.15, 0.15], "2Y": [0.40, 0.45], "3Y": [0.55, 0.55],
      "5Y": [1.10, 0.95], "7Y": [0.95, 0.90], "10Y": [1.10, 1.05], "20Y": [0.70, 0.80], "30Y": [0.80, 0.95] },
  };
  const clone = (o) => JSON.parse(JSON.stringify(o));
  function validSetup(s) {
    return s && typeof s === "object" && isNum(+s.mvBn) && isNum(+s.teBudget) && isNum(+s.durLimit) && s.krd &&
      U.KR.every((t) => !s.krd[t] || (Array.isArray(s.krd[t]) && s.krd[t].length === 2));
  }
  function normSetup(s) {
    const out = { example: !!s.example, mvBn: +s.mvBn, teBudget: +s.teBudget, durLimit: +s.durLimit, krd: {} };
    U.KR.forEach((t) => { const x = s.krd[t] || [0, 0]; out.krd[t] = [+x[0] || 0, +x[1] || 0]; });
    return out;
  }
  const loadSetup = () => { const s = store.get(SETUP_KEY); return validSetup(s) ? normSetup(s) : clone(EXAMPLE); };
  const b64 = { enc: (s) => btoa(unescape(encodeURIComponent(s))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""),
    dec: (s) => decodeURIComponent(escape(atob(s.replace(/-/g, "+").replace(/_/g, "/")))) };

  // ------------------------------------------------------------------ state
  const S = { nom: null, real: null, fred: {}, auctions: [], fomc: [], generated: null, warnings: [],
    live: null, setup: loadSetup(), ctx: null, setupMsg: "" };

  function ingest(j) {
    S.nom = U.frameFromJSON(j.nominal);
    S.real = U.frameFromJSON(j.real);
    S.fred = {};
    for (const k in j.fred) S.fred[k] = { dates: j.fred[k].dates, values: j.fred[k].values.map((v) => (v == null ? NaN : v)) };
    S.auctions = j.auctions || [];
    S.fomc = j.fomc || [];
    S.generated = j.generated;
    S.warnings = j.warnings || [];
  }

  // ---------------------------------------------------------- live refresh
  const TREASURY = (year, type) => "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/" +
    `daily-treasury-rates.csv/${year}/all?type=${type}&field_tdr_date_value=${year}&page&_format=csv`;
  const AUCTIONS = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query";
  const NYFED = { EFFR: "https://markets.newyorkfed.org/api/rates/unsecured/effr/last/30.json",
    SOFR: "https://markets.newyorkfed.org/api/rates/secured/sofr/last/30.json" };
  const AUCTION_FIELDS = ["cusip", "security_term", "auction_date", "issue_date", "reopening", "offering_amt", "high_yield",
    "high_discnt_margin", "bid_to_cover_ratio", "comp_accepted", "indirect_bidder_accepted", "direct_bidder_accepted",
    "primary_dealer_accepted", "inflation_index_security", "floating_rate"];

  async function get(url, ms = 25000) {
    const c = new AbortController(), t = setTimeout(() => c.abort(), ms);
    try {
      const r = await fetch(url, { signal: c.signal, cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.text();
    } finally { clearTimeout(t); }
  }
  async function liveCurve(type) {
    const y = new Date().getUTCFullYear();
    const years = !S.nom || S.nom.dates.length < 300 ? [y - 1, y] : [y];
    let F = null;
    for (const yr of years) {
      const part = U.parseTreasuryCSV(await get(TREASURY(yr, type)));
      if (part.dates.length) F = F ? U.mergeFrames(F, part) : part;
    }
    if (!F) throw new Error("no rows");
    return F;
  }
  async function liveAuctions() {
    const start = U.addDays(todayIso(), -730);
    const q = new URLSearchParams({ filter: `auction_date:gte:${start},security_type:in:(Note,Bond)`,
      fields: AUCTION_FIELDS.join(","), sort: "-auction_date", "page[size]": "10000" });
    const j = JSON.parse(await get(`${AUCTIONS}?${q}`));
    const num = ["offering_amt", "high_yield", "high_discnt_margin", "bid_to_cover_ratio", "comp_accepted",
      "indirect_bidder_accepted", "direct_bidder_accepted", "primary_dealer_accepted"];
    return j.data.map((r) => {
      const o = { ...r };
      num.forEach((k) => { const v = parseFloat(r[k]); o[k] = isNum(v) ? v : null; });
      return o;
    });
  }
  async function liveRate(id) {
    const j = JSON.parse(await get(NYFED[id]));
    const rows = j.refRates.filter((r) => isNum(r.percentRate)).sort((a, b) => (a.effectiveDate < b.effectiveDate ? -1 : 1));
    return { dates: rows.map((r) => r.effectiveDate), values: rows.map((r) => r.percentRate) };
  }

  function signature() {
    const last = (x) => (x && x.dates.length ? x.dates[x.dates.length - 1] + ":" + x.dates.length : "-");
    const done = S.auctions.filter((a) => isNum(a.bid_to_cover_ratio)).length;
    const r = (k) => { const s = S.fred[k]; return s ? last(s) + ":" + s.values[s.values.length - 1] : "-"; };
    const lastRow = S.nom ? Object.values(S.nom.cols).map((c) => c[c.length - 1]).join(",") : "";
    return [last(S.nom), lastRow, last(S.real), S.auctions.length, done, r("EFFR"), r("SOFR")].join("|");
  }
  async function liveRefresh() {
    const btn = $("#refresh");
    btn.disabled = true; btn.textContent = "Refreshing…";
    setStatus("Checking Treasury, FiscalData and NY Fed for new data…");
    const jobs = {
      "Treasury curve": liveCurve("daily_treasury_yield_curve").then((F) => { S.nom = S.nom ? U.mergeFrames(S.nom, F) : F; }),
      "TIPS curve": liveCurve("daily_treasury_real_yield_curve").then((F) => { S.real = S.real ? U.mergeFrames(S.real, F) : F; }),
      "Auctions": liveAuctions().then((a) => { S.auctions = a; }),
      "EFFR": liveRate("EFFR").then((s) => { S.fred.EFFR = U.mergeSeries(S.fred.EFFR, s); }),
      "SOFR": liveRate("SOFR").then((s) => { S.fred.SOFR = U.mergeSeries(S.fred.SOFR, s); }),
    };
    const names = Object.keys(jobs), before = signature();
    const res = await Promise.allSettled(Object.values(jobs));
    S.live = { at: new Date(), failed: names.filter((_, i) => res[i].status === "rejected") };
    btn.disabled = false; btn.textContent = "Refresh";
    // Only redraw when something actually changed, and keep the reader's place on the page.
    S.live.changed = signature() !== before;
    if (S.nom && (S.live.changed || !S.ctx)) {
      const y = window.scrollY;
      compute(); renderAll();
      requestAnimationFrame(() => window.scrollTo(0, y));
    }
    renderStatus();
  }

  // ---------------------------------------------------------------- compute
  function breakevens() {
    const N = S.nom, R = S.real;
    const out = { be5: { dates: [], values: [] }, be10: { dates: [], values: [] }, fwd: { dates: [], values: [] } };
    if (!R) return out;
    R.dates.forEach((d, i) => {
      const j = U.idxLE(N.dates, d);
      if (j < 0 || N.dates[j] !== d) return;
      const b5 = N.cols["5Y"][j] - R.cols["5Y"][i], b10 = N.cols["10Y"][j] - R.cols["10Y"][i];
      if (!isNum(b5) || !isNum(b10)) return;
      out.be5.dates.push(d); out.be5.values.push(b5);
      out.be10.dates.push(d); out.be10.values.push(b10);
      out.fwd.dates.push(d); out.fwd.values.push((Math.pow(Math.pow(1 + b10 / 100, 10) / Math.pow(1 + b5 / 100, 5), 0.2) - 1) * 100);
    });
    return out;
  }
  function compute() {
    const F = S.nom, lb = U.lookback(F.dates);
    const sp = U.spreads(F), spTab = {};
    for (const k in sp) spTab[k] = U.levelRow(sp[k], lb, U.SETTINGS.zWindow);
    const p = U.pca(F);
    S.ctx = { F, lb, sp, spTab, p,
      snap: U.curveSnapshot(F, lb), chg: U.curveChanges(F, lb), pcam: U.pcaRecentMoves(F, lb, p),
      cr: U.carryRoll(F, lb), be: breakevens(), rv: U.realizedVol(F),
      sb: S.fred.SP500 && S.fred.SP500.values.length ? U.stockBondCorr(S.fred.SP500, U.frameCol(F, "10Y")) : null,
      at: U.auctionTables(S.auctions, todayIso()) };
    computeBook();
  }
  function computeBook() {
    const c = S.ctx, s = S.setup;
    c.risk = U.bookRisk(s, c.F);
    c.fx = U.factorExposure(s, c.p);
    c.scen = U.scenarios(s, c.F, c.lb, c.p);
    c.bc = U.bookCarry(s, c.cr);
    c.talk = U.commentary(c.chg, c.spTab, c.cr, S.fred.EFFR, c.F, c.risk, c.pcam, c.sb, s.teBudget);
  }

  // ----------------------------------------------------------------- charts
  const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
  const CFG = { displaylogo: false, responsive: true, displayModeBar: false };
  const charts = new Map();
  function isDark() {
    const t = document.documentElement.dataset.theme;
    return t ? t === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  }
  function palette() {
    return isDark()
      ? { s: ["#3987e5", "#d95926", "#199e70"], gray: "#898781", pos: "#3987e5", neg: "#e66767", ink: "#ffffff",
        ink2: "#c3c2b7", grid: "#2c2c2a", axis: "#383835", band: "rgba(195,194,183,0.12)", hover: "#1a1a19" }
      : { s: ["#2a78d6", "#eb6834", "#1baf7a"], gray: "#898781", pos: "#2a78d6", neg: "#e34948", ink: "#0b0b0b",
        ink2: "#52514e", grid: "#e1e0d9", axis: "#c3c2b7", band: "rgba(137,135,129,0.14)", hover: "#fcfcfb" };
  }
  const phone = () => window.innerWidth < 640;
  function lay(P, o = {}) {
    return {
      height: o.height || (phone() ? 250 : 310),
      margin: Object.assign({ l: 8, r: 12, t: o.legend === false ? 10 : 30, b: 8 }, o.margin || {}),
      paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: FONT, size: phone() ? 11 : 12, color: P.ink },
      showlegend: o.legend !== false,
      legend: { orientation: "h", x: 0, y: 1.02, yanchor: "bottom", bgcolor: "rgba(0,0,0,0)" },
      hovermode: o.hover || "x unified",
      hoverlabel: { bgcolor: P.hover, bordercolor: P.axis, font: { family: FONT, color: P.ink } },
      barcornerradius: 3, bargap: 0.3, bargroupgap: 0.08,
      xaxis: Object.assign({ showgrid: false, linecolor: P.axis, tickcolor: P.axis, ticks: "outside", zeroline: false, automargin: true }, o.xaxis || {}),
      yaxis: Object.assign({ gridcolor: P.grid, linecolor: P.axis, zeroline: false, automargin: true }, o.yaxis || {}),
      shapes: o.shapes || [],
    };
  }
  const zeroLine = (P, axis = "y") => (axis === "y"
    ? { type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: P.axis, width: 1 } }
    : { type: "line", yref: "paper", y0: 0, y1: 1, x0: 0, x1: 0, line: { color: P.axis, width: 1 } });
  function plot(id, build) { charts.set(id, build); draw(id); }
  function draw(id) {
    const el = document.getElementById(id);
    if (!el || !window.Plotly) return;
    const { data, layout } = charts.get(id)(palette());
    Plotly.react(el, data, layout, CFG);
  }
  const redrawAll = () => { for (const id of charts.keys()) draw(id); };

  function lineChart(series, o = {}) {
    return (P) => ({
      data: series.map((x, i) => ({ x: x.s.dates, y: x.s.values, name: x.name, type: "scatter", mode: "lines",
        line: { color: x.color ? x.color(P) : P.s[i], width: 2 },
        hovertemplate: `%{y:${o.fmt || ".2f"}}${o.unit || ""}<extra>${esc(x.name)}</extra>` })),
      layout: lay(P, { legend: series.length > 1, height: o.height,
        yaxis: Object.assign({ ticksuffix: o.unit || "" }, o.tickformat ? { tickformat: o.tickformat } : {}),
        shapes: o.zero ? [zeroLine(P)] : [] }),
    });
  }
  function signedBars(labels, values, o = {}) {
    const d = o.fmt ?? 2, unit = o.unit || "";
    return (P) => {
      const colors = values.map((v) => (v >= 0 ? P.pos : P.neg));
      const text = values.map((v) => (Math.abs(v) >= 0.5 * Math.pow(10, -d) ? fs(v, d) + unit : ""));
      const bar = o.horizontal
        ? { type: "bar", orientation: "h", y: labels, x: values, marker: { color: colors }, text, textposition: "outside",
          cliponaxis: false, hovertemplate: `%{y}: %{x:+.${d}f}${unit}<extra></extra>` }
        : { type: "bar", x: labels, y: values, marker: { color: colors }, text, textposition: "outside",
          cliponaxis: false, hovertemplate: `%{x}: %{y:+.${d}f}${unit}<extra></extra>` };
      // Pad the value axis so outside labels on negative bars don't run into the category labels.
      const lo = Math.min(0, ...values), hi = Math.max(0, ...values), span = hi - lo || 1, pad = phone() ? 0.75 : 0.25;
      const range = [lo < 0 ? lo - pad * span : lo, hi > 0 ? hi + pad * span : hi];
      const layout = lay(P, { legend: false, hover: "closest", height: o.height,
        margin: o.horizontal ? { r: 12 } : { t: 24 },
        xaxis: o.horizontal ? { showgrid: true, gridcolor: P.grid, ticksuffix: unit, ticks: "", range, nticks: 5 } : { type: "category" },
        yaxis: o.horizontal ? { autorange: "reversed", gridcolor: "rgba(0,0,0,0)", type: "category" } : { ticksuffix: unit },
        shapes: [zeroLine(P, o.horizontal ? "x" : "y")] });
      return { data: [bar], layout };
    };
  }

  // ------------------------------------------------------------------- html
  const tile = (label, value, sub = "", status = null) =>
    `<div class="tile"><div class="tl">${esc(label)}</div><div class="tv">${value}</div><div class="ts">${sub}</div>` +
    (status ? `<div class="chip ${status[0]}"><span class="dot" aria-hidden="true"></span>${esc(status[1])}</div>` : "") + "</div>";
  function yieldTile(label, s, lb) {
    const c = U.clean(s);
    if (!c.values.length) return "";
    const last = c.values[c.values.length - 1], d = (k) => (last - U.asofVal(c, lb[k])) * 100;
    return tile(label, `${f(last)}%`, `1d ${fs(d("1d"))} · 1w ${fs(d("1w"))} · 1m ${fs(d("1m"))} bp`);
  }
  function spreadTile(label, s, lb) {
    const c = U.clean(s), last = c.values[c.values.length - 1], d = (k) => last - U.asofVal(c, lb[k]);
    return tile(label, `${f(last, 0)}bp`, `1d ${fs(d("1d"))} · 1w ${fs(d("1w"))} · 1m ${fs(d("1m"))} bp`);
  }
  function table(head, rows, o = {}) {
    const th = head.map((h) => `<th scope="col">${esc(h)}</th>`).join("");
    const tr = rows.map((r) => `<tr><th scope="row">${esc(r[0])}</th>${r.slice(1).map((c) => `<td>${c}</td>`).join("")}</tr>`).join("");
    return `<div class="tbl"><table${o.cls ? ` class="${o.cls}"` : ""}><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
  }
  const card = (inner, title = "", o = {}) =>
    `<div class="card${o.wide ? " wide" : ""}">${title ? `<h3>${title}</h3>` : ""}${inner}${o.note ? `<p class="note">${o.note}</p>` : ""}</div>`;
  const chartDiv = (id, cls = "") => `<div id="${id}" class="chart ${cls}"></div>`;
  const zfmt = (v) => (isNum(v) && Math.abs(v) >= 2 ? `<b>${fs(v, 2)}</b>` : fs(v, 2));

  // --------------------------------------------------------------- sections
  function renderBrief() {
    const { F, lb, sp, be, talk } = S.ctx;
    const t = [];
    ["3M", "2Y", "5Y", "10Y", "30Y"].forEach((x) => t.push(yieldTile(x, U.frameCol(F, x), lb)));
    ["2s10s", "5s30s", "2s5s10s"].forEach((x) => t.push(spreadTile(x, sp[x], lb)));
    if (S.real) t.push(yieldTile("10Y real", U.frameCol(S.real, "10Y"), lb));
    t.push(yieldTile("10Y breakeven", be.be10, lb));
    ["EFFR", "SOFR"].forEach((x) => { if (S.fred[x]) t.push(yieldTile(x, S.fred[x], lb)); });
    const tp = S.fred.THREEFYTP10;
    if (tp && tp.values.length) {
      const L = U.lastVal(tp);
      t.push(tile("10Y term premium", `${f(L.value)}%`, `as of ${fdate(L.date)} · 1m ${fs((L.value - U.asofVal(tp, lb["1m"])) * 100)} bp`));
    }
    [["VIXCLS", "VIX", 1], ["DEXMAUS", "USD/MYR", 4]].forEach(([k, lab, d]) => {
      const s = S.fred[k];
      if (s && s.values.length) { const L = U.lastVal(s); t.push(tile(lab, f(L.value, d), `as of ${fdate(L.date)}`)); }
    });
    $("#brief-body").innerHTML = `<div class="tiles">${t.join("")}</div>` +
      card(`<ul class="talk">${talk.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>`, "Talking points",
        { note: "Auto-drafted from the numbers. Check them against the news before the morning call." });
  }

  function renderCurve() {
    const { snap, chg } = S.ctx;
    const tenors = snap.tenors;
    const cols = Object.keys(snap.cols), dcols = Object.keys(chg);
    const rows = tenors.map((t) => [t, ...cols.map((c) => f(snap.cols[c][t])), ...dcols.map((c) => fs(chg[c][t]))]);
    $("#curve-body").innerHTML = `<div class="grid">` +
      card(chartDiv("ch-curve"), "Par curve: today vs history") +
      card(chartDiv("ch-chg"), "Changes by tenor") +
      card(table(["Tenor", ...cols, ...dcols.map((c) => c + " bp")], rows), "Levels (%) and changes (bp)", { wide: true }) + `</div>`;
    const styles = { "Today": [0, 2.5], "1w ago": [1, 2], "1m ago": [2, 2], "1y ago": [-1, 2] };
    plot("ch-curve", (P) => ({
      data: Object.entries(styles).filter(([k]) => snap.cols[k]).map(([k, [ci, w]]) => {
        const ts = tenors.filter((t) => isNum(snap.cols[k][t]));
        return { x: ts, y: ts.map((t) => snap.cols[k][t]), name: k, type: "scatter", mode: "lines+markers",
          line: { color: ci < 0 ? P.gray : P.s[ci], width: w }, marker: { size: 7 },
          hovertemplate: `%{y:.2f}%<extra>${k}</extra>` };
      }),
      layout: lay(P, { xaxis: { type: "category" }, yaxis: { ticksuffix: "%" } }),
    }));
    plot("ch-chg", (P) => ({
      data: ["Δ1d", "Δ1w", "Δ1m"].map((k, i) => ({ type: "bar", x: tenors, y: tenors.map((t) => chg[k][t]), name: k,
        marker: { color: P.s[i] }, hovertemplate: `%{y:+.1f}bp<extra>${k}</extra>` })),
      layout: lay(P, { xaxis: { type: "category" }, yaxis: { ticksuffix: "bp" }, shapes: [zeroLine(P)] }),
    }));
  }

  function renderSpreads() {
    const { sp, spTab } = S.ctx, W = U.SETTINGS.zWindow;
    const names = Object.keys(sp);
    const head = ["Spread (bp)", "Level", "Δ1d", "Δ1w", "Δ1m", "1y low", "1y high", "z (1y)", "Pctile (1y)"];
    const rows = names.map((n) => { const r = spTab[n]; return [n, f(r.Level, 1), fs(r["Δ1d"]), fs(r["Δ1w"]), fs(r["Δ1m"]),
      f(r["1y low"], 1), f(r["1y high"], 1), zfmt(r["z (1y)"]), f(r["Pctile (1y)"], 0)]; });
    $("#rv-body").innerHTML = `<div class="minis">${names.map((n) => card(chartDiv("ch-sp-" + n, "mini"), n)).join("")}</div>` +
      `<p class="note">Shaded band: trailing 1y mean ± 1σ. Flies are 2×belly − wings, so positive means the belly is cheap.</p>` +
      card(table(head, rows), "Relative-value screen", { note: "Bold: |z| ≥ 2. Mean reversion is a tendency, not a law. Check what is driving the move first." });
    names.forEach((n) => {
      const s = U.tail(U.clean(sp[n]), W * 2), h = U.tail(s, W);
      const m = U.mean(h.values), sd = U.std(h.values), x0 = h.dates[0], x1 = h.dates[h.dates.length - 1];
      plot("ch-sp-" + n, (P) => ({
        data: [{ x: s.dates, y: s.values, type: "scatter", mode: "lines", line: { color: P.s[0], width: 1.8 },
          hovertemplate: `%{y:.1f}bp<extra>${n}</extra>` }],
        layout: lay(P, { legend: false, height: phone() ? 200 : 220, yaxis: { ticksuffix: "bp" },
          shapes: [
            { type: "rect", xref: "x", yref: "y", x0, x1, y0: m - sd, y1: m + sd, fillcolor: P.band, line: { width: 0 }, layer: "below" },
            { type: "line", xref: "x", yref: "y", x0, x1, y0: m, y1: m, line: { color: P.gray, width: 1 } },
          ] }),
      }));
    });
  }

  function renderPolicy() {
    const { F, be } = S.ctx;
    const pol = [];
    if (S.fred.EFFR) pol.push({ name: "EFFR", s: U.tail(U.clean(S.fred.EFFR), 500) });
    pol.push({ name: "3M bill", s: U.tail(U.clean(U.frameCol(F, "3M")), 500) });
    pol.push({ name: "2Y", s: U.tail(U.clean(U.frameCol(F, "2Y")), 500) });
    $("#policy-body").innerHTML = `<div class="grid">` +
      card(chartDiv("ch-pol"), "Policy rate vs front end", { note: "2Y above EFFR means the market prices hikes (or a term premium); below means cuts. Use WIRP or SOFR futures for the precise path." }) +
      card(chartDiv("ch-tp"), "10Y term premium (Kim-Wright)", { note: "A rising term premium means investors want more to hold duration: supply, fiscal or inflation uncertainty. Fed Board data, lags about a week." }) +
      card(chartDiv("ch-real"), "TIPS real yields") +
      card(chartDiv("ch-be"), "Breakeven inflation", { note: "Nominal minus TIPS par yields. 5y5y is the forward 5y breakeven starting in 5 years." }) + `</div>`;
    plot("ch-pol", lineChart(pol, { unit: "%" }));
    if (S.fred.THREEFYTP10) plot("ch-tp", lineChart([{ name: "10Y term premium", s: U.tail(U.clean(S.fred.THREEFYTP10), 750) }], { unit: "%", zero: true }));
    if (S.real) plot("ch-real", lineChart(["5Y", "10Y", "30Y"].map((t) => ({ name: `${t} real`, s: U.tail(U.clean(U.frameCol(S.real, t)), 500) })), { unit: "%" }));
    plot("ch-be", lineChart([{ name: "5Y BE", s: U.tail(be.be5, 500) }, { name: "10Y BE", s: U.tail(be.be10, 500) },
      { name: "5y5y fwd BE", s: U.tail(be.fwd, 500) }], { unit: "%" }));
  }

  function renderBook() {
    const c = S.ctx, s = S.setup, r = c.risk, mv = s.mvBn * 1e9;
    const teUse = r.teBp / s.teBudget * 100;
    const teStatus = teUse < 75 ? ["good", "Within budget"] : teUse <= 100 ? ["warn", "Near budget"] : ["crit", "Over budget"];
    const durUse = Math.abs(r.activeDur) / s.durLimit * 100;
    const durStatus = durUse < 75 ? ["good", `${durUse.toFixed(0)}% of ±${s.durLimit}y limit`]
      : durUse <= 100 ? ["warn", `${durUse.toFixed(0)}% of limit`] : ["crit", `${durUse.toFixed(0)}% of limit: breach`];
    const months = Math.round(U.SETTINGS.horizon * 12);
    const tiles = [
      tile("Portfolio duration", `${f(r.portDur)}y`, `Benchmark ${f(r.benchDur)}y`),
      tile("Active duration", `${fs(r.activeDur, 2)}y`, `Active DV01 ${money(r.activeDv01)} per bp`, durStatus),
      tile("Ex-ante tracking error", `${f(r.teBp, 0)}bp/yr`, `Budget ${s.teBudget}bp · ${teUse.toFixed(0)}% used · rates only`, teStatus),
      tile("1-day VaR 95% (active)", `${f(r.var95Bp, 1)}bp`, `≈ $${(r.var95Usd / 1e6).toFixed(1)}mn on $${s.mvBn}bn`),
      tile(`Carry + roll (${months}m)`, `${fs(c.bc.bp)}bp`, `${money(c.bc.usd)} if the curve doesn't move`),
    ];
    const scenRows = c.scen.map((x) => [x.name, fs(x["2Y Δbp"]), fs(x["5Y Δbp"]), fs(x["10Y Δbp"]), fs(x["30Y Δbp"]),
      fs(x["Active P&L bp"], 2), money(x["Active P&L USD"])]);
    const krRows = U.KR.map((t, i) => [t, f(s.krd[t][0]), f(s.krd[t][1]), fs(r.active[i], 2), money(r.activeDv01ByTenor[i]),
      fs(r.teContrib[i], 0), fs(c.bc.byTenor[i], 2)]);
    const fxRows = c.fx.map((x) => [x.factor, fs(x.day, 2), fs(x.month, 2)]);
    $("#book-body").innerHTML =
      `<p class="note">KRDs in years from Book setup. P&amp;L in bp of the $${s.mvBn}bn portfolio. TE and VaR use 1y historical covariance of par yields, so they cover curve risk only (no spread, selection or TIPS risk).</p>` +
      `<div class="tiles">${tiles.join("")}</div><div class="grid">` +
      card(chartDiv("ch-krd"), "Active key-rate duration (overweight + / underweight −)") +
      card(chartDiv("ch-tec"), "Contribution to tracking error", { note: "Where the risk sits. A negative bucket diversifies the rest of the book." }) +
      card(chartDiv("ch-scen"), "Scenario P&amp;L vs benchmark (bp of portfolio)", { wide: true }) +
      card(table(["Scenario", "2Y Δbp", "5Y Δbp", "10Y Δbp", "30Y Δbp", "Active P&L bp", "Active P&L $"], scenRows), "Scenario detail", { wide: true }) +
      card(table(["Key rate", "Portfolio KRD", "Benchmark KRD", "Active KRD", "Active DV01", "TE contrib %", "Carry+roll bp"], krRows), "Key-rate detail") +
      card(table(["Factor", "+1σ day (bp)", "+1σ month (bp)"], fxRows), "PCA factor exposure",
        { note: "Active P&L for a +1σ move: level (yields up), slope (steeper), curvature (belly cheaper). PCA uses 1Y-30Y, so bill KRDs are left out." }) +
      `</div>`;
    plot("ch-krd", signedBars(U.KR, r.active, { fmt: 2, unit: "y" }));
    plot("ch-tec", signedBars(U.KR, r.teContrib, { fmt: 0, unit: "%" }));
    plot("ch-scen", signedBars(c.scen.map((x) => x.name), c.scen.map((x) => x["Active P&L bp"]),
      { fmt: 1, unit: "bp", horizontal: true, height: 60 + 24 * c.scen.length }));
  }

  function renderCarry() {
    const { cr, p, pcam } = S.ctx, months = Math.round(U.SETTINGS.horizon * 12);
    const tenors = U.KR.filter((t) => t !== "3M");
    const rows = U.KR.map((t) => { const x = cr[t]; return [t, f(x["Yield %"]), f(x["Mod dur"]), fs(x["Carry bp"]), fs(x["Roll bp"]),
      fs(x["Breakeven bp"]), fs(x["Return bp"], 0)]; });
    const mrows = p.names.map((n, j) => [n, fs(pcam["1w"][j], 2), fs(pcam["1m"][j], 2), fs(pcam["3m"][j], 2)]);
    $("#carry-body").innerHTML = `<div class="grid">` +
      card(chartDiv("ch-be-bar"), `${months}m carry + roll breakeven by tenor`,
        { note: `How many bp the yield can rise over ${months}m before a long underperforms ${U.SETTINGS.fundTenor} bills. Par-curve approximation.` }) +
      card(table(["Tenor", "Yield %", "Mod dur", "Carry bp", "Roll bp", "Breakeven bp", "Return bp"], rows), "Carry and roll table") +
      card(chartDiv("ch-pca"), "PCA loadings (1y of daily changes)",
        { note: "Shape of a typical 1σ day for each factor. Use them for hedge ratios and to see what the book is really exposed to." }) +
      card(table(["Factor move (σ)", "1w", "1m", "3m"], mrows), "Recent factor moves",
        { note: "Move over the window divided by σ·√days. Beyond ±2 is unusual." }) + `</div>`;
    plot("ch-be-bar", signedBars(tenors, tenors.map((t) => cr[t]["Breakeven bp"]), { fmt: 1, unit: "bp" }));
    plot("ch-pca", (P) => ({
      data: p.names.map((n, j) => ({ x: p.tenors, y: p.loadings[j], name: `${n} (${p.explained[j].toFixed(0)}%)`, type: "scatter",
        mode: "lines+markers", line: { color: P.s[j], width: 2 }, marker: { size: 8 }, hovertemplate: `%{y:+.2f}bp<extra>${n}</extra>` })),
      layout: lay(P, { xaxis: { type: "category" }, yaxis: { ticksuffix: "bp" }, shapes: [zeroLine(P)] }),
    }));
  }

  function renderCross() {
    const { sb, rv } = S.ctx;
    const liq = [["WRESBAL", "Bank reserves", 1e3], ["WTREGEN", "TGA", 1e3], ["RRPONTSYD", "ON RRP", 1]].filter(([k]) => S.fred[k]);
    const fx = [["DEXMAUS", "USD/MYR", ".4f"], ["DTWEXBGS", "Broad USD index", ".1f"], ["VIXCLS", "VIX", ".1f"]].filter(([k]) => S.fred[k]);
    $("#cross-body").innerHTML = `<div class="grid">` +
      card(chartDiv("ch-sb"), "Stock-bond correlation",
        { note: "Under TPA this matters most. Positive means Treasuries hedge the equity and credit risk elsewhere in the reserves. Negative means they don't." }) +
      card(chartDiv("ch-rv"), "Realised yield vol (1m, annualised)",
        { note: "A stand-in for MOVE. Size in vol-adjusted terms: the same DV01 carries more risk when vol is high." }) + `</div>` +
      `<h3 class="sub">Liquidity plumbing ($bn)</h3><div class="minis">${liq.map(([k, n]) => card(chartDiv("ch-l-" + k, "mini"), n)).join("")}</div>` +
      `<p class="note">Scarce reserves plus a TGA rebuild mean funding pressure in the front end and swap spreads. Reserves are weekly; TGA and RRP are daily.</p>` +
      `<h3 class="sub">FX and risk sentiment</h3><div class="minis">${fx.map(([k, n]) => card(chartDiv("ch-x-" + k, "mini"), n)).join("")}</div>`;
    if (sb) plot("ch-sb", lineChart([{ name: "Corr(S&P return, 10Y Δy), 3m", s: U.tail(sb, 750) }], { zero: true }));
    plot("ch-rv", lineChart(["2Y", "10Y", "30Y"].map((t) => ({ name: t, s: U.tail(U.clean(rv[t]), 750) })), { unit: "bp", fmt: ".0f" }));
    const mini = { height: phone() ? 190 : 210 };
    liq.forEach(([k, n, div]) => {
      const s = U.clean(S.fred[k]);
      plot("ch-l-" + k, lineChart([{ name: n, s: { dates: s.dates.slice(-800), values: s.values.slice(-800).map((v) => v / div) } }], { ...mini, fmt: ",.0f" }));
    });
    fx.forEach(([k, n, fmt]) => plot("ch-x-" + k, lineChart([{ name: n, s: U.tail(U.clean(S.fred[k]), 750) }], { ...mini, fmt })));
  }

  function renderSupply() {
    const { at } = S.ctx, today = todayIso();
    const next = S.fomc.filter(([d]) => d >= today).slice(0, 4);
    const days = (iso) => Math.round((new Date(iso + "T00:00:00Z") - new Date(today + "T00:00:00Z")) / 864e5);
    const fomc = next.length ? next.map(([d, sep]) => `<li><b>${fdate(d, true)}</b> · in ${days(d)} days${sep ? " · SEP and dots" : ""}</li>`).join("")
      : "<li>No future dates in the data. The daily build refreshes them from federalreserve.gov.</li>";
    const up = at.upcoming.map((r) => [fdate(r.auction_date), esc(r.security_term), r.kind, r.reopening, f(r.sizeBn, 0), fdate(r.issue_date), esc(r.cusip)]);
    const rec = at.recent.map((r) => [fdate(r.auction_date), esc(r.security_term), r.kind, r.reopening, f(r.sizeBn, 0),
      f(r.high_yield, 3), f(r.high_discnt_margin, 3), f(r.bid_to_cover_ratio), fs(r.btcVsAvg6, 2), f(r.indirectPct, 1),
      f(r.directPct, 1), f(r.dealerPct, 1), fs(r.dealerVsAvg6, 1)]);
    $("#supply-body").innerHTML = `<div class="grid">` +
      card(`<ul class="talk">${fomc}</ul>`, "Next FOMC decisions") +
      card(up.length ? table(["Auction", "Term", "Type", "Reopen", "Size $bn", "Settles", "CUSIP"], up) : `<p class="note">No coupon auctions announced yet.</p>`,
        "Announced coupon auctions", { note: "Treasury announces sizes about a week ahead. Usual rhythm: 3s, 10s and 30s in week 2; 20s and TIPS mid-month; 2s, 5s, 7s and the FRN in the last week." }) +
      card(rec.length ? table(["Auction", "Term", "Type", "Reopen", "Size $bn", "High yld %", "DM", "BTC", "BTC vs avg6",
        "Indirect %", "Direct %", "Dealer %", "Dealer vs avg6"], rec) : `<p class="note">No results in the last 5 weeks.</p>`,
        "Recent coupon auction results", { wide: true, note: "A weak auction shows a low BTC and a high dealer take (dealers absorb what investors didn't). The public data has no when-issued yield, so get the tail from Bloomberg or dealer recaps." }) + `</div>`;
  }

  // ------------------------------------------------------------ book setup
  function renderSetup() {
    const s = S.setup;
    const rows = U.KR.map((t) => `<tr><th scope="row">${t}</th>` +
      `<td><input id="p_${t}" type="number" step="0.01" inputmode="decimal" value="${s.krd[t][0]}" aria-label="${t} portfolio KRD"></td>` +
      `<td><input id="b_${t}" type="number" step="0.01" inputmode="decimal" value="${s.krd[t][1]}" aria-label="${t} benchmark KRD"></td>` +
      `<td id="a_${t}">${fs(s.krd[t][0] - s.krd[t][1], 2)}</td></tr>`).join("");
    $("#setup-body").innerHTML =
      `<p class="note">Your numbers stay in this browser on this device. They are never uploaded, and the site's code can't send them anywhere. ` +
      `Changes save automatically.</p><div class="grid">` +
      card(`<div class="form">
        <label for="mvBn">Portfolio size (USD bn)</label><input id="mvBn" type="number" step="0.1" min="0" inputmode="decimal" value="${s.mvBn}">
        <label for="teBudget">Tracking-error budget (bp per year)</label><input id="teBudget" type="number" step="1" min="1" inputmode="decimal" value="${s.teBudget}">
        <label for="durLimit">Active duration limit (± years)</label><input id="durLimit" type="number" step="0.05" min="0.01" inputmode="decimal" value="${s.durLimit}">
      </div>`, "Mandate") +
      card(`<div class="tbl"><table class="krd"><thead><tr><th scope="col">Key rate</th><th scope="col">Portfolio</th><th scope="col">Benchmark</th><th scope="col">Active</th></tr></thead>
        <tbody>${rows}</tbody><tfoot><tr><th scope="row">Total</th><td id="tot_p"></td><td id="tot_b"></td><td id="tot_a"></td></tr></tfoot></table></div>`,
        "Key-rate durations (years)", { note: "From Bloomberg PORT (Characteristics, key rate duration) or your risk system." }) +
      card(`<textarea id="paste" rows="7" spellcheck="false" placeholder="2Y&#9;0.40&#9;0.45&#10;5Y&#9;1.10&#9;0.95"></textarea>
        <div class="row"><button id="applyPaste" class="btn" type="button">Apply pasted rows</button><span id="pasteMsg" class="msg" role="status"></span></div>`,
        "Paste from Excel or PORT", { note: "One row per tenor: tenor, portfolio KRD, benchmark KRD. Tabs, commas or spaces all work. Tenors you leave out stay as they are." }) +
      card(`<div class="row"><button id="copyLink" class="btn" type="button">Copy setup link</button><span id="linkMsg" class="msg" role="status"></span></div>
        <input id="linkOut" type="text" readonly hidden aria-label="Setup link">`,
        "Use the same setup on your phone", { note: "Open the link on the other device to load these numbers there. They travel in the part of the link after #, which browsers never send to the website. Treat the link as confidential all the same." }) +
      `</div><div class="row"><button id="reset" class="btn" type="button">Reset to example numbers</button><span id="saveMsg" class="msg" role="status">${esc(S.setupMsg)}</span></div>`;
    updateSetupTotals();
  }
  function updateSetupTotals() {
    let tp = 0, tb = 0;
    U.KR.forEach((t) => { tp += S.setup.krd[t][0]; tb += S.setup.krd[t][1]; $(`#a_${t}`).textContent = fs(S.setup.krd[t][0] - S.setup.krd[t][1], 2); });
    $("#tot_p").textContent = f(tp); $("#tot_b").textContent = f(tb); $("#tot_a").textContent = fs(tp - tb, 2);
  }
  function readSetupForm() {
    const num = (id, fallback) => { const v = parseFloat($("#" + id).value); return isNum(v) ? v : fallback; };
    const s = S.setup;
    s.mvBn = Math.max(num("mvBn", s.mvBn), 0);
    s.teBudget = Math.max(num("teBudget", s.teBudget), 1);
    s.durLimit = Math.max(num("durLimit", s.durLimit), 0.01);
    U.KR.forEach((t) => { s.krd[t] = [num("p_" + t, s.krd[t][0]), num("b_" + t, s.krd[t][1])]; });
  }
  function commitSetup(msg) {
    S.setup.example = false;
    const ok = store.set(SETUP_KEY, S.setup);
    S.setupMsg = ok ? `${msg || "Saved on this device"} at ${hhmm(new Date())}.` : "Couldn't save in this browser (private mode?). The numbers apply until you close the page.";
    $("#saveMsg").textContent = S.setupMsg;
    updateSetupTotals();
    if (S.ctx) { computeBook(); renderBrief(); renderBook(); }
    $("#example-banner").hidden = !S.setup.example;
  }
  function wireSetup() {
    const body = $("#setup-body");
    body.addEventListener("change", (e) => { if (e.target.matches("input[type=number]")) { readSetupForm(); commitSetup(); } });
    body.addEventListener("input", (e) => { if (e.target.matches("input[type=number]")) { readSetupForm(); updateSetupTotals(); } });
    body.addEventListener("click", async (e) => {
      const id = e.target.id;
      if (id === "applyPaste") {
        let n = 0; const bad = [];
        $("#paste").value.split(/\r?\n/).forEach((line) => {
          const p = line.trim().split(/[\t,; ]+/).filter(Boolean);
          if (!p.length) return;
          const t = p[0].toUpperCase(), a = parseFloat(p[1]), b = parseFloat(p[2]);
          if (U.KR.includes(t) && isNum(a) && isNum(b)) { S.setup.krd[t] = [a, b]; n++; } else bad.push(p[0]);
        });
        const msg = n ? `Applied ${n} row${n > 1 ? "s" : ""}.${bad.length ? ` Skipped: ${bad.slice(0, 4).join(", ")}.` : ""}`
          : "No rows matched. Use: tenor, portfolio KRD, benchmark KRD (for example 2Y 0.40 0.45).";
        if (n) { renderSetup(); commitSetup("Pasted rows saved"); }
        $("#pasteMsg").textContent = msg;
      } else if (id === "reset") {
        S.setup = clone(EXAMPLE); store.del(SETUP_KEY);
        S.setupMsg = "Example numbers restored."; renderSetup();
        if (S.ctx) { computeBook(); renderBrief(); renderBook(); }
        $("#example-banner").hidden = false;
      } else if (id === "copyLink") {
        const link = `${location.origin}${location.pathname}#setup=${b64.enc(JSON.stringify(S.setup))}`;
        const out = $("#linkOut");
        try { await navigator.clipboard.writeText(link); $("#linkMsg").textContent = "Link copied. Send it to yourself and open it on the other device."; out.hidden = true; }
        catch (err) { out.hidden = false; out.value = link; out.select(); $("#linkMsg").textContent = "Copy the selected link below."; }
      }
    });
  }
  function importSetupFromHash() {
    const m = location.hash.match(/^#setup=([A-Za-z0-9_-]+)$/);
    if (!m) return;
    try {
      const s = JSON.parse(b64.dec(m[1]));
      if (!validSetup(s)) throw new Error("bad");
      S.setup = normSetup(s); S.setup.example = false; store.set(SETUP_KEY, S.setup);
      S.setupMsg = "Loaded the setup from your link and saved it on this device.";
    } catch (e) { S.setupMsg = "That setup link is damaged, so the saved numbers were kept."; }
    history.replaceState(null, "", location.pathname + location.search + "#setup");
  }

  // ------------------------------------------------------------ status, UI
  function setStatus(t) { $("#status").textContent = t; }
  function renderStatus() {
    if (!S.nom) return;
    const asof = S.nom.dates[S.nom.dates.length - 1];
    $("#asof").textContent = `Curve as of ${fdate(asof, true)} (NY close)`;
    const parts = [];
    if (S.live) {
      const ok = 5 - S.live.failed.length;
      parts.push(`Live check ${hhmm(S.live.at)}: ${ok} of 5 sources reached, ${S.live.changed ? "new data loaded" : "no new data"}` +
        (S.live.failed.length ? ` (couldn't reach ${S.live.failed.join(", ")})` : ""));
    }
    if (S.generated) parts.push(`Daily build ${new Date(S.generated).toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}`);
    const age = Math.round((new Date(todayIso() + "T00:00:00Z") - new Date(asof + "T00:00:00Z")) / 864e5);
    if (age > 4) parts.push(`The curve is ${age} days old. Tap Refresh, or check that the daily build is still running.`);
    setStatus(parts.join(" · "));
  }
  function renderFooter() {
    const warn = S.warnings.length ? `<ul>${S.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : "";
    $("#foot").innerHTML = `<p>Sources: U.S. Treasury daily par yield curves (nominal and TIPS); Treasury FiscalData (auctions, TGA); NY Fed (EFFR, SOFR, reverse repo); ` +
      `FRED (St. Louis Fed) for the term premium, S&amp;P 500, VIX, USD, USD/MYR and bank reserves; federalreserve.gov for FOMC dates. ` +
      `Curve, TIPS, auctions, EFFR and SOFR refresh live in your browser; the FRED series update with the daily build.</p>${warn}`;
  }
  function renderAll() {
    if (!S.ctx) return;
    const secs = [renderBrief, renderCurve, renderSpreads, renderPolicy, renderBook, renderCarry, renderCross, renderSupply];
    secs.forEach((fn) => { try { fn(); } catch (e) { console.error(fn.name, e); } });
    renderFooter(); renderStatus();
    $("#example-banner").hidden = !S.setup.example;
    if (!window.Plotly) setStatus("Charts couldn't load (cdnjs.cloudflare.com is blocked on this network). Tables and numbers still work.");
  }

  function applyTheme(t) {
    if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
    redrawAll();
  }
  function wire() {
    $("#refresh").addEventListener("click", liveRefresh);
    $("#theme").addEventListener("click", () => {
      const next = isDark() ? "light" : "dark";
      store.set("ustdash.theme", next); applyTheme(next);
    });
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => redrawAll());
    let wasPhone = phone(), timer = null;
    window.addEventListener("resize", () => {
      clearTimeout(timer);
      timer = setTimeout(() => { if (phone() !== wasPhone) { wasPhone = phone(); redrawAll(); } }, 200);
    });
    wireSetup();
  }

  async function boot() {
    const t = store.get("ustdash.theme");
    if (t === "dark" || t === "light") document.documentElement.dataset.theme = t;
    importSetupFromHash();
    wire();
    renderSetup();
    try {
      const r = await fetch("data.json", { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      ingest(await r.json());
      compute(); renderAll();
    } catch (e) {
      setStatus("The daily data file didn't load, so the page is fetching live data instead. Some FRED panels will be empty.");
    }
    await liveRefresh();
    if (location.hash === "#setup") $("#setup").scrollIntoView();
  }
  boot();
})();

/*
 * UST desk analytics, browser edition. Mirrors ust_dash/analytics.py so the
 * page can recompute everything after a live refresh or a positions change.
 *
 * Units: yields in %, changes/spreads in bp, KRD in years, P&L in bp of the
 * portfolio unless a field says USD.
 */
(function (root) {
  "use strict";

  const KR = ["3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"];
  const PCA_T = ["1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"];
  const TY = {
    "1M": 1 / 12, "1.5M": 1.5 / 12, "2M": 2 / 12, "3M": 0.25, "4M": 4 / 12, "6M": 0.5,
    "1Y": 1, "2Y": 2, "3Y": 3, "5Y": 5, "7Y": 7, "10Y": 10, "20Y": 20, "30Y": 30,
  };
  const SETTINGS = { zWindow: 252, covWindow: 252, corrWindow: 63, horizon: 0.25, fundTenor: "3M" };

  // Flies are 2*belly - wings: positive = belly cheap.
  const SPREADS = {
    "3M10Y": { "10Y": 1, "3M": -1 },
    "2s10s": { "10Y": 1, "2Y": -1 },
    "5s30s": { "30Y": 1, "5Y": -1 },
    "10s30s": { "30Y": 1, "10Y": -1 },
    "2s5s10s": { "5Y": 2, "2Y": -1, "10Y": -1 },
    "5s10s30s": { "10Y": 2, "5Y": -1, "30Y": -1 },
  };

  // {tenor_years: shift_bp}; linear in between, flat beyond the ends.
  const SCENARIOS = {
    "Parallel +25": { 0.25: 25, 30: 25 },
    "Parallel -25": { 0.25: -25, 30: -25 },
    "Bull steepener": { 0.25: -25, 2: -25, 10: -5, 30: 0 },
    "Bear steepener": { 0.25: 0, 2: 0, 10: 20, 30: 25 },
    "Bull flattener": { 0.25: 0, 2: -5, 10: -20, 30: -25 },
    "Bear flattener": { 0.25: 25, 2: 25, 10: 5, 30: 0 },
    "Belly cheapens +10": { 2: 0, 5: 10, 10: 0 },
    "Fed cuts repriced -50 front": { 0.25: -50, 1: -40, 2: -30, 5: -15, 10: -5, 30: 0 },
    "Term-premium shock +40 long": { 0.25: 0, 2: 5, 10: 30, 30: 40 },
  };

  // ------------------------------------------------------------------ helpers
  const isNum = (v) => typeof v === "number" && isFinite(v);
  const sum = (a) => a.reduce((s, v) => s + v, 0);
  const mean = (a) => sum(a) / a.length;
  function std(a) {
    if (a.length < 2) return NaN;
    const m = mean(a);
    return Math.sqrt(a.reduce((s, v) => s + (v - m) * (v - m), 0) / (a.length - 1));
  }
  function interp(x, xs, ys) {
    const n = xs.length;
    if (x <= xs[0]) return ys[0];
    if (x >= xs[n - 1]) return ys[n - 1];
    let i = 1;
    while (xs[i] < x) i++;
    const t = (x - xs[i - 1]) / (xs[i] - xs[i - 1]);
    return ys[i - 1] + t * (ys[i] - ys[i - 1]);
  }
  const orderTenors = (ts) => ts.filter((t) => t in TY).sort((a, b) => TY[a] - TY[b]);

  // ISO date helpers (UTC, no time zones involved).
  const toD = (iso) => new Date(iso + "T00:00:00Z");
  const toIso = (d) => d.toISOString().slice(0, 10);
  const addDays = (iso, n) => { const d = toD(iso); d.setUTCDate(d.getUTCDate() + n); return toIso(d); };
  function addMonths(iso, n) {
    const d = toD(iso);
    const y = d.getUTCFullYear(), m = d.getUTCMonth() + n, day = d.getUTCDate();
    const first = new Date(Date.UTC(y, m, 1));
    const dim = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0)).getUTCDate();
    first.setUTCDate(Math.min(day, dim)); // clamp like pandas DateOffset
    return toIso(first);
  }
  function idxLE(dates, iso) { // last index with dates[i] <= iso, or -1
    let lo = 0, hi = dates.length - 1, ans = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (dates[mid] <= iso) { ans = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return ans;
  }

  // ------------------------------------------------------------ data shapes
  // Frame: {dates: [iso], cols: {tenor: [num|NaN]}}   Series: {dates, values}
  function frameFromJSON(j) {
    const cols = {};
    j.tenors.forEach((t, k) => { cols[t] = j.values.map((r) => (r[k] == null ? NaN : r[k])); });
    return { dates: j.dates.slice(), cols };
  }
  function mergeFrames(base, upd) {
    const tenors = orderTenors([...new Set([...Object.keys(base.cols), ...Object.keys(upd.cols)])]);
    const map = new Map();
    const blank = () => Object.fromEntries(tenors.map((t) => [t, NaN]));
    base.dates.forEach((d, i) => {
      const r = blank();
      tenors.forEach((t) => { if (base.cols[t]) r[t] = base.cols[t][i]; });
      map.set(d, r);
    });
    upd.dates.forEach((d, i) => {
      const r = map.get(d) || blank();
      tenors.forEach((t) => { if (upd.cols[t] && isNum(upd.cols[t][i])) r[t] = upd.cols[t][i]; });
      map.set(d, r);
    });
    const dates = [...map.keys()].sort();
    const cols = {};
    tenors.forEach((t) => { cols[t] = dates.map((d) => map.get(d)[t]); });
    return { dates, cols };
  }
  function mergeSeries(base, upd) {
    const map = new Map();
    (base ? base.dates : []).forEach((d, i) => map.set(d, base.values[i]));
    upd.dates.forEach((d, i) => { if (isNum(upd.values[i])) map.set(d, upd.values[i]); });
    const dates = [...map.keys()].sort();
    return { dates, values: dates.map((d) => map.get(d)) };
  }
  const frameCol = (F, t) => ({ dates: F.dates, values: F.cols[t] || F.dates.map(() => NaN) });
  const clean = (s) => {
    const d = [], v = [];
    s.dates.forEach((x, i) => { if (isNum(s.values[i])) { d.push(x); v.push(s.values[i]); } });
    return { dates: d, values: v };
  };
  const tail = (s, n) => ({ dates: s.dates.slice(-n), values: s.values.slice(-n) });
  function asofVal(s, iso) {
    const i = idxLE(s.dates, iso);
    for (let k = i; k >= 0; k--) if (isNum(s.values[k])) return s.values[k];
    return NaN;
  }
  const lastVal = (s) => { const c = clean(s); return { date: c.dates[c.dates.length - 1], value: c.values[c.values.length - 1] }; };

  // ------------------------------------------------------------------ market
  function lookback(dates) {
    const n = dates.length, asof = dates[n - 1];
    const tgt = { "1d": dates[n - 2], "1w": addDays(asof, -7), "1m": addMonths(asof, -1),
      "3m": addMonths(asof, -3), "1y": addMonths(asof, -12) };
    const out = { asof };
    for (const k in tgt) { const i = idxLE(dates, tgt[k]); if (i >= 0) out[k] = dates[i]; }
    return out;
  }
  function row(F, iso) { const i = F.dates.indexOf(iso); const r = {}; for (const t in F.cols) r[t] = F.cols[t][i]; return r; }

  function curveSnapshot(F, lb) {
    const last = row(F, lb.asof);
    const out = { tenors: orderTenors(Object.keys(F.cols)), cols: { "Today": last } };
    ["1w", "1m", "3m", "1y"].forEach((k) => { if (lb[k]) out.cols[`${k} ago`] = row(F, lb[k]); });
    return out;
  }
  function curveChanges(F, lb) {
    const last = row(F, lb.asof), out = {};
    ["1d", "1w", "1m", "3m"].forEach((k) => {
      if (!lb[k]) return;
      const r = row(F, lb[k]);
      out[`Δ${k}`] = Object.fromEntries(Object.keys(last).map((t) => [t, (last[t] - r[t]) * 100]));
    });
    return out;
  }
  function spreads(F) {
    const out = {};
    for (const name in SPREADS) {
      const legs = SPREADS[name];
      out[name] = { dates: F.dates, values: F.dates.map((_, i) => {
        let v = 0;
        for (const t in legs) v += legs[t] * F.cols[t][i];
        return v * 100;
      }) };
    }
    return out;
  }
  function levelRow(s, lb, window) {
    const c = clean(s);
    const hist = c.values.slice(-window);
    const last = c.values[c.values.length - 1];
    const sd = std(hist), m = mean(hist);
    return {
      "Level": last,
      "Δ1d": last - asofVal(c, lb["1d"]), "Δ1w": last - asofVal(c, lb["1w"]), "Δ1m": last - asofVal(c, lb["1m"]),
      "1y low": Math.min(...hist), "1y high": Math.max(...hist),
      "z (1y)": sd > 0 ? (last - m) / sd : NaN,
      "Pctile (1y)": (hist.filter((v) => v < last).length / hist.length) * 100,
    };
  }
  function diffs(values) { return values.map((v, i) => (i === 0 ? NaN : v - values[i - 1])); }
  function rollingStd(values, w) {
    return values.map((_, i) => {
      if (i < w - 1) return NaN;
      const win = values.slice(i - w + 1, i + 1);
      return win.every(isNum) ? std(win) : NaN;
    });
  }
  function realizedVol(F, tenors = ["2Y", "10Y", "30Y"], w = 21) {
    const out = {};
    tenors.forEach((t) => {
      const d = diffs(F.cols[t]).map((v) => v * 100);
      out[t] = { dates: F.dates, values: rollingStd(d, w).map((v) => v * Math.sqrt(252)) };
    });
    return out;
  }
  // corr(S&P daily log return, 10Y daily yield change). Positive = Treasuries hedge equities.
  function stockBondCorr(spx, y10, w = SETTINGS.corrWindow) {
    const a = clean(spx), b = y10;
    const ra = new Map(); a.dates.forEach((d, i) => { if (i > 0) ra.set(d, Math.log(a.values[i]) - Math.log(a.values[i - 1])); });
    const db = diffs(b.values);
    const dates = [], x = [], y = [];
    b.dates.forEach((d, i) => { if (ra.has(d) && isNum(db[i]) && isNum(ra.get(d))) { dates.push(d); x.push(ra.get(d)); y.push(db[i]); } });
    const out = { dates: [], values: [] };
    for (let i = w - 1; i < dates.length; i++) {
      const xs = x.slice(i - w + 1, i + 1), ys = y.slice(i - w + 1, i + 1);
      const mx = mean(xs), my = mean(ys);
      let sxy = 0, sxx = 0, syy = 0;
      for (let k = 0; k < w; k++) { sxy += (xs[k] - mx) * (ys[k] - my); sxx += (xs[k] - mx) ** 2; syy += (ys[k] - my) ** 2; }
      out.dates.push(dates[i]); out.values.push(sxy / Math.sqrt(sxx * syy));
    }
    return out;
  }
  function interpCurve(r, x) {
    const ts = orderTenors(Object.keys(r)).filter((t) => isNum(r[t]));
    return interp(x, ts.map((t) => TY[t]), ts.map((t) => r[t]));
  }
  function parModDur(yPct, T) {
    const y = yPct / 100;
    return T < 1 ? T / (1 + y * T) : (1 - Math.pow(1 + y / 2, -2 * T)) / y;
  }
  // Carry vs T-bills + roll-down on the par curve; breakeven = bp of yield rise a long can absorb.
  function carryRoll(F, lb, h = SETTINGS.horizon, fund = SETTINGS.fundTenor) {
    const last = row(F, lb.asof), f = last[fund], out = {};
    KR.forEach((t) => {
      const T = TY[t], y = last[t], D = parModDur(y, T);
      const carry = ((y - f) * h / D) * 100;
      const roll = T > h ? (y - interpCurve(last, T - h)) * 100 : 0;
      out[t] = { "Yield %": y, "Mod dur": D, "Carry bp": carry, "Roll bp": roll,
        "Breakeven bp": carry + roll, "Return bp": (carry + roll) * D };
    });
    return out;
  }
  function keyRateChanges(F, tenors, w = SETTINGS.covWindow) {
    const rows = [];
    for (let i = 1; i < F.dates.length; i++) {
      const r = tenors.map((t) => (F.cols[t][i] - F.cols[t][i - 1]) * 100);
      if (r.every(isNum)) rows.push(r);
    }
    return rows.slice(-w);
  }
  function cov(rows) {
    const n = rows.length, k = rows[0].length;
    const m = Array.from({ length: k }, (_, j) => mean(rows.map((r) => r[j])));
    const C = Array.from({ length: k }, () => Array(k).fill(0));
    rows.forEach((r) => { for (let i = 0; i < k; i++) for (let j = 0; j < k; j++) C[i][j] += (r[i] - m[i]) * (r[j] - m[j]); });
    return C.map((rr) => rr.map((v) => v / (n - 1)));
  }
  const matVec = (A, v) => A.map((r) => r.reduce((s, x, j) => s + x * v[j], 0));
  const dot = (a, b) => a.reduce((s, x, i) => s + x * b[i], 0);

  // Cyclic Jacobi for small symmetric matrices. Returns eigenvalues and column eigenvectors.
  function eigSym(A) {
    const n = A.length, a = A.map((r) => r.slice());
    const V = Array.from({ length: n }, (_, i) => Array.from({ length: n }, (_, j) => (i === j ? 1 : 0)));
    for (let sweep = 0; sweep < 100; sweep++) {
      let off = 0;
      for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) off += a[i][j] ** 2;
      if (off < 1e-20) break;
      for (let p = 0; p < n; p++) for (let q = p + 1; q < n; q++) {
        if (Math.abs(a[p][q]) < 1e-18) continue;
        const theta = (a[q][q] - a[p][p]) / (2 * a[p][q]);
        const t = (theta >= 0 ? 1 : -1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
        const c = 1 / Math.sqrt(t * t + 1), s = t * c;
        for (let k = 0; k < n; k++) { const kp = a[k][p], kq = a[k][q]; a[k][p] = c * kp - s * kq; a[k][q] = s * kp + c * kq; }
        for (let k = 0; k < n; k++) { const pk = a[p][k], qk = a[q][k]; a[p][k] = c * pk - s * qk; a[q][k] = s * pk + c * qk; }
        for (let k = 0; k < n; k++) { const kp = V[k][p], kq = V[k][q]; V[k][p] = c * kp - s * kq; V[k][q] = s * kp + c * kq; }
      }
    }
    return { values: a.map((r, i) => r[i]), vectors: V };
  }

  function pca(F, n = 3) {
    const C = cov(keyRateChanges(F, PCA_T));
    const { values, vectors } = eigSym(C);
    const order = values.map((v, i) => i).sort((i, j) => values[j] - values[i]).slice(0, n);
    const names = ["Level", "Slope", "Curvature"].slice(0, n);
    const vecs = order.map((j) => vectors.map((r) => r[j])); // vecs[f][tenor]
    const idx = (t) => PCA_T.indexOf(t);
    const belly = ["2Y", "3Y", "5Y", "7Y"].map(idx);
    // Sign conventions: level up, curve steepens, belly cheapens = positive.
    const checks = [
      (v) => sum(v),
      (v) => v[v.length - 1] - v[0],
      (v) => mean(belly.map((i) => v[i])) - (v[0] + v[v.length - 1]) / 2,
    ];
    vecs.forEach((v, f) => { if (checks[f](v) < 0) v.forEach((_, i) => { v[i] = -v[i]; }); });
    const trace = sum(C.map((r, i) => r[i]));
    const sigma = order.map((j) => Math.sqrt(values[j]));
    return {
      names, tenors: PCA_T, vecs, sigma,
      loadings: vecs.map((v, f) => v.map((x) => x * sigma[f])), // bp per 1σ day
      explained: order.map((j) => (values[j] / trace) * 100),
    };
  }
  function pcaRecentMoves(F, lb, p) {
    const n = F.dates.length, last = row(F, lb.asof), out = {};
    ["1w", "1m", "3m"].forEach((k) => {
      const i = F.dates.indexOf(lb[k]), r = row(F, lb[k]);
      const days = Math.max(n - 1 - i, 1);
      const move = p.tenors.map((t) => (last[t] - r[t]) * 100);
      out[k] = p.vecs.map((v, f) => dot(move, v) / (p.sigma[f] * Math.sqrt(days)));
    });
    return out; // out[window][factor]
  }

  // ------------------------------------------------------ active book vs benchmark
  // setup = {mvBn, teBudget, durLimit, krd: {tenor: [portfolio, benchmark]}}
  const activeVec = (setup, tenors = KR) => tenors.map((t) => { const x = setup.krd[t] || [0, 0]; return (+x[0] || 0) - (+x[1] || 0); });

  function bookRisk(setup, F) {
    const a = activeVec(setup), mv = setup.mvBn * 1e9;
    const C = cov(keyRateChanges(F, KR));
    const Ca = matVec(C, a), v = dot(a, Ca), sd = Math.sqrt(Math.max(v, 0));
    return {
      portDur: sum(KR.map((t) => +(setup.krd[t] || [0])[0] || 0)),
      benchDur: sum(KR.map((t) => +(setup.krd[t] || [0, 0])[1] || 0)),
      activeDur: sum(a), activeDv01: sum(a) * mv / 1e4,
      teBp: sd * Math.sqrt(252), var95Bp: 1.645 * sd, var95Usd: 1.645 * sd * mv / 1e4,
      teContrib: a.map((x, i) => (v > 0 ? (x * Ca[i]) / v * 100 : 0)),
      activeDv01ByTenor: a.map((x) => x * mv / 1e4), active: a,
    };
  }
  function factorExposure(setup, p) {
    const a = activeVec(setup, p.tenors);
    return p.names.map((f, j) => { const d = -dot(a, p.loadings[j]); return { factor: f, day: d, month: d * Math.sqrt(21) }; });
  }
  function scenarios(setup, F, lb, p) {
    const a = activeVec(setup), mv = setup.mvBn * 1e9, shocks = {};
    for (const name in SCENARIOS) {
      const piv = Object.entries(SCENARIOS[name]).map(([x, y]) => [+x, y]).sort((u, w) => u[0] - w[0]);
      shocks[name] = KR.map((t) => interp(TY[t], piv.map((q) => q[0]), piv.map((q) => q[1])));
    }
    const last = row(F, lb.asof);
    [["1w", "Replay last 1w"], ["1m", "Replay last 1m"], ["3m", "Replay last 3m"]].forEach(([k, label]) => {
      const r = row(F, lb[k]); shocks[label] = KR.map((t) => (last[t] - r[t]) * 100);
    });
    p.names.forEach((f, j) => {
      shocks[`PCA ${f} +1σ (1m)`] = KR.map((t) => { const i = p.tenors.indexOf(t); return i < 0 ? 0 : p.loadings[j][i] * Math.sqrt(21); });
    });
    return Object.entries(shocks).map(([name, dy]) => {
      const pnl = -dot(a, dy);
      return { name, "2Y Δbp": dy[KR.indexOf("2Y")], "5Y Δbp": dy[KR.indexOf("5Y")], "10Y Δbp": dy[KR.indexOf("10Y")],
        "30Y Δbp": dy[KR.indexOf("30Y")], "Active P&L bp": pnl, "Active P&L USD": pnl * mv / 1e4 };
    });
  }
  function bookCarry(setup, cr) {
    const a = activeVec(setup), byTenor = KR.map((t, i) => a[i] * cr[t]["Breakeven bp"]);
    const bp = sum(byTenor);
    return { bp, usd: bp * setup.mvBn * 1e9 / 1e4, byTenor };
  }

  // ------------------------------------------------------------------- supply
  function auctionTables(auctions, todayIso, recentDays = 35) {
    const rows = auctions.map((r) => {
      const kind = r.inflation_index_security === "Yes" ? "TIPS" : r.floating_rate === "Yes" ? "FRN" : "Nominal";
      const pct = (x) => (isNum(x) && isNum(r.comp_accepted) && r.comp_accepted > 0 ? (x / r.comp_accepted) * 100 : NaN);
      return { ...r, kind, sizeBn: r.offering_amt / 1e9, indirectPct: pct(r.indirect_bidder_accepted),
        directPct: pct(r.direct_bidder_accepted), dealerPct: pct(r.primary_dealer_accepted) };
    });
    const done = rows.filter((r) => isNum(r.bid_to_cover_ratio)).sort((x, y) => (x.auction_date < y.auction_date ? -1 : 1));
    const groups = {};
    done.forEach((r) => {
      const key = r.kind + "|" + r.security_term, g = (groups[key] = groups[key] || []);
      const prev = g.slice(-6);
      r.btcVsAvg6 = prev.length >= 3 ? r.bid_to_cover_ratio - mean(prev.map((q) => q.bid_to_cover_ratio)) : NaN;
      const pd = prev.map((q) => q.dealerPct).filter(isNum);
      r.dealerVsAvg6 = pd.length >= 3 ? r.dealerPct - mean(pd) : NaN;
      g.push(r);
    });
    const upcoming = rows.filter((r) => r.auction_date >= todayIso && !isNum(r.bid_to_cover_ratio))
      .sort((x, y) => (x.auction_date < y.auction_date ? -1 : 1));
    const cutoff = addDays(todayIso, -recentDays);
    const recent = done.filter((r) => r.auction_date >= cutoff).reverse();
    return { upcoming, recent };
  }

  // ------------------------------------------------------------- commentary
  function commentary(chg, spTab, cr, effr, nomF, risk, pcam, sb, teBudget) {
    const bp = (x) => `${x >= 0 ? "+" : ""}${x.toFixed(1)}bp`;
    const c = chg["Δ1w"], out = [];
    const s = spTab["2s10s"];
    out.push(`Curve on the week: 2Y ${bp(c["2Y"])}, 10Y ${bp(c["10Y"])}, 30Y ${bp(c["30Y"])}. 2s10s at ${s.Level.toFixed(0)}bp (${bp(s["Δ1w"])} w/w, 1y z ${s["z (1y)"] >= 0 ? "+" : ""}${s["z (1y)"].toFixed(1)}).`);
    const w = pcam["1w"], m = pcam["1m"], names = ["Level", "Slope", "Curvature"];
    const dom = w.map(Math.abs).indexOf(Math.max(...w.map(Math.abs)));
    const sg = (x) => `${x >= 0 ? "+" : ""}${x.toFixed(1)}σ`;
    out.push(`PCA: last week's most unusual factor move was ${names[dom].toLowerCase()} (${sg(w[dom])}); 1m moves - level ${sg(m[0])}, slope ${sg(m[1])}, curvature ${sg(m[2])}.`);
    const best = KR.filter((t) => t !== "3M").reduce((b, t) => (cr[t]["Breakeven bp"] > cr[b]["Breakeven bp"] ? t : b), "6M");
    out.push(`Best 3m carry+roll cushion on the curve: ${best} (${cr[best]["Breakeven bp"].toFixed(1)}bp of yield rise to breakeven vs bills).`);
    if (effr && effr.values.length) {
      const gap = (lastVal(frameCol(nomF, "1Y")).value - lastVal(effr).value) * 100;
      const lean = gap > 10 ? "hikes" : gap < -10 ? "cuts" : "roughly no change";
      out.push(`1Y bill − EFFR ${gap >= 0 ? "+" : ""}${gap.toFixed(0)}bp: bills lean toward ${lean} over 12m (crude - includes bill/OIS basis; check WIRP).`);
    }
    if (sb && sb.values.length) {
      const v = sb.values[sb.values.length - 1];
      const view = v > 0.2 ? "Treasuries are hedging equities" : v < -0.2 ? "stocks and bonds are moving together - weak hedge" : "hedge relationship is weak/unstable";
      out.push(`Stock-bond correlation (3m) ${v >= 0 ? "+" : ""}${v.toFixed(2)}: ${view}.`);
    }
    out.push(`Book: active duration ${risk.activeDur >= 0 ? "+" : ""}${risk.activeDur.toFixed(2)}y, ex-ante TE ${risk.teBp.toFixed(0)}bp (${(risk.teBp / teBudget * 100).toFixed(0)}% of ${teBudget}bp budget).`);
    return out;
  }

  // ---------------------------------------------------------------- CSV parse
  const TREASURY_COLS = {
    "1 Mo": "1M", "1.5 Month": "1.5M", "2 Mo": "2M", "3 Mo": "3M", "4 Mo": "4M", "6 Mo": "6M",
    "1 Yr": "1Y", "2 Yr": "2Y", "3 Yr": "3Y", "5 Yr": "5Y", "5 YR": "5Y", "7 Yr": "7Y", "7 YR": "7Y",
    "10 Yr": "10Y", "10 YR": "10Y", "20 Yr": "20Y", "20 YR": "20Y", "30 Yr": "30Y", "30 YR": "30Y",
  };
  function parseTreasuryCSV(text) {
    const lines = text.trim().split(/\r?\n/);
    const head = lines[0].split(",").map((h) => h.replace(/"/g, "").trim());
    const tenors = head.slice(1).map((h) => TREASURY_COLS[h] || null);
    const rows = lines.slice(1).map((l) => l.split(",")).filter((p) => /^\d{2}\/\d{2}\/\d{4}$/.test(p[0]));
    rows.sort((x, y) => (iso(x[0]) < iso(y[0]) ? -1 : 1));
    function iso(mdy) { const [m, d, y] = mdy.split("/"); return `${y}-${m}-${d}`; }
    const cols = {};
    tenors.forEach((t, k) => { if (t) cols[t] = rows.map((p) => { const v = parseFloat(p[k + 1]); return isNum(v) ? v : NaN; }); });
    return { dates: rows.map((p) => iso(p[0])), cols };
  }

  const API = {
    KR, PCA_T, TY, SETTINGS, SPREADS, SCENARIOS, isNum, mean, std, interp, addDays, addMonths, idxLE,
    frameFromJSON, mergeFrames, mergeSeries, frameCol, clean, tail, asofVal, lastVal, lookback, row,
    curveSnapshot, curveChanges, spreads, levelRow, realizedVol, stockBondCorr, carryRoll, keyRateChanges,
    cov, eigSym, pca, pcaRecentMoves, activeVec, bookRisk, factorExposure, scenarios, bookCarry,
    auctionTables, commentary, parseTreasuryCSV, parModDur,
  };
  root.UA = API;
  if (typeof module !== "undefined" && module.exports) module.exports = API;
})(typeof window !== "undefined" ? window : globalThis);

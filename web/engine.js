// LUNAR//OPS decision engine (browser). Mirrors pipeline/lunarops/solver.py;
// tests/golden.html checks that both give identical numbers on the same inputs.
// No DOM access here: the engine is independent from the UI.

export const SENSE = { sun: +1, dte: +1, blackout: -1, shadow: -1 };
export const UNITS = { sun: "pp", dte: "pp", blackout: "h", shadow: "h" };
export const LABELS = { sun: "Solar availability", dte: "DTE availability", blackout: "Longest blackout", shadow: "Longest shadow" };

export function defaultRequirements() {
  return { durationH: 168, minSunPct: 70, minDtePct: 50, maxBlackoutH: 24, maxShadowH: null, litThreshold: 0.5 };
}

export function activeConstraints(req) {
  const a = {};
  if (req.minSunPct != null) a.sun = req.minSunPct;
  if (req.minDtePct != null) a.dte = req.minDtePct;
  if (req.maxBlackoutH != null) a.blackout = req.maxBlackoutH;
  if (req.maxShadowH != null) a.shadow = req.maxShadowH;
  return a;
}

/** True runs of a boolean-ish array: {starts, ends} with ends exclusive. */
export function runs(mask) {
  const starts = [], ends = [];
  let inRun = false;
  for (let i = 0; i < mask.length; i++) {
    if (mask[i] && !inRun) { starts.push(i); inRun = true; }
    else if (!mask[i] && inRun) { ends.push(i); inRun = false; }
  }
  if (inRun) ends.push(mask.length);
  return { starts: Int32Array.from(starts), ends: Int32Array.from(ends) };
}

/** Longest run of true samples inside each window [s, s+len). Sweep over runs sorted by start. */
export function longestRunInWindows(mask, windowStarts, len, pre = null) {
  const { starts: rs, ends: re } = pre || runs(mask);
  const out = new Float64Array(windowStarts.length);
  let j0 = 0;
  for (let w = 0; w < windowStarts.length; w++) {
    const ws = windowStarts[w], we = ws + len;
    while (j0 < rs.length && re[j0] <= ws) j0++;
    let best = 0;
    for (let j = j0; j < rs.length && rs[j] < we; j++) {
      const v = Math.min(re[j], we) - Math.max(rs[j], ws);
      if (v > best) best = v;
    }
    out[w] = best;
  }
  return out;
}

/** Run list + sparse table over run lengths: longest run inside any window in O(1). */
function runIndex(mask) {
  const r = runs(mask), n = r.starts.length;
  const t = [new Int32Array(n)];
  for (let i = 0; i < n; i++) t[0][i] = r.ends[i] - r.starts[i];
  for (let k = 1; (1 << k) <= n; k++) {
    const prev = t[k - 1], h = 1 << (k - 1), cur = new Int32Array(n - (1 << k) + 1);
    for (let i = 0; i < cur.length; i++) cur[i] = prev[i] > prev[i + h] ? prev[i] : prev[i + h];
    t.push(cur);
  }
  return { ...r, table: t };
}
/** Same result as longestRunInWindows, for increasing window starts: interior runs by range-max, edges clipped. */
function longestRunFast(idx, windowStarts, len) {
  const { starts: rs, ends: re, table } = idx, R = rs.length;
  const out = new Float64Array(windowStarts.length);
  let j0 = 0, j1 = -1;
  for (let w = 0; w < windowStarts.length; w++) {
    const ws = windowStarts[w], we = ws + len;
    while (j0 < R && re[j0] <= ws) j0++;
    while (j1 + 1 < R && rs[j1 + 1] < we) j1++;
    if (j0 > j1) { out[w] = 0; continue; }
    let best = Math.min(re[j0], we) - Math.max(rs[j0], ws);
    const e = Math.min(re[j1], we) - Math.max(rs[j1], ws);
    if (e > best) best = e;
    if (j1 - j0 >= 2) {
      const l = j0 + 1, r = j1 - 1, k = 31 - Math.clz32(r - l + 1);
      const a = table[k][l], b = table[k][r - (1 << k) + 1], m = a > b ? a : b;
      if (m > best) best = m;
    }
    out[w] = best;
  }
  return out;
}

function prefix(arr, map = (x) => x) {
  const p = new Float64Array(arr.length + 1);
  for (let i = 0; i < arr.length; i++) p[i + 1] = p[i] + map(arr[i]);
  return p;
}

// Everything about a series that does not depend on the mission length, computed once per
// (series, lit threshold): prefix sums and run lists. Changing the duration then costs one sweep.
const _aux = new WeakMap();
function seriesAux(series, litThreshold) {
  let byLit = _aux.get(series.f);
  if (!byLit) { byLit = new Map(); _aux.set(series.f, byLit); }
  let a = byLit.get(litThreshold);
  if (!a) {
    const n = series.f.length;
    const ov = new Uint8Array(n), noDte = new Uint8Array(n), dark = new Uint8Array(n);
    for (let i = 0; i < n; i++) {
      ov[i] = series.f[i] >= litThreshold && series.dte[i] ? 1 : 0;
      noDte[i] = series.dte[i] ? 0 : 1;
      dark[i] = series.f[i] <= 0 ? 1 : 0;
    }
    a = { cf: prefix(series.f), cd: prefix(series.dte), co: prefix(ov), noDte: runIndex(noDte), dark: runIndex(dark) };
    byLit.set(litThreshold, a);
  }
  return a;
}

/**
 * series: { id, dtS, f: Float32Array (0..1), dte: Uint8Array (0/1) }
 * returns { id, starts, metrics: {sun, dte, overlap, blackout, shadow} }
 */
export function windowMetrics(series, req, startStepH = 1) {
  const perH = 3600 / series.dtS;
  const L = Math.round(req.durationH * perH);
  const step = Math.max(Math.round(startStepH * perH), 1);
  const n = series.f.length;
  const count = Math.max(Math.floor((n - L) / step) + 1, 0);
  const starts = new Int32Array(count);
  for (let k = 0; k < count; k++) starts[k] = k * step;
  const { cf, cd, co, noDte, dark } = seriesAux(series, req.litThreshold);
  const sun = new Float64Array(count), dte = new Float64Array(count), overlap = new Float64Array(count);
  for (let k = 0; k < count; k++) {
    const a = starts[k], b = a + L;
    sun[k] = (100 * (cf[b] - cf[a])) / L;
    dte[k] = (100 * (cd[b] - cd[a])) / L;
    overlap[k] = (100 * (co[b] - co[a])) / L;
  }
  const blackout = longestRunFast(noDte, starts, L), shadow = longestRunFast(dark, starts, L);
  for (let k = 0; k < count; k++) { blackout[k] /= perH; shadow[k] /= perH; }
  return { id: series.id, starts, L, perH, metrics: { sun, dte, overlap, blackout, shadow } };
}

export function evaluate(tables, req) {
  const act = activeConstraints(req), keys = Object.keys(act);
  for (const t of tables) {
    const n = t.starts.length;
    // buffers are reused between calls (a slider drag re-evaluates many times per second)
    const buf = (t._buf ??= {});
    t.margins = {};
    for (const k of keys) {
      const m = (buf[k] ??= new Float64Array(n)), src = t.metrics[k], v = act[k], sg = SENSE[k];
      for (let i = 0; i < n; i++) m[i] = sg * (src[i] - v);
      t.margins[k] = m;
    }
    // failCount[i]: how many requirements window i misses; failKey[i]: index (in keys) of the last one
    t.feasible = (buf.feasible ??= new Uint8Array(n));
    t.failCount = (buf.failCount ??= new Uint8Array(n)); t.failCount.fill(0);
    t.failKey = (buf.failKey ??= new Int8Array(n)); t.failKey.fill(-1);
    keys.forEach((k, j) => { const m = t.margins[k]; for (let i = 0; i < n; i++) if (m[i] < -1e-9) { t.failCount[i]++; t.failKey[i] = j; } });
    for (let i = 0; i < n; i++) t.feasible[i] = t.failCount[i] === 0 ? 1 : 0;
    t.failingAt = (i) => keys.filter((k) => t.margins[k][i] < -1e-9);
  }
  return tables;
}

/** Exact single-constraint relaxation (Stage 2, 2.16). */
export function minimalRelaxation(tables, req) {
  const act = activeConstraints(req), keys = Object.keys(act);
  const out = {};
  keys.forEach((k, j) => {
    // window i is a candidate if every OTHER requirement passes: no failure, or the only failure is k
    const ok = (t, i) => t.failCount[i] === 0 || (t.failCount[i] === 1 && t.failKey[i] === j);
    let best = null, where = null, count = 0;
    const sg = SENSE[k];
    for (const t of tables) {
      const met = t.metrics[k];
      for (let i = 0; i < t.starts.length; i++) {
        if (!ok(t, i)) continue;
        if (best === null || sg * (met[i] - best) > 0) { best = met[i]; where = { site: t.id, start: t.starts[i] }; }
      }
    }
    if (best === null) { out[k] = { relaxedTo: null, change: null }; return; }
    const already = sg * (best - act[k]) >= -1e-9;
    // how many windows become feasible at exactly the relaxed threshold
    for (const t of tables) { const met = t.metrics[k]; for (let i = 0; i < t.starts.length; i++) if (ok(t, i) && sg * (met[i] - best) >= -1e-9) count++; }
    out[k] = { relaxedTo: best, change: already ? 0 : best - act[k], at: where, alreadyFeasible: already, windowsAtRelaxed: count };
  });
  return out;
}

/** Number of feasible windows as a function of one threshold (what-if curve). */
export function sensitivity(tables, req, key, values) {
  const act = activeConstraints(req);
  const others = Object.keys(act).filter((j) => j !== key);
  return values.map((v) => {
    let n = 0;
    for (const t of tables) for (let i = 0; i < t.starts.length; i++) {
      if (others.some((j) => t.margins[j][i] < -1e-9)) continue;
      if (SENSE[key] * (t.metrics[key][i] - v) >= -1e-9) n++;
    }
    return { value: v, windows: n };
  });
}

/**
 * Fast what-if curve: number of feasible landing starts (all sites) as a function of the
 * threshold of `key`, every other active requirement held. Same semantics as sensitivity(),
 * computed once per update by sorting the candidate metric values (needs evaluate() first).
 */
export function thresholdCurve(tables, req, key, values) {
  const keys = Object.keys(activeConstraints(req)), j = keys.indexOf(key), sg = SENSE[key];
  let n = 0;
  for (const t of tables) n += t.starts.length;
  const buf = new Float64Array(n);
  let m = 0;
  for (const t of tables) {
    const met = t.metrics[key];
    for (let i = 0; i < t.starts.length; i++) {
      const fc = t.failCount[i];
      if (fc === 0 || (fc === 1 && j >= 0 && t.failKey[i] === j)) buf[m++] = met[i];
    }
  }
  const v = buf.subarray(0, m).sort();
  const lower = (x) => { let lo = 0, hi = v.length; while (lo < hi) { const md = (lo + hi) >> 1; if (v[md] < x) lo = md + 1; else hi = md; } return lo; };
  return values.map((x) => (sg > 0 ? v.length - lower(x - 1e-9) : lower(x + 1e-9)));
}

/** Merge consecutive feasible starts into intervals [firstStartSample, lastStartSample]. */
export function feasibleWindows(t) {
  const { starts: rs, ends: re } = runs(t.feasible);
  const out = [];
  for (let j = 0; j < rs.length; j++) out.push([t.starts[rs[j]], t.starts[re[j] - 1]]);
  return out;
}

/** Metrics and verdict for ONE window [a, a+len) of a series sampled perH times per hour. */
export function evaluateWindow(f, dte, a, len, req, perH) {
  let sf = 0, sd = 0, blk = 0, curB = 0, shd = 0, curS = 0;
  for (let i = a; i < a + len; i++) {
    sf += f[i]; sd += dte[i] ? 1 : 0;
    curB = dte[i] ? 0 : curB + 1; if (curB > blk) blk = curB;
    curS = f[i] <= 0 ? curS + 1 : 0; if (curS > shd) shd = curS;
  }
  const m = { sun: (100 * sf) / len, dte: (100 * sd) / len, blackout: blk / perH, shadow: shd / perH };
  const act = activeConstraints(req);
  const margins = {}, failing = [];
  for (const [k, v] of Object.entries(act)) { margins[k] = SENSE[k] * (m[k] - v); if (margins[k] < -1e-9) failing.push(k); }
  return { metrics: m, margins, failing, feasible: failing.length === 0 };
}

export function robustnessLabel(share) {
  if (share >= 0.9) return "ROBUST";
  if (share >= 0.5) return "MARGINAL";
  return "FRAGILE";
}

/**
 * Exact window check from run boundaries (10-min samples) plus an hourly sunlight series.
 * on / dark: flat arrays [s0, e0, s1, e1, ...] of DTE-on and no-Sun runs (end exclusive).
 */
export function evaluateWindowRuns(fHourly, step, on, dark, a, len, req, perH) {
  return runEvaluator(fHourly, step, on, dark)(a, len, req, perH);
}

/** First run index j (runs stored flat as [s0, e0, s1, e1, ...]) whose end is > a. */
function firstRunEndingAfter(r, a) {
  let lo = 0, hi = r.length / 2;
  while (lo < hi) { const m = (lo + hi) >> 1; if (r[2 * m + 1] <= a) lo = m + 1; else hi = m; }
  return lo;
}

/**
 * Precomputed form of evaluateWindowRuns for one series: prefix sums of the hourly
 * sunlight and binary search into the run lists, so thousands of windows (every
 * landing day x every dispersion point / DEM clone) can be checked interactively.
 */
export function runEvaluator(fHourly, step, on, dark) {
  const cf = prefix(fHourly);
  return (a, len, req, perH) => {
    const b = a + len;
    const ha = Math.floor(a / step), hl = Math.max(Math.round(len / step), 1);
    const sf = cf[Math.min(ha + hl, fHourly.length)] - cf[Math.min(ha, fHourly.length)];
    let onTotal = 0, gap = 0, cursor = a;
    for (let j = firstRunEndingAfter(on, a); 2 * j < on.length; j++) {
      if (on[2 * j] >= b) break;
      const s = Math.max(on[2 * j], a), e = Math.min(on[2 * j + 1], b);
      if (s - cursor > gap) gap = s - cursor;
      onTotal += e - s; cursor = e;
    }
    if (b - cursor > gap) gap = b - cursor;
    let shd = 0;
    for (let j = firstRunEndingAfter(dark, a); 2 * j < dark.length && dark[2 * j] < b; j++) {
      const v = Math.min(dark[2 * j + 1], b) - Math.max(dark[2 * j], a);
      if (v > shd) shd = v;
    }
    const m = { sun: (100 * sf) / hl, dte: (100 * onTotal) / len, blackout: gap / perH, shadow: shd / perH };
    const act = activeConstraints(req);
    const margins = {}, failing = [];
    for (const [k, v] of Object.entries(act)) { margins[k] = SENSE[k] * (m[k] - v); if (margins[k] < -1e-9) failing.push(k); }
    return { metrics: m, margins, failing, feasible: failing.length === 0 };
  };
}

/**
 * Summary of one window evaluated over an ensemble (landing points or DEM clones):
 * share that passes, and for every metric the pessimistic and optimistic value.
 */
export function ensembleSummary(results) {
  const n = results.length, pass = results.filter((r) => r.feasible).length;
  const range = {};
  for (const k of Object.keys(SENSE)) {
    const v = results.map((r) => r.metrics[k]);
    const lo = Math.min(...v), hi = Math.max(...v);
    range[k] = SENSE[k] > 0 ? { pessimistic: lo, optimistic: hi } : { pessimistic: hi, optimistic: lo };
  }
  return { n, pass, share: n ? pass / n : 0, label: robustnessLabel(n ? pass / n : 0), range };
}

/** Indices i in (a, b) where test(i) differs from test(i - 1): [{i, on}] (on = new state). */
export function transitions(test, a, b) {
  const out = [];
  let prev = !!test(a);
  for (let i = a + 1; i < b; i++) { const cur = !!test(i); if (cur !== prev) { out.push({ i, on: cur }); prev = cur; } }
  return out;
}

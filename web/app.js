// LUNAR//OPS user interface. All science lives in engine.js (decisions) and in the
// precomputed, validated site series produced by pipeline/lunarops/build.py.
import { windowMetrics, evaluate, minimalRelaxation, feasibleWindows, activeConstraints,
         SENSE, LABELS, runEvaluator, ensembleSummary, transitions, thresholdCurve } from "./engine.js";
import { fetchBin } from "./io.js";

const $ = (s) => document.querySelector(s);
const short = (s) => (s.id === "im2-athena" ? "IM-2 site, Mons Mouton" : s.region || s.name);
// CSS custom properties are constant (one theme), so read each one once: getComputedStyle per
// canvas cell / track point was the main cause of the page stuttering.
const _css = new Map();
const css = (v) => { let x = _css.get(v); if (x === undefined) { x = getComputedStyle(document.documentElement).getPropertyValue(v).trim(); _css.set(v, x); } return x; };
// Static parts of a chart are drawn once into an offscreen canvas and reused while only the cursor moves.
function layer(name, key, w, h, draw) {
  state.layers ??= {};
  const dpr = window.devicePixelRatio || 1, c = state.layers[name];
  if (!c || c.key !== key) {
    const oc = document.createElement("canvas"); oc.width = Math.round(w * dpr); oc.height = Math.round(h * dpr);
    const x = oc.getContext("2d"); x.setTransform(dpr, 0, 0, dpr, 0, 0); draw(x);
    state.layers[name] = { key, canvas: oc };
  }
  return state.layers[name].canvas;
}
const DAY = 144;               // 10-min samples per day
const COLORS = { ok: "--ok", frag: "--ok-frag", sun: "--fail-sun", dte: "--fail-dte", blackout: "--fail-blk", shadow: "--fail-shd" };
const FAIL_TEXT = { sun: "not enough sunlight", dte: "not enough Earth link", blackout: "blackout too long", shadow: "darkness too long" };

const state = { meta: null, sites: [], req: null, h: 0, cache: new Map(), tables: null, sel: null, mode: "plan", play: null };

// ---------------------------------------------------------------- data
function loading(done, total, what) {
  const el = $("#verdict");
  if (!el || state.meta) return;
  el.className = "verdict loading";
  el.innerHTML = `<div class="go">LOADING <small>${what}</small></div>
    <div class="loadbar"><i style="width:${Math.round((100 * done) / total)}%"></i></div>
    <div class="sub">${done} of ${total} data files · NASA LOLA skylines, SPICE geometry and robustness ensembles for six sites (≈ 4 MB).</div>`;
}
async function load() {
  loading(0, 1, "site list");
  const meta = await (await fetch("data/sites.json")).json();
  const n = meta.grid.n, nh = meta.heights_m.length;
  const total = meta.sites.length * 2 + meta.sites.filter((s) => s.dem_ensemble).length;
  let done = 0;
  const tick = (what) => loading(++done, total, what);
  const sites = await Promise.all(meta.sites.map(async (s) => {
    const buf = await fetchBin(`data/site_${s.id}.bin`);
    tick(s.region || s.name);
    if (buf.byteLength !== n * (2 * nh + 8)) throw new Error(`bad size for ${s.id}`);
    const u8 = new Uint8Array(buf);
    const f = [], dte = [], who = [];
    for (let k = 0; k < nh; k++) f.push(u8.subarray(k * n, (k + 1) * n));
    for (let k = 0; k < nh; k++) {
      const raw = u8.subarray((nh + k) * n, (nh + k + 1) * n);
      dte.push(raw.map((v) => v & 1));
      who.push(raw.map((v) => v >> 1));
    }
    // azimuths are 0..36000 centidegrees (uint16); elevations are signed (int16)
    const u16 = new Uint16Array(buf, 2 * nh * n, 4 * n), i16 = new Int16Array(buf, 2 * nh * n, 4 * n);
    const pick = (j) => (j % 2 === 0 ? u16 : i16).subarray(j * n, (j + 1) * n);
    let disp = null;
    if (s.dispersion) {
      try {
        const db = new Uint8Array(await fetchBin(`data/disp_${s.id}.bin`));
        tick("landing-error ensembles");
        const nhr = Math.ceil(n / s.dispersion.step_samples), P = s.dispersion.points;
        if (db.length === nh * P * 2 * nhr) {
          disp = [];
          for (let k = 0; k < nh; k++) {
            const pts = [];
            for (let p = 0; p < P; p++) {
              const o = ((k * P + p) * 2) * nhr;
              pts.push({ f: db.subarray(o, o + nhr), dte: db.subarray(o + nhr, o + 2 * nhr) });
            }
            disp.push(pts);
          }
        }
      } catch { disp = null; }
    }
    const fs = meta.f_scale;
    const dispEval = disp && disp.map((pts, k) => pts.map((p, pi) => runEvaluator(Float32Array.from(p.f, (v) => v / fs),
      s.dispersion.step_samples, s.dispersion.runs[k][pi].on, s.dispersion.runs[k][pi].dark)));
    let ens = null;
    if (s.dem_ensemble) {
      try {
        const [ej, eb] = await Promise.all([fetch(`data/clones_${s.id}.json`).then((r) => r.json()),
          fetchBin(`data/clones_${s.id}.bin`)]);
        tick("NASA DEM-error clones");
        const nhr = Math.ceil(n / ej.step_samples), u = new Uint8Array(eb), M = ej.members.length;
        if (u.length === M * nh * nhr) {
          const evals = [];
          for (let k = 0; k < nh; k++) evals.push(ej.members.map((m, mi) => runEvaluator(
            Float32Array.from(u.subarray((mi * nh + k) * nhr, (mi * nh + k + 1) * nhr), (v) => v / fs),
            ej.step_samples, ej.runs[k][mi].on, ej.runs[k][mi].dark)));
          ens = { meta: ej, evals };
        }
      } catch { ens = null; }
    }
    return { ...s, f, dte, who, disp, dispEval, ens, sunAz: pick(0), sunEl: pick(1), earthAz: pick(2), earthEl: pick(3) };
  }));
  let validation = null;
  try { validation = await (await fetch("data/validation.json")).json(); } catch { /* optional */ }
  return { meta, sites, validation };
}

const t0ms = () => Date.parse(state.meta.grid.start_utc + "Z");
const timeOf = (i) => new Date(t0ms() + i * state.meta.grid.step_s * 1000);
const fmtDate = (d) => d.toISOString().slice(0, 10);
const fmtTime = (d) => d.toISOString().slice(0, 16).replace("T", " ") + " UTC";
const fmtH = (h) => (h >= 48 ? `${(h / 24).toFixed(1)} d` : `${h.toFixed(1)} h`);
const horizonAt = (site, az) => {
  const hz = site.horizon[String(state.meta.heights_m[state.h])].elev_cdeg;
  const f = ((az % 360) + 360) % 360 / (360 / hz.length);
  const i0 = Math.floor(f) % hz.length, i1 = (i0 + 1) % hz.length, t = f - Math.floor(f);
  return ((1 - t) * hz[i0] + t * hz[i1]) / 100;
};
const occluderKm = (site, az) => {
  const d = site.horizon[String(state.meta.heights_m[state.h])].dist_m;
  return d[Math.round((((az % 360) + 360) % 360) / (360 / d.length)) % d.length] / 1000;
};

// ---------------------------------------------------------------- requirements
function readForm() {
  const num = (k) => Number($(`#req [name=${k}]`).value);
  const useShadow = $("#req [name=useShadow]").checked;
  $("#req [name=maxShadowH]").disabled = !useShadow;
  state.h = state.meta.heights_m.indexOf(num("heightM"));
  return { durationH: num("durationD") * 24, minSunPct: num("minSunPct"), minDtePct: num("minDtePct"),
           maxBlackoutH: num("maxBlackoutH"), maxShadowH: useShadow ? num("maxShadowH") : null, litThreshold: 0.5 };
}
function showOutputs(req) {
  const o = (k, v) => { const el = document.querySelector(`output[data-for=${k}]`); if (el) el.textContent = v; };
  o("durationD", `${req.durationH / 24} d`); o("minSunPct", `${req.minSunPct}%`); o("minDtePct", `${req.minDtePct}%`);
  o("maxBlackoutH", fmtH(req.maxBlackoutH)); o("maxShadowH", req.maxShadowH == null ? "off" : fmtH(req.maxShadowH));
}

// One stable series object per site and height, so the engine can reuse its duration-independent sums.
function seriesOf(s, h) {
  s._series ??= [];
  return (s._series[h] ??= { id: s.id, dtS: state.meta.grid.step_s, f: Float32Array.from(s.f[h], (v) => v / state.meta.f_scale), dte: s.dte[h] });
}
function compute(fast = false) {
  const req = state.req;
  const key = `${state.h}|${req.durationH}`;
  if (!state.cache.has(key)) state.cache.set(key, state.sites.map((s) => windowMetrics(seriesOf(s, state.h), req, 1)));
  if (state.cache.size > 24) state.cache.delete(state.cache.keys().next().value);      // keep memory bounded
  const T = PROF ? performance.now() : 0;
  state.tables = evaluate(state.cache.get(key), req);
  const T1 = PROF ? performance.now() : 0;
  state.relax = fast ? null : minimalRelaxation(state.tables, req);     // while dragging: only when NO-GO needs it
  const T2 = PROF ? performance.now() : 0;
  state.days = state.tables.map((t, si) => (fast ? bestPerDay(t) : dayCells(t, si)));
  state.robustReady = !fast;
  if (PROF) console.log(`evaluate ${(T1 - T).toFixed(0)} ms · relax ${(T2 - T1).toFixed(0)} ms · days ${(performance.now() - T2).toFixed(0)} ms`);
}
const PROF = /[?&]prof/.test(location.search);

const perHour = () => 3600 / state.meta.grid.step_s;

// Landing-error robustness of one window: share of the 19 dispersion points where it still passes.
function landingShare(s, a, L) {
  if (!s.dispEval) return null;
  const ev = s.dispEval[state.h];
  let ok = 0;
  for (const e of ev) if (e(a, L, state.req, perHour()).feasible) ok++;
  return ok / ev.length;
}

// best window per landing day: feasible with the largest worst-margin, else the smallest relative shortfall;
// feasible days also get their landing-error robustness (cells: robust / passes-but-fragile / fails-by-constraint)
function dayCells(t, si) {
  const cells = bestPerDay(t);
  const s = state.sites[si];
  for (const c of cells) if (c && c.ok) {
    c.share = landingShare(s, t.starts[c.i], t.L);
    c.robust = c.share != null && c.share >= 0.9;
    if (c.robust) c.score += 2e6;
  }
  return cells;
}
function bestPerDay(t) {
  const act = activeConstraints(state.req);
  const keys = Object.keys(act), norm = keys.map((k) => Math.max(Math.abs(act[k]), 1)), M = keys.map((k) => t.margins[k]);
  const nDays = Math.ceil((t.starts[t.starts.length - 1] + 1) / DAY);
  const cells = new Array(nDays);
  for (let i = 0; i < t.starts.length; i++) {
    const d = Math.floor(t.starts[i] / DAY);
    let score, fail = null;
    if (t.feasible[i]) {
      let w = 1e3;
      for (let j = 0; j < keys.length; j++) { const v = M[j][i] / norm[j]; if (v < w) w = v; }
      score = 1e6 + w;
    } else {
      let worst = 0;
      for (let j = 0; j < keys.length; j++) { const v = -M[j][i] / norm[j]; if (v > worst) { worst = v; fail = keys[j]; } }
      score = -worst;
    }
    const c = cells[d];
    if (!c || score > c.score) cells[d] = { i, score, ok: !!t.feasible[i], fail };
  }
  return cells;
}

// ---------------------------------------------------------------- what-if sparklines under the sliders
function renderSparks() {
  document.querySelectorAll("canvas.spark").forEach((cv) => {
    const k = cv.dataset.k, input = cv.previousElementSibling;
    const lo = Number(input.min), hi = Number(input.max), N = 60;
    const xs = Array.from({ length: N + 1 }, (_, i) => lo + ((hi - lo) * i) / N);
    const cur = Number(input.value);
    const all = thresholdCurve(state.tables, state.req, k, [...xs, cur]), ys = all.slice(0, -1), now = all[all.length - 1];
    const ctx = setup(cv, 26), W = cv.clientWidth, H = 26, max = Math.max(...ys, 1);
    const bw = W / (N + 1);
    ys.forEach((y, i) => {
      if (!y) return;
      const h = Math.max(1.5, Math.sqrt(y / max) * (H - 4));
      ctx.fillStyle = css("--yonder"); ctx.globalAlpha = 0.55; ctx.fillRect(i * bw + 0.5, H - h, Math.max(bw - 1, 1), h);
    });
    ctx.globalAlpha = 1;
    const x = ((cur - lo) / (hi - lo)) * (W - bw) + bw / 2;
    ctx.fillStyle = css("--yellow"); ctx.fillRect(x - 1, 0, 2, H);
    cv.title = `${now.toLocaleString("en")} landing hours pass at the current setting`;
  });
}

// ---------------------------------------------------------------- verdict
function renderVerdict() {
  const el = $("#verdict");
  let nWin = 0; const okSites = [];
  for (const t of state.tables) { const w = feasibleWindows(t); nWin += w.length; if (w.length) okSites.push(t.id); }
  const name = (id) => short(state.sites.find((s) => s.id === id));
  if (nWin) {
    el.className = "verdict ok";
    let okDays = 0, robustDays = 0;
    const robustSites = new Set();
    state.days.forEach((row, si) => row.forEach((c) => { if (c && c.ok) { okDays++; if (c.robust) { robustDays++; robustSites.add(si); } } }));
    const rob = !state.robustReady ? "Checking robustness to landing error…" : robustDays
      ? `${robustDays} of ${okDays} feasible landing days still pass at ≥ 90% of points within ${state.sites[0].dispersion?.radius_m ?? 250} m of the target (${[...robustSites].map((i) => short(state.sites[i])).join(", ")}).`
      : `None of the ${okDays} feasible landing days survives a ${state.sites[0].dispersion?.radius_m ?? 250} m landing error at ≥ 90% of nearby points — every solution is fragile.`;
    el.innerHTML = `<div class="go">GO <small>${!state.robustReady ? "checking robustness" : robustDays ? "robust options exist" : "fragile options only"}</small></div>
      <div class="big">${okSites.length} of ${state.sites.length} sites can host this mission — ${nWin} landing window${nWin === 1 ? "" : "s"} in 2027–2028.</div>
      <div>${rob}</div>
      <div class="sub">Feasible at: ${okSites.map(name).join(", ")}. ${robustDays ? "Bright yellow cells are robust; pick one to see the evidence." : "Dim yellow cells pass only at the exact target point; pick one to see the evidence."}</div>`;
  } else {
    el.className = "verdict none";
    state.relax ??= minimalRelaxation(state.tables, state.req);
    const opts = Object.entries(state.relax).filter(([, r]) => r.relaxedTo != null && !r.alreadyFeasible);
    const btns = opts.map(([k, r]) => {
      const from = activeConstraints(state.req)[k];
      const to = k === "sun" || k === "dte" ? Math.floor(r.relaxedTo) : Math.ceil(r.relaxedTo);
      const unit = k === "sun" || k === "dte" ? "%" : " h";
      return `<button data-k="${k}" data-v="${to}">${LABELS[k]}: <b>${from}${unit} → ${to}${unit}</b> (${name(r.at.site)})</button>`;
    }).join("");
    const useless = Object.entries(state.relax).filter(([, r]) => r.relaxedTo == null).map(([k]) => ({ sun: "the sunlight minimum", dte: "the DTE minimum", blackout: "the blackout limit", shadow: "the darkness limit" }[k]));
    el.innerHTML = `<div class="go">NO-GO <small>no site · no date</small></div>
      <div class="big">No site meets all requirements.</div>
      <div>${opts.length ? "Smallest single change that makes a mission possible (click to apply):" : "No single relaxation is enough — at least two requirements must change."}</div>
      <div class="relax">${btns}</div>
      ${useless.length ? `<div class="sub">Relaxing ${useless.join(" or ")} alone would not help: another requirement still fails everywhere.</div>` : ""}
      <div id="alts" class="alts"><span class="hint">Checking engineering alternatives…</span></div>`;
    el.querySelectorAll(".relax button").forEach((b) => b.addEventListener("click", () => applyRelax(b.dataset.k, Number(b.dataset.v))));
    scheduleAlternatives();
  }
}

// ---------------------------------------------------------------- engineering alternatives (keep every requirement)
// Stage 2, 2.16: instead of lowering a requirement, change the design or the plan.
function feasibleCount(h, durationH) {
  const req = { ...state.req, durationH };
  const key = `${h}|${durationH}`;
  const base = state.cache.get(key) || state.sites.map((s) => windowMetrics(seriesOf(s, h), req, 1));
  const tabs = evaluate(base.map((t) => ({ ...t, _buf: undefined })), req);   // copies with own buffers: the live tables keep their margins
  let n = 0; const sites = [];
  tabs.forEach((t, si) => { const w = feasibleWindows(t); n += w.length; if (w.length) sites.push(si); });
  return { n, sites };
}
let altToken = 0;
function scheduleAlternatives() {
  const token = ++altToken, key = JSON.stringify([state.h, state.req]);
  const live = () => token === altToken && key === JSON.stringify([state.h, state.req]) && $("#alts");
  const pause = () => new Promise((r) => setTimeout(r, 0));          // yield to the browser between slices
  (async () => {
    await new Promise((r) => setTimeout(r, 200));                   // wait until the sliders rest
    if (!live()) return;
    const out = [], D = state.req.durationH / 24, names = (sites) => sites.map((i) => short(state.sites[i])).join(", ");
    const other = state.meta.heights_m.findIndex((_, k) => k !== state.h);
    if (other >= 0) {
      const r = feasibleCount(other, state.req.durationH), z = state.meta.heights_m[other];
      out.push(r.n ? `<button data-h="${z}">Mount panels &amp; antenna at <b>${z} m</b> instead of ${state.meta.heights_m[state.h]} m → <b>${r.n}</b> window${r.n === 1 ? "" : "s"} (${names(r.sites)})</button>`
                   : `<span class="hint">A ${z} m mast alone does not help.</span>`);
    }
    for (let d = D - 1; d >= 1; d--) {
      await pause();
      if (!live()) return;
      const r = feasibleCount(state.h, d * 24);
      if (r.n) { out.push(`<button data-d="${d}">Shorten the surface mission to <b>${d} days</b> → <b>${r.n}</b> window${r.n === 1 ? "" : "s"} (${names(r.sites)})</button>`); break; }
      if (d === 1) out.push(`<span class="hint">No shorter mission works either.</span>`);
    }
    if (!live()) return;
    $("#alts").innerHTML = `<div>Or keep every requirement and change the design or the plan:</div><div class="relax">${out.join("")}</div>`;
    $("#alts").querySelectorAll("button").forEach((btn) => btn.addEventListener("click", () => {
      if (btn.dataset.h) $("#req [name=heightM]").value = btn.dataset.h;
      if (btn.dataset.d) $("#req [name=durationD]").value = btn.dataset.d;
      update(false);
    }));
  })();
}

// ---------------------------------------------------------------- site x date map
const MAP = { left: 150, top: 22, rowH: 30 };
function renderMap() {
  const cv = $("#map"), ctx = setup(cv, MAP.top + state.sites.length * MAP.rowH + 26);
  const W = cv.clientWidth, nDays = state.days[0].length;
  const cw = (W - MAP.left - 8) / nDays;
  ctx.font = "12px Overpass, system-ui"; ctx.textBaseline = "middle";
  state.sites.forEach((s, r) => {
    const y = MAP.top + r * MAP.rowH;
    ctx.fillStyle = css("--ink"); ctx.textAlign = "right";
    ctx.fillText(short(s), MAP.left - 10, y + MAP.rowH / 2);
    state.days[r].forEach((c, d) => {
      ctx.fillStyle = css(c ? (c.ok ? (c.robust || c.share == null ? COLORS.ok : "--ok-frag") : COLORS[c.fail] || "--none") : "--none");
      ctx.fillRect(MAP.left + d * cw, y + 4, Math.max(cw - 0.25, 0.6), MAP.rowH - 8);
    });
  });
  // month ticks
  ctx.fillStyle = css("--ink-2"); ctx.textAlign = "left"; ctx.font = "11px Overpass, system-ui";
  const start = t0ms();
  for (let d = 0; d < nDays; d++) {
    const dt = new Date(start + d * 86400e3);
    if (dt.getUTCDate() === 1) {
      const x = MAP.left + d * cw;
      ctx.fillRect(x, MAP.top - 4, 1, state.sites.length * MAP.rowH + 4);
      const m = dt.getUTCMonth();
      if (m % 3 === 0) ctx.fillText(m === 0 ? String(dt.getUTCFullYear()) : dt.toLocaleString("en", { month: "short", timeZone: "UTC" }), x + 3, MAP.top - 10);
    }
  }
  if (state.sel) {
    const r = state.sites.findIndex((s) => s.id === state.sel.site);
    const d = Math.floor(state.sel.start / DAY);
    ctx.strokeStyle = css("--ink"); ctx.lineWidth = 2;
    ctx.strokeRect(MAP.left + d * cw - 2, MAP.top + r * MAP.rowH + 2, cw + 4, MAP.rowH - 4);
  }
  const leg = [["ok", "meets all, robust to landing error"], ["frag", "meets all at the target point only"], ["sun", FAIL_TEXT.sun], ["dte", FAIL_TEXT.dte], ["blackout", FAIL_TEXT.blackout], ["shadow", FAIL_TEXT.shadow]];
  // text alternative for screen readers: per site, how many landing days pass
  $("#map-summary").textContent = "Feasible landing days per site: " + state.sites.map((x, r) => {
    const row = state.days[r], ok = row.filter((c) => c && c.ok).length, rb = row.filter((c) => c && c.robust).length;
    return `${short(x)} ${ok} of ${row.length}${ok ? ` (${rb} robust to landing error)` : ""}`;
  }).join("; ") + ".";
  $("#map-legend").innerHTML = leg.map(([k, t]) => `<span><i style="background:var(${COLORS[k]})"></i>${t}</span>`).join("");
}
function mapHit(ev) {
  const cv = $("#map"), rect = cv.getBoundingClientRect();
  const x = ev.clientX - rect.left, y = ev.clientY - rect.top;
  const nDays = state.days[0].length, cw = (cv.clientWidth - MAP.left - 8) / nDays;
  const r = Math.floor((y - MAP.top) / MAP.rowH), d = Math.floor((x - MAP.left) / cw);
  if (r < 0 || r >= state.sites.length || d < 0 || d >= nDays) return null;
  return { r, d, x, y, cell: state.days[r][d] };
}

// ---------------------------------------------------------------- evidence + explanations
function explainInterval(site, a, b, kind) {
  // Classify why the Sun is dark or the link is down, at the middle of the interval.
  // Earth's centre stands in for the DSN antenna direction (they differ by < 1 deg).
  const mid = Math.floor((a + b) / 2);
  const body = kind === "shadow" ? "Sun" : "Earth";
  const el = (kind === "shadow" ? site.sunEl : site.earthEl)[mid] / 100;
  const az = (kind === "shadow" ? site.sunAz : site.earthAz)[mid] / 100;
  const hz = horizonAt(site, az), dKm = occluderKm(site, az);
  const km = dKm < 1 ? `${Math.round(dKm * 1000)} m` : `${dKm.toFixed(1)} km`;
  const what = dKm < 1 ? "the local slope" : "terrain";
  const caveat = dKm < 0.1 ? " — closer than LOLA's effective resolution (≈15–35 m) can pin down; treat as uncertain" : "";
  if (kind === "dte" && el >= hz) return "Earth is above the skyline, but no DSN antenna sees the Moon at 6° or more";
  if (el >= 0) return `${body} is ${el.toFixed(2)}° above the mathematical horizon but hidden by ${what} ${km} away (az ${az.toFixed(0)}°, skyline ${hz.toFixed(2)}°)${caveat}`;
  if (hz <= 0) return `${body} is ${Math.abs(el).toFixed(2)}° below the mathematical horizon${kind === "dte" ? " (libration)" : ""}; even from this elevated site the skyline at az ${az.toFixed(0)}° is ${hz.toFixed(2)}°`;
  return `${body} is ${Math.abs(el).toFixed(2)}° below the mathematical horizon and also behind ${what} ${km} away (az ${az.toFixed(0)}°, skyline ${hz.toFixed(2)}°)${caveat}`;
}
function longestRun(arr, a, b, pred) {
  let best = [a, a], s = -1;
  for (let i = a; i <= b; i++) {
    const on = i < b && pred(arr[i]);
    if (on && s < 0) s = i;
    if (!on && s >= 0) { if (i - s > best[1] - best[0]) best = [s, i]; s = -1; }
  }
  return best;
}
function renderEvidence() {
  const box = $("#evidence");
  if (!state.sel) { box.innerHTML = `<p class="hint">Select a cell on the map.</p>`; return; }
  const si = state.sites.findIndex((s) => s.id === state.sel.site), s = state.sites[si], t = state.tables[si];
  const i = state.sel.k, a = t.starts[i], b = a + t.L;
  const act = activeConstraints(state.req);
  const row = (k, val, unit) => {
    const has = k in act, pass = has ? t.margins[k][i] >= -1e-9 : null;
    const req = has ? `${SENSE[k] > 0 ? "≥" : "≤"} ${act[k]}${unit}` : "—";
    const m = has ? `${t.margins[k][i] >= 0 ? "+" : ""}${t.margins[k][i].toFixed(1)}${unit}` : "";
    return `<tr><td>${LABELS[k]}</td><td class="num">${val}${unit}</td><td class="num">${req}</td><td class="num">${m}</td>
      <td>${has ? `<span class="pill ${pass ? "pass" : "fail"}">${pass ? "PASS" : "FAIL"}</span>` : `<span class="pill na">not required</span>`}</td></tr>`;
  };
  const M = t.metrics;
  const bl = longestRun(s.dte[state.h], a, b, (v) => !v);
  const sh = longestRun(s.f[state.h], a, b, (v) => v === 0);
  const why = [];
  if (bl[1] > bl[0]) why.push(`Longest blackout ${fmtH((bl[1] - bl[0]) / 6)} from ${fmtTime(timeOf(bl[0]))}: ${explainInterval(s, bl[0], bl[1], "dte")}.`);
  if (sh[1] > sh[0]) why.push(`Longest darkness ${fmtH((sh[1] - sh[0]) / 6)} from ${fmtTime(timeOf(sh[0]))}: ${explainInterval(s, sh[0], sh[1], "shadow")}.`);
  const ok = t.feasible[i];
  $("#ev-sub").textContent = `${short(s)} · land ${fmtTime(timeOf(a))} · ${state.req.durationH / 24} days · panels ${state.meta.heights_m[state.h]} m`;
  box.innerHTML = `<div class="big" style="font-weight:650;margin-bottom:6px">${ok ? "MEETS ALL REQUIREMENTS" : "FAILS: " + t.failingAt(i).map((k) => FAIL_TEXT[k]).join(", ")}</div>
    <table class="ev"><thead><tr><th>Metric</th><th>Value</th><th>Required</th><th>Margin</th><th></th></tr></thead><tbody>
    ${row("sun", M.sun[i].toFixed(1), "%")}${row("dte", M.dte[i].toFixed(1), "%")}
    ${row("blackout", M.blackout[i].toFixed(1), " h")}${row("shadow", M.shadow[i].toFixed(1), " h")}
    <tr><td>Power + link at once</td><td class="num">${M.overlap[i].toFixed(1)}%</td><td class="num">—</td><td></td><td><span class="pill na">info</span></td></tr>
    </tbody></table>
    <ul class="why">${why.map((w) => `<li>${w}</li>`).join("")}</ul>
    ${robustnessHtml(s, a, t.L)}
    <div class="prov">Site: ${s.lat.toFixed(4)}°, ${s.lon.toFixed(4)}° E, ${s.h_site_m} m above the 1737.4 km sphere. Source: ${s.source}.</div>
    <div class="plain explain-only">${ok ? "Everything this mission needs is available here: the solar panels see the Sun most of the time and Earth is in view often enough to send data home." :
      "This landing date does not work. " + t.failingAt(i).map((k) => ({ sun: "Hills or the low Sun block the light the panels need.", dte: "Earth spends too much time below this site's horizon.", blackout: "There is a long stretch with no way to talk to Earth.", shadow: "There is a long dark period the battery would have to survive." }[k])).join(" ")}</div>`;
}

function robustnessHtml(s, a, L) {
  const perH = perHour(), act = activeConstraints(state.req);
  const fmt = (k, v) => (k === "sun" || k === "dte" ? `${v.toFixed(0)}%` : fmtH(v));
  const keys = ["sun", "dte", "blackout", "shadow"].filter((k) => k in act || k !== "shadow");
  const SHORT = { sun: "sun", dte: "link", blackout: "blackout", shadow: "dark" };
  const span = (sum, which) => keys.map((k) => {
    const v = sum.range[k][which], bad = k in act && SENSE[k] * (v - act[k]) < -1e-9;
    return `<span class="m ${bad ? "bad" : ""}">${SHORT[k]} ${fmt(k, v)}</span>`;
  }).join("");
  const pill = (lbl) => `<span class="pill ${lbl === "ROBUST" ? "pass" : lbl === "FRAGILE" ? "fail" : "na"}">${lbl}</span>`;
  const rows = [];
  if (s.dispEval) {
    const res = s.dispEval[state.h].map((e) => e(a, L, state.req, perH));
    const sum = ensembleSummary(res);
    let worst = null;
    res.forEach((r, k) => { if (!r.feasible) { const m = Math.min(...r.failing.map((f) => r.margins[f] / Math.max(Math.abs(act[f]), 1))); if (!worst || m < worst.m) worst = { k, m, f: r.failing[0] }; } });
    const off = worst ? s.dispersion.offsets_m[worst.k] : null;
    rows.push(`<tr><th scope="row">Landing error ±${s.dispersion.radius_m} m<div class="hint">${s.dispersion.points} landing points</div></th>
      <td class="num">${sum.pass}/${sum.n}</td><td>${span(sum, "pessimistic")}${worst ? `<div class="hint">worst point ${Math.hypot(off[0], off[1]).toFixed(0)} m off target: ${FAIL_TEXT[worst.f]}</div>` : ""}</td>
      <td>${span(sum, "optimistic")}</td><td>${pill(sum.label)}</td></tr>`);
  } else rows.push(`<tr><th scope="row">Landing error</th><td colspan="4" class="hint">not computed for this site</td></tr>`);
  if (s.ens) {
    const res = s.ens.evals[state.h].map((e) => e(a, L, state.req, perH));
    const nom = res[0], sum = ensembleSummary(res.slice(1));
    rows.push(`<tr><th scope="row">Terrain (DEM) error<div class="hint">${sum.n} NASA error clones, PGDA ${s.ens.meta.tile}</div></th>
      <td class="num">${sum.pass}/${sum.n}</td><td>${span(sum, "pessimistic")}</td><td>${span(sum, "optimistic")}</td>
      <td>${sum.n >= 20 ? pill(sum.label) : `<span class="pill na" title="fewer than 20 clones processed">PRELIMINARY</span>`}</td></tr>`);
    rows.push(`<tr><td colspan="5" class="hint">Clones perturb NASA's 2021 5 m site DEM within its published error (Barker et al. 2021). On that DEM's nominal surface this window ${nom.feasible ? "passes" : "fails (" + nom.failing.map((k) => FAIL_TEXT[k]).join(", ") + ")"}; the main result above uses the newer 2023 10 m DEM.</td></tr>`);
  } else rows.push(`<tr><th scope="row">Terrain (DEM) error</th><td colspan="4" class="hint">${s.clones
    ? `NASA publishes 100 error clones for this site (PGDA ${s.clones}); ensemble not processed yet — not assessed`
    : "no NASA error ensemble exists for this site — not assessed"}</td></tr>`);
  return `<h3 class="sec">Robustness <span class="hint">— is the answer still true if…</span></h3>
    <div class="rob-wrap"><table class="ev rob"><thead><tr><th></th><th>Holds at</th><th>Pessimistic</th><th>Optimistic</th><th></th></tr></thead><tbody>${rows.join("")}</tbody></table></div>
    <div class="prov">Each point/clone gets its own terrain horizon; link and darkness at full 10-min resolution, sunlight averaged hourly. IM-2 landed ~250 m from its target. ROBUST ≥ 90% hold, MARGINAL 50–90%, FRAGILE &lt; 50% (our convention). An approximation: boulders below DEM resolution and lander tilt are not modelled.</div>`;
}

// ---------------------------------------------------------------- site comparison (same landing time)
function renderCompare() {
  if (!state.sel) return;
  const k = state.sel.k, act = activeConstraints(state.req), keys = ["sun", "dte", "blackout", "shadow"];
  const a = state.tables[0].starts[k];
  const cell = (t, key) => {
    const v = t.metrics[key][k], txt = key === "sun" || key === "dte" ? `${v.toFixed(1)}%` : fmtH(v);
    const bad = key in act && t.margins[key][k] < -1e-9;
    const m = key in act ? t.margins[key][k] : null;
    const mt = m == null ? "" : `<div class="m">${m >= 0 ? "+" : "−"}${key === "sun" || key === "dte" ? Math.abs(m).toFixed(1) + " pp" : fmtH(Math.abs(m))}</div>`;
    return `<td class="num ${bad ? "bad" : ""}">${txt}${mt}</td>`;
  };
  const rows = state.tables.map((t, si) => {
    const s = state.sites[si], ok = t.feasible[k], share = ok ? landingShare(s, a, t.L) : null;
    const rob = share == null ? "—" : `${Math.round(share * s.dispersion.points)}/${s.dispersion.points}`;
    const sel = s.id === state.sel.site;
    return `<tr class="${sel ? "sel" : ""}"><th scope="row"><button class="link" data-si="${si}" aria-pressed="${sel}">${short(s)}</button></th>
      ${keys.map((key) => cell(t, key)).join("")}<td class="num">${rob}</td>
      <td><span class="pill ${ok ? "pass" : "fail"}">${ok ? "PASS" : "FAIL"}</span></td></tr>`;
  }).join("");
  const req = (key) => (key in act ? `<div class="m">${SENSE[key] > 0 ? "≥" : "≤"} ${act[key]}${key === "sun" || key === "dte" ? "%" : " h"}</div>` : `<div class="m">not required</div>`);
  $("#compare").innerHTML = `<table class="ev cmp"><thead><tr><th>Site</th>${keys.map((key) => `<th class="num">${LABELS[key]}${req(key)}</th>`).join("")}<th class="num">Holds within 250 m</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
  $("#cmp-sub").textContent = `land ${fmtTime(timeOf(a))} · ${state.req.durationH / 24} days · panels ${state.meta.heights_m[state.h]} m`;
  $("#compare").querySelectorAll("button[data-si]").forEach((btn) => btn.addEventListener("click", () => {
    const si = Number(btn.dataset.si);
    state.sel = { site: state.sites[si].id, k, start: a };
    renderAll();
  }));
}

// ---------------------------------------------------------------- pareto
function renderPareto() {
  const cv = $("#pareto"), ctx = setup(cv, 260);
  const W = cv.clientWidth, H = 260, L = 44, B = 32, T = 10, R = 12;
  const X = (v) => L + (v / 100) * (W - L - R), Y = (v) => H - B - (v / 100) * (H - B - T);
  ctx.strokeStyle = css("--grid"); ctx.fillStyle = css("--ink-2"); ctx.font = "11px Overpass, system-ui"; ctx.lineWidth = 1;
  for (let v = 0; v <= 100; v += 25) {
    ctx.beginPath(); ctx.moveTo(X(v), Y(0)); ctx.lineTo(X(v), Y(100)); ctx.moveTo(X(0), Y(v)); ctx.lineTo(X(100), Y(v)); ctx.stroke();
    ctx.textAlign = "center"; ctx.fillText(v + "%", X(v), H - B + 14); ctx.textAlign = "right"; ctx.fillText(v + "%", L - 6, Y(v) + 4);
  }
  ctx.textAlign = "center"; ctx.fillText("average sunlight on panels →", X(50), H - 4);
  ctx.save(); ctx.translate(11, Y(50)); ctx.rotate(-Math.PI / 2); ctx.fillText("time with DTE link →", 0, 0); ctx.restore();
  const req = activeConstraints(state.req);
  ctx.fillStyle = css("--ok"); ctx.globalAlpha = 0.08;
  ctx.fillRect(X(req.sun ?? 0), Y(100), X(100) - X(req.sun ?? 0), Y(req.dte ?? 0) - Y(100)); ctx.globalAlpha = 1;
  const best = [];
  state.tables.forEach((t, si) => {
    const sel = state.sel && state.sel.site === t.id;
    ctx.fillStyle = css(sel ? "--ink" : "--ink-2"); ctx.globalAlpha = sel ? 0.35 : 0.12;
    ctx.beginPath();                                     // one path per site instead of one per dot
    for (const c of state.days[si]) if (c) { const x = X(t.metrics.sun[c.i]), y = Y(t.metrics.dte[c.i]); ctx.moveTo(x + 1.6, y); ctx.arc(x, y, 1.6, 0, 7); }
    ctx.fill();
    ctx.globalAlpha = 1;
  });
  // labelled points: each site's 2-year average (the physical trade-off, independent of the mission length)
  const hk = String(state.meta.heights_m[state.h]);
  state.sites.forEach((site, si) => best.push({ s: site, x: site.summary[hk].sun_avg_pct, y: site.summary[hk].dte_pct, sel: state.sel && state.sel.site === site.id }));
  // numbered points; the legend below names them (labels collided inside the dense 70-85 % cluster)
  ctx.font = "600 11px Overpass, system-ui"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  best.forEach((p, k) => {
    ctx.fillStyle = css(p.sel ? "--sun" : "--ink"); ctx.beginPath(); ctx.arc(X(p.x), Y(p.y), p.sel ? 8 : 7, 0, 7); ctx.fill();
    ctx.fillStyle = css("--panel"); ctx.fillText(String(k + 1), X(p.x), Y(p.y) + 0.5);
  });
  ctx.textBaseline = "alphabetic";
  $("#pareto-legend").innerHTML = best.map((p, k) => `<li class="${p.sel ? "sel" : ""}"><b>${k + 1}</b> ${short(p.s)} <span>${p.x.toFixed(0)}% / ${p.y.toFixed(0)}%</span></li>`).join("");
  $("#pareto-hint").textContent = "Numbered points: each site’s average over 2027–2028 (sunlight / DTE link). Faint dots: best landing per day for the current mission length. Green box: what the requirements accept. More sunlight usually means less Earth in view — the trade-off is physical, not a scoring artefact.";
}

// ---------------------------------------------------------------- timeline
const earthUp = (s, i) => s.earthEl[i] / 100 > horizonAt(s, s.earthAz[i] / 100);
const EVENT_TEXT = {
  sun: ["Sun hidden", "Sun appears over the skyline"],
  earth: ["Earthset behind the skyline", "Earthrise over the skyline"],
  dte: ["DTE link lost", "DTE link available"],
};
// Events in the selected window. Flicker shorter than 30 min (a body grazing the skyline) is merged.
function windowEvents(s, a, b) {
  const key = `${s.id}|${a}|${b}|${state.h}`;
  if (state.evKey === key) return state.events;
  const f = s.f[state.h], dte = s.dte[state.h], MIN = 3;
  const debounce = (ev) => {
    const out = [];
    for (let j = 0; j < ev.length; j++) {
      const next = ev[j + 1];
      if (next && next.i - ev[j].i < MIN) { j++; continue; }          // on-off within 30 min: drop both
      out.push(ev[j]);
    }
    return out.filter((e, j) => j === 0 || e.on !== out[j - 1].on);
  };
  const ev = [];
  for (const [kind, test] of [["sun", (i) => f[i] > 0], ["earth", (i) => earthUp(s, i)], ["dte", (i) => dte[i]]])
    for (const e of debounce(transitions(test, a, b))) ev.push({ ...e, kind, text: EVENT_TEXT[kind][e.on ? 1 : 0] });
  ev.sort((x, y) => x.i - y.i);
  state.evKey = key; state.events = ev;
  return ev;
}
const TL_ROWS = [["Sunlight on panels", 14, 40], ["Earth above skyline", 64, 18], ["Earth link (DTE)", 90, 18], ["Power + link", 116, 18], ["Darkness", 142, 18]];
function renderTimeline(pos) {
  if (!state.sel) return;
  const cv = $("#timeline"), ctx = setup(cv, 196);
  const si = state.sites.findIndex((s) => s.id === state.sel.site), s = state.sites[si], t = state.tables[si];
  const a = t.starts[state.sel.k], b = a + t.L, W = cv.clientWidth, L = 140, R = 10;
  const X = (i) => L + ((i - a) / (b - a)) * (W - L - R);
  const f = s.f[state.h], dte = s.dte[state.h], fs = state.meta.f_scale;
  const ev = windowEvents(s, a, b);
  const bg = layer("timeline", `${s.id}|${a}|${b}|${state.h}|${W}|${devicePixelRatio}|${state.req.litThreshold}`, W, 196, (ctx) => {
    ctx.font = "12px Overpass, system-ui"; ctx.textAlign = "right"; ctx.fillStyle = css("--ink");
    TL_ROWS.forEach(([lbl, y, h]) => ctx.fillText(lbl, L - 10, y + h / 2 + 4));
    ctx.fillStyle = css("--sun");
    for (let i = a; i < b; i++) { const h = (f[i] / fs) * 40; if (h) ctx.fillRect(X(i), 14 + 40 - h, X(i + 1) - X(i) + 0.5, h); }
    // one rectangle per run of consecutive samples
    const band = ([, y, h], pred, color) => {
      ctx.fillStyle = css(color);
      for (let i = a; i < b; i++) { if (!pred(i)) continue; let j = i; while (j + 1 < b && pred(j + 1)) j++; ctx.fillRect(X(i), y, X(j + 1) - X(i) + 0.5, h); i = j; }
    };
    band(TL_ROWS[1], (i) => earthUp(s, i), "--earth-up");
    band(TL_ROWS[2], (i) => dte[i], "--earth");
    band(TL_ROWS[3], (i) => dte[i] && f[i] / fs >= state.req.litThreshold, "--ok");
    band(TL_ROWS[4], (i) => f[i] === 0, "--fail-shd");
    ctx.fillStyle = css("--ink-2"); ctx.textAlign = "center"; ctx.font = "11px Overpass, system-ui";
    const days = state.req.durationH / 24, every = days > 21 ? 7 : days > 10 ? 2 : 1;
    for (let d = 0; d <= days; d += every) {
      const i = a + d * DAY; ctx.fillRect(X(i), 10, 1, 154);
      ctx.textAlign = d === 0 ? "left" : X(i) > W - 30 ? "right" : "center"; ctx.fillText(`day ${d}`, X(i), 182);
    }
    for (const e of ev) {
      const y = e.kind === "sun" ? 8 : e.kind === "earth" ? 60 : 86;
      ctx.fillStyle = css(e.kind === "sun" ? "--sun" : "--earth");
      ctx.beginPath(); ctx.moveTo(X(e.i), y + 4); ctx.lineTo(X(e.i) - 3, y); ctx.lineTo(X(e.i) + 3, y); ctx.fill();
    }
  });
  ctx.drawImage(bg, 0, 0, W, 196);
  const p = a + Math.round((pos ?? 0) * (b - a - 1));
  ctx.fillStyle = css("--ink"); ctx.fillRect(X(p) - 1, 6, 2, 162);
  state.cursor = p;
  const sAz = s.sunAz[p] / 100, sEl = s.sunEl[p] / 100, eAz = s.earthAz[p] / 100, eEl = s.earthEl[p] / 100;
  const st = s.who[state.h][p], stName = st ? state.meta.stations[st - 1] : "none";
  const nxt = ev.find((e) => e.i > p), prv = [...ev].reverse().find((e) => e.i <= p);
  $("#now").innerHTML = `<span><b>${fmtTime(timeOf(p))}</b> · day ${((p - a) / DAY).toFixed(2)}</span>
    <span>Sun az <b>${sAz.toFixed(1)}°</b> el <b>${sEl.toFixed(2)}°</b> · skyline <b>${horizonAt(s, sAz).toFixed(2)}°</b> · disc visible <b>${Math.round((f[p] / fs) * 100)}%</b></span>
    <span>Earth az <b>${eAz.toFixed(1)}°</b> el <b>${eEl.toFixed(2)}°</b> · skyline <b>${horizonAt(s, eAz).toFixed(2)}°</b> · DTE <b>${dte[p] ? "via " + stName : "no"}</b></span>
    <span>${prv ? `last event: <b>${prv.text}</b> ${fmtH((p - prv.i) / 6)} ago` : "no event yet"}${nxt ? ` · next: <b>${nxt.text}</b> in ${fmtH((nxt.i - p) / 6)}` : ""} · ${ev.length} events</span>`;
  $("#tl-sub").textContent = `${short(s)} · ${fmtDate(timeOf(a))} → ${fmtDate(timeOf(b))}`;
}
function jumpEvent(dir) {
  if (!state.sel || !state.events) return;
  const si = state.sites.findIndex((s) => s.id === state.sel.site), t = state.tables[si];
  const a = t.starts[state.sel.k], b = a + t.L, p = state.cursor ?? a;
  const e = dir > 0 ? state.events.find((x) => x.i > p) : [...state.events].reverse().find((x) => x.i < p);
  if (!e) return;
  $("#scrub").value = Math.round(((e.i - a) / (b - a - 1)) * 1000);
  renderTimeline(Number($("#scrub").value) / 1000); renderHorizon(); time3d();
}

// ---------------------------------------------------------------- horizon panorama
function renderHorizon() {
  if (!state.sel) return;
  const cv = $("#horizon"), ctx = setup(cv, 240);
  const si = state.sites.findIndex((s) => s.id === state.sel.site), s = state.sites[si], t = state.tables[si];
  const a = t.starts[state.sel.k], b = a + t.L;
  const W = cv.clientWidth, H = 240, L = 40, R = 10, T = 10, B = 26;
  const hz = s.horizon[String(state.meta.heights_m[state.h])].elev_cdeg.map((v) => v / 100);
  let lo = Math.min(...hz, -1), hi = Math.max(...hz, 1);
  for (let i = a; i < b; i += 6) { lo = Math.min(lo, s.sunEl[i] / 100, s.earthEl[i] / 100); hi = Math.max(hi, s.sunEl[i] / 100, s.earthEl[i] / 100); }
  lo = Math.floor(lo - 0.5); hi = Math.ceil(hi + 0.5);
  const X = (az) => L + (az / 360) * (W - L - R), Y = (el) => T + ((hi - el) / (hi - lo)) * (H - T - B);
  const sunVis = (i) => s.f[state.h][i] > 0, earthVis = (i) => earthUp(s, i);
  const bg = layer("horizon", `${s.id}|${a}|${b}|${state.h}|${W}|${devicePixelRatio}`, W, H, (ctx) => {
    ctx.strokeStyle = css("--grid"); ctx.fillStyle = css("--ink-2"); ctx.font = "11px Overpass, system-ui"; ctx.lineWidth = 1;
    for (let az = 0; az <= 360; az += 45) { ctx.beginPath(); ctx.moveTo(X(az), T); ctx.lineTo(X(az), H - B); ctx.stroke(); ctx.textAlign = "center"; ctx.fillText(["N", "45", "E", "135", "S", "225", "W", "315", "N"][az / 45], X(az), H - 8); }
    for (let el = lo; el <= hi; el += Math.max(1, Math.round((hi - lo) / 6))) { ctx.textAlign = "right"; ctx.fillText(el + "°", L - 6, Y(el) + 4); }
    ctx.fillStyle = css("--terrain"); ctx.beginPath(); ctx.moveTo(X(0), Y(lo));
    hz.forEach((e, k) => ctx.lineTo(X((k * 360) / hz.length), Y(e))); ctx.lineTo(X(360), Y(hz[0])); ctx.lineTo(X(360), Y(lo)); ctx.closePath(); ctx.fill();
    ctx.strokeStyle = css("--yonder"); ctx.lineWidth = 1.2; ctx.beginPath();
    hz.forEach((e, k) => (k ? ctx.lineTo : ctx.moveTo).call(ctx, X((k * 360) / hz.length), Y(e))); ctx.stroke();
    ctx.strokeStyle = css("--ink-2"); ctx.setLineDash([5, 4]); ctx.beginPath(); ctx.moveTo(X(0), Y(0)); ctx.lineTo(X(360), Y(0)); ctx.stroke(); ctx.setLineDash([]);
    // geometric visibility (centre above 0 deg) vs terrain-obstructed visibility (our skyline)
    const track = (azA, elA, color, visible) => {
      ctx.strokeStyle = css("--blocked"); ctx.lineWidth = 1.2; ctx.beginPath();
      for (let i = a; i < b; i += 3) {
        if (elA[i] > 0 && !visible(i)) {                  // above the mathematical horizon, blocked by terrain
          const x = X(azA[i] / 100), y = Y(elA[i] / 100);
          ctx.moveTo(x - 2, y - 2); ctx.lineTo(x + 2, y + 2); ctx.moveTo(x + 2, y - 2); ctx.lineTo(x - 2, y + 2);
        }
      }
      ctx.stroke();
      ctx.fillStyle = css(color);
      for (const [alpha, want] of [[0.22, false], [0.9, true]]) {
        ctx.globalAlpha = alpha;
        for (let i = a; i < b; i += 3) {
          const vis = visible(i);
          if (vis !== want || (elA[i] > 0 && !vis)) continue;
          ctx.fillRect(X(azA[i] / 100) - 1, Y(elA[i] / 100) - 1, 2.2, 2.2);
        }
      }
      ctx.globalAlpha = 1;
    };
    track(s.sunAz, s.sunEl, "--sun", sunVis);
    track(s.earthAz, s.earthEl, "--earth", earthVis);
  });
  ctx.drawImage(bg, 0, 0, W, H);
  const p = state.cursor ?? a;
  const dot = (az, el, color, r) => { ctx.fillStyle = css(color); ctx.strokeStyle = css("--panel"); ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(X(az), Y(el), r, 0, 7); ctx.fill(); ctx.stroke(); };
  dot(s.sunAz[p] / 100, s.sunEl[p] / 100, "--sun", 6); dot(s.earthAz[p] / 100, s.earthEl[p] / 100, "--earth", 6);
  $("#hz-sub").textContent = "Sun path (gold) and Earth path (blue) during the mission; faint = below the horizon and hidden; × = above the mathematical horizon but blocked by terrain";
  const key = `${s.id}|${a}|${b}|${state.h}`;
  if (state.hzKey !== key) {
    state.hzKey = key;
    const stats = (elA, vis) => {
      let geo = 0, v = 0, blocked = 0, below = 0;
      for (let i = a; i < b; i++) { const g = elA[i] > 0, x = vis(i); geo += g; v += x; blocked += g && !x; below += !g && x; }
      const n = b - a, pc = (x) => `${((100 * x) / n).toFixed(1)}%`;
      return [pc(geo), pc(v), pc(blocked), pc(below)];
    };
    const sR = stats(s.sunEl, sunVis), eR = stats(s.earthEl, earthVis);
    $("#hz-stats").innerHTML = `<table class="ev"><thead><tr><th>Share of mission time</th><th>Geometric: above 0°</th><th>With terrain: visible</th><th>Blocked by terrain</th><th>Visible although below 0°</th></tr></thead>
      <tbody><tr><th scope="row">Sun (any part of disc)</th>${sR.map((x) => `<td class="num">${x}</td>`).join("")}</tr>
      <tr><th scope="row">Earth (centre)</th>${eR.map((x) => `<td class="num">${x}</td>`).join("")}</tr></tbody></table>`;
  }
}

// ---------------------------------------------------------------- south-pole locator (status board)
// True positions on the south polar stereographic grid; 0° longitude (the Earth-facing side) at the top.
const LOC = { edge: -83.6, size: 220 };
function locXY(lat, lon) {
  const r = (phi) => Math.tan(Math.PI / 4 + (phi * Math.PI) / 360);          // stereographic radius, south aspect
  const k = (LOC.size / 2 - 14) / r(LOC.edge), rho = k * r(lat), L = (lon * Math.PI) / 180;
  return [LOC.size / 2 + rho * Math.sin(L), LOC.size / 2 - rho * Math.cos(L)];
}
function renderLocator() {
  const cv = $("#locator");
  if (!cv) return;
  const dpr = window.devicePixelRatio || 1, S = LOC.size, c = S / 2;
  cv.width = S * dpr; cv.height = S * dpr; cv.style.width = cv.style.height = S + "px";
  const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, S, S);
  ctx.strokeStyle = css("--line"); ctx.fillStyle = css("--ink-2"); ctx.lineWidth = 1; ctx.font = "9.5px Overpass Mono, monospace"; ctx.textAlign = "center";
  for (let lat = -84; lat >= -89; lat--) {
    const [, y] = locXY(lat, 0); ctx.beginPath(); ctx.arc(c, c, c - y, 0, 7); ctx.stroke();
    if (lat === -85 || lat === -88) ctx.fillText(`${-lat}°S`, c + 2, y - 3);
  }
  ctx.strokeStyle = css("--yonder"); ctx.beginPath(); ctx.arc(c, c, c - 14, 0, 7); ctx.stroke();
  for (let lon = 0; lon < 360; lon += 30) {
    const [x, y] = locXY(LOC.edge, lon); ctx.strokeStyle = css("--grid"); ctx.beginPath(); ctx.moveTo(c, c); ctx.lineTo(x, y); ctx.stroke();
  }
  ctx.fillStyle = css("--ink-2");
  ctx.fillText("0° · Earth side", c, 9); ctx.fillText("180°", c, S - 2);
  ctx.textAlign = "left"; ctx.fillText("90°E", S - 26, c + 3); ctx.textAlign = "right"; ctx.fillText("90°W", 26, c + 3);
  ctx.strokeStyle = css("--ink"); ctx.beginPath(); ctx.moveTo(c - 4, c); ctx.lineTo(c + 4, c); ctx.moveTo(c, c - 4); ctx.lineTo(c, c + 4); ctx.stroke();
  ctx.font = "600 10px Overpass Mono, monospace"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  state.sites.forEach((site, k) => {
    const [x, y] = locXY(site.lat, site.lon), sel = state.sel && state.sel.site === site.id;
    ctx.fillStyle = css(sel ? "--sun" : "--ink"); ctx.beginPath(); ctx.arc(x, y, sel ? 8 : 7, 0, 7); ctx.fill();
    if (sel) { ctx.strokeStyle = css("--sun"); ctx.beginPath(); ctx.arc(x, y, 12, 0, 7); ctx.stroke(); }
    ctx.fillStyle = css("--deep"); ctx.fillText(String(k + 1), x, y + 0.5);
  });
  ctx.textBaseline = "alphabetic";
}
function locatorClick(ev) {
  const r = $("#locator").getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top;
  let best = null;
  state.sites.forEach((site, si) => { const [sx, sy] = locXY(site.lat, site.lon), d = Math.hypot(sx - x, sy - y); if (d < 16 && (!best || d < best.d)) best = { si, d }; });
  if (!best || !state.sel) return;
  const t = state.tables[best.si];
  state.sel = { site: state.sites[best.si].id, k: state.sel.k, start: t.starts[state.sel.k] };
  renderAll();
}

// ---------------------------------------------------------------- journey bar: highlight the step in view
function initJourney() {
  const links = [...document.querySelectorAll(".journey a")];
  const mark = () => {
    let on = links[0];
    for (const a of links) { const h = document.querySelector(a.getAttribute("href")); if (h && h.getBoundingClientRect().top < 160) on = a; }
    // Robustness lives inside the Evidence card: light it when its heading is in view
    const rob = [...document.querySelectorAll("#evidence h3.sec")][0];
    if (rob && rob.getBoundingClientRect().top < 260 && rob.getBoundingClientRect().bottom > 0 && on.getAttribute("href") === "#ev-h") on = links.find((a) => a.hasAttribute("data-rob"));
    links.forEach((a) => a.classList.toggle("on", a === on));
  };
  let queued = false;                                  // at most one check per frame while scrolling
  addEventListener("scroll", () => { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; mark(); }); } }, { passive: true });
  mark();
  links.find((a) => a.hasAttribute("data-rob"))?.addEventListener("click", (e) => {
    const rob = document.querySelector("#evidence h3.sec"); if (rob) { e.preventDefault(); rob.scrollIntoView({ block: "center" }); }
  });
}

// ---------------------------------------------------------------- 3D view (lazy, optional)
const v3 = { view: null, loading: false, site: null, bufs: new Map(), failed: false };
function init3d() {
  const card = $("#card3d");
  const io = new IntersectionObserver(async (entries) => {
    if (!entries.some((e) => e.isIntersecting) || v3.loading) return;
    v3.loading = true; io.disconnect();
    try {
      const { createView } = await import("./view3d.js");
      const box = $("#view3d"); box.innerHTML = "";
      const col = (v) => css(v);
      v3.view = createView(box, { sun: col("--sun"), earth: col("--earth"), ok: col("--ok"), bad: col("--blocked"), ring: col("--ink"), hidden: col("--ink-2") });
      update3d(true);
    } catch (e) {
      v3.failed = true;
      $("#view3d").innerHTML = `<p class="hint">The 3D view could not load (it needs three.js from cdn.jsdelivr.net or WebGL). Nothing else on this page depends on it.</p>`;
    }
  }, { rootMargin: "200px" });
  io.observe(card);
  card.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => {
    card.querySelectorAll("[data-view]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    if (!v3.view || !state.sel) return;
    const s = state.sites.find((x) => x.id === state.sel.site);
    v3.view.landerView(b.dataset.view === "lander", s.sunAz[state.cursor ?? 0] / 100);
  }));
}
async function update3d(force) {
  if (!v3.view || !state.sel) return;
  const si = state.sites.findIndex((x) => x.id === state.sel.site), s = state.sites[si], t = state.tables[si];
  if (!s.terrain3d) return;
  const key = `${s.id}|${state.h}`;
  if (force || v3.site !== key) {
    v3.site = key;
    if (!v3.bufs.has(s.id)) v3.bufs.set(s.id, await fetchBin(`data/terrain_${s.id}.bin`));
    v3.view.setSite(s.terrain3d, v3.bufs.get(s.id), s.horizon[String(state.meta.heights_m[state.h])].elev_cdeg, state.meta.heights_m[state.h]);
    $("#v3-sub").textContent = `${short(s)} · relief ${s.terrain3d.relief_m[0]} … +${s.terrain3d.relief_m[1]} m around the lander`;
  }
  const a = t.starts[state.sel.k];
  v3.view.setPoints(s.dispEval ? s.dispEval[state.h].map((e) => e(a, t.L, state.req, perHour()).feasible) : []);
  time3d();
}
function time3d() {
  if (!v3.view || !state.sel) return;
  const s = state.sites.find((x) => x.id === state.sel.site), p = state.cursor ?? 0;
  v3.view.setTime({ az: s.sunAz[p] / 100, el: s.sunEl[p] / 100 }, { az: s.earthAz[p] / 100, el: s.earthEl[p] / 100 }, s.f[state.h][p] > 0);
}

// ---------------------------------------------------------------- methods
function renderMethods(validation) {
  const v = validation || {};
  const rows = (v.checks || []).map((c) => `<tr><td>${c.check}</td><td>${c.reference}</td><td>${c.result}</td><td>${c.criterion}</td><td>${c.status}</td></tr>`).join("");
  $("#methods-body").innerHTML = `<div class="methods">
    <p>Every number on this page comes from open NASA/JPL data through a reproducible pipeline (repository <code>pipeline/</code>). Sun and Earth directions: NAIF SPICE (DE440, MOON_ME). Terrain: NASA GSFC LOLA DEMs (Barker et al. 2023) at 10 m near the site, 80–480 m to 300 km. Horizon method follows Mazarico et al. 2011 / Barker et al. 2021. DTE: lunar terrain and DSN antennas ≥ 6° (DSN 810-005).</p>
    <table><thead><tr><th>Check</th><th>Reference</th><th>Result</th><th>Pass criterion (fixed in advance)</th><th>Status</th></tr></thead><tbody>${rows || "<tr><td colspan=5>validation file not loaded</td></tr>"}</tbody></table>
    <p>Robustness: every window is re-evaluated at 19 landing points within 250 m (each with its own skyline) and, where NASA publishes them, on Monte Carlo DEM error clones (PGDA product 78, Barker et al. 2021). The browser engine is checked against the Python solver by a golden test (max difference 5·10⁻¹⁰). Full methods, data list with SHA-256 pins, and the decision log are in the repository's <code>docs/</code>.</p>
    <p class="hint">Known limitations: geometric link only (no DSN scheduling, link budget or relays); uniform solar disc; boulders and features below the DEM's ≈ 15–35 m effective resolution are not seen; irradiance is for an ideal Sun-tracking panel, not lander power; DEM-error robustness only where NASA publishes clones; the 3D view is an illustration and computes nothing.</p></div>`;
}

// ---------------------------------------------------------------- canvas helper
function setup(cv, h) {
  const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, pw = Math.round(w * dpr), ph = Math.round(h * dpr);
  if (cv.style.height !== h + "px") cv.style.height = h + "px";
  if (cv.width !== pw || cv.height !== ph) { cv.width = pw; cv.height = ph; }     // resizing reallocates: only when needed
  const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
  return ctx;
}

// ---------------------------------------------------------------- mission brief (printable, one page)
function missionBrief() {
  if (!state.sel) return;
  const si = state.sites.findIndex((x) => x.id === state.sel.site), s = state.sites[si], t = state.tables[si], k = state.sel.k;
  const a = t.starts[k], act = activeConstraints(state.req), M = t.metrics, ok = t.feasible[k];
  const esc = (x) => String(x).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const unit = (key) => (key === "sun" || key === "dte" ? "%" : " h");
  const rows = ["sun", "dte", "blackout", "shadow"].map((key) => {
    const has = key in act, pass = has ? t.margins[key][k] >= -1e-9 : null;
    return `<tr><td>${LABELS[key]}</td><td class="n">${M[key][k].toFixed(1)}${unit(key)}</td><td class="n">${has ? `${SENSE[key] > 0 ? "≥" : "≤"} ${act[key]}${unit(key)}` : "—"}</td>
      <td class="n">${has ? `${t.margins[key][k] >= 0 ? "+" : ""}${t.margins[key][k].toFixed(1)}${unit(key)}` : ""}</td><td>${has ? (pass ? "PASS" : "<b>FAIL</b>") : "not required"}</td></tr>`;
  }).join("");
  const cmp = state.tables.map((tt, j) => `<tr${j === si ? ' class="sel"' : ""}><td>${esc(short(state.sites[j]))}</td>${["sun", "dte", "blackout", "shadow"].map((key) =>
    `<td class="n${key in act && tt.margins[key][k] < -1e-9 ? " bad" : ""}">${tt.metrics[key][k].toFixed(1)}${unit(key)}</td>`).join("")}<td>${tt.feasible[k] ? "PASS" : "FAIL"}</td></tr>`).join("");
  const why = [...document.querySelectorAll("#evidence .why li")].map((li) => `<li>${esc(li.textContent)}</li>`).join("");
  const rob = document.querySelector("#evidence table.rob");
  const robRows = rob ? [...rob.querySelectorAll("tbody tr")].map((tr) => `<tr>${[...tr.children].map((c) => `<td${c.colSpan > 1 ? ` colspan="${c.colSpan}"` : ""}>${esc(c.innerText.split("\n").join(" · "))}</td>`).join("")}</tr>`).join("") : "";
  const img = (sel) => { try { return document.querySelector(sel).toDataURL("image/png"); } catch { return ""; } };
  const req = `${state.req.durationH / 24} days · sunlight ≥ ${state.req.minSunPct}% · DTE link ≥ ${state.req.minDtePct}% · blackout ≤ ${fmtH(state.req.maxBlackoutH)}${state.req.maxShadowH != null ? ` · darkness ≤ ${fmtH(state.req.maxShadowH)}` : ""} · panels/antenna ${state.meta.heights_m[state.h]} m`;
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>LUNAR//OPS mission brief — ${esc(short(s))} ${fmtDate(timeOf(a))}</title>
<style>
  body{font:12px/1.45 "Overpass",system-ui,sans-serif;color:#0b1430;margin:28px 34px}
  h1{font:900 20px "Fira Sans",system-ui,sans-serif;margin:0}h1 b{color:#0042A6}
  h2{font:800 11px "Fira Sans",system-ui,sans-serif;text-transform:uppercase;letter-spacing:.1em;color:#0042A6;margin:16px 0 6px;border-bottom:1px solid #c8d3ea;padding-bottom:3px}
  .meta{color:#4a5878;font:11px ui-monospace,monospace;margin:4px 0 10px}
  .verdict{font:900 22px "Fira Sans",system-ui,sans-serif;margin:8px 0;color:${ok ? "#1b5e20" : "#b71c1c"}}
  table{border-collapse:collapse;width:100%;font-size:11.5px}td,th{border-bottom:1px solid #dde4f2;padding:4px 5px;text-align:left;vertical-align:top}
  th{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:#4a5878}.n{text-align:right;font-family:ui-monospace,monospace}
  .bad{color:#b71c1c;font-weight:700}tr.sel td{background:#eef3ff}
  img{width:100%;border:1px solid #dde4f2;background:#07173F;margin-top:4px}
  .two{display:grid;grid-template-columns:1fr 1fr;gap:16px}.fine{color:#4a5878;font-size:10px;margin-top:14px}
  @media print{body{margin:12mm}}
</style></head><body>
<h1>LUNAR<b>//</b>OPS · Mission brief</h1>
<div class="meta">${esc(short(s))} (${s.lat.toFixed(4)}°, ${s.lon.toFixed(4)}° E) · landing ${fmtTime(timeOf(a))} · generated ${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC</div>
<div><b>Requirements:</b> ${esc(req)}</div>
<div class="verdict">${ok ? "GO — this landing window meets every requirement" : "NO-GO — " + esc(t.failingAt(k).map((x) => FAIL_TEXT[x]).join(", "))}</div>
<h2>Margins</h2><table><thead><tr><th>Metric</th><th class="n">Value</th><th class="n">Required</th><th class="n">Margin</th><th></th></tr></thead><tbody>${rows}</tbody></table>
${why ? `<h2>Why</h2><ul>${why}</ul>` : ""}
${robRows ? `<h2>Robustness</h2><table><thead><tr><th></th><th>Holds at</th><th>Pessimistic</th><th>Optimistic</th><th></th></tr></thead><tbody>${robRows}</tbody></table>` : ""}
<h2>All sites, same landing time</h2><table><thead><tr><th>Site</th><th class="n">Sunlight</th><th class="n">DTE link</th><th class="n">Longest blackout</th><th class="n">Longest darkness</th><th></th></tr></thead><tbody>${cmp}</tbody></table>
<div class="two"><div><h2>Timeline</h2><img src="${img("#timeline")}" alt="timeline"></div><div><h2>Skyline from the lander</h2><img src="${img("#horizon")}" alt="skyline"></div></div>
<p class="fine">Reproduce this view: ${esc(location.href)}<br>Method: NAIF SPICE (DE440, MOON_ME) Sun/Earth/DSN geometry; skylines from NASA GSFC LOLA DEMs (Barker et al. 2023) to 300 km; DTE = DSN antenna ≥ 6° and above the lunar skyline (geometric only, no scheduling or link budget). Validated against JPL Horizons and Barker et al. 2021. LUNAR//OPS is an independent open-source planning and education prototype — not a NASA product, not endorsed by NASA, not for flight operations.</p>
</body></html>`;
  // print from a hidden frame: no pop-up blocker, and the page itself stays as it is
  document.querySelector("#brief-frame")?.remove();
  const fr = document.createElement("iframe");
  fr.id = "brief-frame"; fr.title = "Mission brief"; fr.setAttribute("aria-hidden", "true");
  fr.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden";
  document.body.appendChild(fr);
  const d = fr.contentWindow.document;
  d.open(); d.write(html); d.close();
  setTimeout(() => { fr.contentWindow.focus(); fr.contentWindow.print(); }, 400);
}

// ---------------------------------------------------------------- shareable state (#d=30&sun=80&...)
const HASH_FIELDS = { d: "durationD", sun: "minSunPct", dte: "minDtePct", blk: "maxBlackoutH", shd: "maxShadowH", h: "heightM" };
function readHash() {
  const q = new URLSearchParams(location.hash.slice(1));
  if (q.has("d")) $("#req [name=useShadow]").checked = q.has("shd");     // a full scenario link defines the darkness limit too
  for (const [k, name] of Object.entries(HASH_FIELDS)) {
    if (!q.has(k)) continue;
    const el = $(`#req [name=${name}]`), v = Number(q.get(k));
    if (!Number.isFinite(v)) continue;
    if (el.tagName === "SELECT") { if ([...el.options].some((o) => Number(o.value) === v)) el.value = String(v); continue; }
    el.value = String(Math.min(Math.max(v, Number(el.min)), Number(el.max)));     // clamp to the form's range
    if (k === "shd") $("#req [name=useShadow]").checked = true;
  }
  if (q.has("site") && q.has("t")) {
    const t = Date.parse(q.get("t") + ":00Z");
    if (state.sites.some((x) => x.id === q.get("site")) && Number.isFinite(t))
      state.pending = { site: q.get("site"), start: Math.round((t - t0ms()) / (state.meta.grid.step_s * 1000)) };
  }
}
function writeHash() {
  const r = state.req, q = new URLSearchParams();
  q.set("d", r.durationH / 24); q.set("sun", r.minSunPct); q.set("dte", r.minDtePct); q.set("blk", r.maxBlackoutH);
  if (r.maxShadowH != null) q.set("shd", r.maxShadowH);
  q.set("h", state.meta.heights_m[state.h]);
  if (state.sel) { q.set("site", state.sel.site); q.set("t", timeOf(state.sel.start).toISOString().slice(0, 13)); }
  history.replaceState(null, "", "#" + q.toString().replace(/%3A/g, ":"));
}

// ---------------------------------------------------------------- guided demo (Stage 22)
// Deterministic: every step is a URL state, so the same clicks always show the same numbers.
const TOUR = [
  { hash: "d=14&sun=70&dte=50&blk=24&h=1", focus: "#verdict",
    text: "<b>A two-week CLPS mission.</b> It needs ≥ 70% sunlight on its panels, a direct-to-Earth link ≥ 50% of the time and no blackout over 24 h. LUNAR//OPS checks every landing hour in 2027–2028 at six south-pole sites." },
  { hash: "d=14&sun=70&dte=50&blk=24&h=1", focus: "#map-h",
    text: "<b>Where + when.</b> Rows are sites, columns are landing days. Yellow works. Bright yellow still works if the lander misses its target by 250 m — like IM-2 did. Other colours name the requirement that fails." },
  { hash: "d=30&sun=80&dte=50&blk=240&shd=48&h=1", focus: "#map-h",
    text: "<b>Now survive a month.</b> 30 days, ≥ 80% sunlight, no darkness longer than 2 days. Sites start to separate — and no solution is robust to landing error any more." },
  { hash: "d=30&sun=80&dte=60&blk=240&shd=48&h=1", focus: "#cmp-h",
    text: "<b>Ask for more Earth link (≥ 60%).</b> Same landing day, six sites side by side: every number is a measured margin, red ones break the mission. No hidden score." },
  { hash: "d=30&sun=80&dte=60&blk=120&shd=48&h=1", focus: "#verdict",
    text: "<b>Cap blackouts at 5 days.</b> NO-GO: no site, no date. Instead of “no results” the engine computes the smallest requirement change that brings a mission back — and the design alternatives that keep every requirement, like a shorter surface stay. The bars under the sliders show where each requirement hits a cliff." },
  { action: () => { const b = document.querySelector("#verdict .relax button[data-k=blackout]") || document.querySelector("#verdict .relax button"); if (b) b.click(); },
    focus: "#ev-h", text: "<b>Accept the suggested relaxation.</b> A window reappears. Evidence shows every margin, why the long blackout happens (libration, a ridge, a DSN gap) — and how fragile the answer is to landing error and, where NASA publishes DEM error clones, to terrain uncertainty." },
  { focus: "#tl-h", text: "<b>Play the mission.</b> ⏮ ⏭ jump between sunrises, Earthsets and link changes. The horizon below separates what geometry allows from what the terrain actually lets through." },
  { focus: "#v3-h", action: () => document.querySelector("[data-view=lander]")?.click(),
    text: "<b>Stand on the lander.</b> The line is the skyline computed from 300 km of NASA LOLA terrain; Sun and Earth are drawn at true size and elevation. Every number on this page is validated — see Methods & validation — and ⎙ Mission brief turns any window into a one-page PDF." },
];
let tourAt = -1;
function tourGo(k) {
  tourAt = Math.max(0, Math.min(TOUR.length - 1, k));
  const st = TOUR[tourAt];
  if (st.hash) { location.hash = st.hash; state.pending = null; readHash(); update(false); }
  if (st.action) st.action();
  $("#tour").hidden = false;
  $("#tour-step").textContent = `Demo ${tourAt + 1} / ${TOUR.length}`;
  $("#tour-text").innerHTML = st.text;
  $("#tour-prev").disabled = tourAt === 0;
  $("#tour-next").textContent = tourAt === TOUR.length - 1 ? "Finish" : "Next";
  $("#tour-next").focus({ preventScroll: true });
  const el = document.querySelector(st.focus);
  // scroll after the re-render has settled the layout
  const box = el && el.closest(".card, .verdict");
  if (box) setTimeout(() => {
    const smooth = !matchMedia("(prefers-reduced-motion: reduce)").matches;
    box.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
    // some embedded browsers never finish a smooth scroll; make sure we arrive
    setTimeout(() => { if (Math.abs(box.getBoundingClientRect().top - 72) > 40) box.scrollIntoView({ block: "start" }); }, 900);
  }, 60);
}
function initTour() {
  $("#tour-start").addEventListener("click", () => tourGo(0));
  $("#intro-demo").addEventListener("click", () => tourGo(0));
  let hidden = false;
  try { hidden = localStorage.getItem("lunarops-intro") === "hidden"; } catch { /* storage unavailable */ }
  $("#intro").hidden = hidden;
  $("#intro-close").addEventListener("click", () => { $("#intro").hidden = true; try { localStorage.setItem("lunarops-intro", "hidden"); } catch { /* ignore */ } });
  $("#tour-prev").addEventListener("click", () => tourGo(tourAt - 1));
  $("#tour-next").addEventListener("click", () => (tourAt === TOUR.length - 1 ? ($("#tour").hidden = true) : tourGo(tourAt + 1)));
  $("#tour-close").addEventListener("click", () => ($("#tour").hidden = true));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#tour").hidden = true; });
}

// ---------------------------------------------------------------- wiring
function pickDefault() {
  // first feasible window, else the closest one overall
  let best = null;
  state.tables.forEach((t, si) => state.days[si].forEach((c) => {
    if (c && (!best || c.score > best.c.score)) best = { si, c };
  }));
  if (best) state.sel = { site: state.sites[best.si].id, k: best.c.i, start: state.tables[best.si].starts[best.c.i] };
}
function update(keepSel, fast = false) {
  state.req = readForm(); showOutputs(state.req); compute(fast);
  if (state.pending) {
    const si = state.sites.findIndex((x) => x.id === state.pending.site), t = state.tables[si];
    const k = Math.round(state.pending.start / (t.starts[1] - t.starts[0]));
    state.pending = null;
    if (k >= 0 && k < t.starts.length) { state.sel = { site: t.id, k, start: t.starts[k] }; renderAll(); return; }
  }
  if (!keepSel || !state.sel) pickDefault();
  else {
    const si = state.sites.findIndex((s) => s.id === state.sel.site), t = state.tables[si];
    const d = Math.floor(state.sel.start / DAY), c = state.days[si][Math.min(d, state.days[si].length - 1)];
    if (c) state.sel = { site: state.sel.site, k: c.i, start: t.starts[c.i] };
    // if the kept selection no longer passes but something else does, show the best passing window
    const anyOk = state.days.some((row) => row.some((x) => x && x.ok));
    if ((!c || !c.ok) && anyOk) pickDefault();
  }
  if (fast) { renderVerdict(); renderMap(); } else renderAll();
}
function renderAll() {
  writeHash();
  const parts = [renderSparks, renderVerdict, renderLocator, renderMap, renderCompare, renderEvidence, renderPareto, () => renderTimeline(Number($("#scrub").value) / 1000), renderHorizon];
  const ms = parts.map((fn) => { const t = performance.now(); fn(); return Math.round(performance.now() - t); });
  if (PROF) console.log("render ms", ms.join(" "));
  update3d(false);
}

async function main() {
  try {
    const { meta, sites, validation } = await load();
    state.meta = meta; state.sites = sites;
    renderMethods(validation);
  } catch (e) {
    $("#verdict").className = "verdict none";
    $("#verdict").innerHTML = `<div class="big">Data could not be loaded.</div><div>${String(e.message || e)}. Run the pipeline (python -m lunarops.build) or serve the web/ folder over HTTP.</div>`;
    return;
  }
  // While a slider moves: one cheap update per frame (verdict + map, a few ms). When it rests for
  // 150 ms: the full update (landing-error robustness of every day, sparklines, charts, 3D).
  let pendingFrame = 0, restTimer = 0;
  $("#req").addEventListener("input", () => {
    if (!pendingFrame) pendingFrame = requestAnimationFrame(() => { pendingFrame = 0; update(true, true); });
    clearTimeout(restTimer);
    restTimer = setTimeout(() => { cancelAnimationFrame(pendingFrame); pendingFrame = 0; update(true); }, 150);
  });
  $("#map").addEventListener("mousemove", (ev) => {
    const h = mapHit(ev), tip = $("#map-tip");
    if (!h || !h.cell) { tip.hidden = true; return; }
    const t = state.tables[h.r], i = h.cell.i;
    tip.hidden = false; tip.style.left = h.x + "px"; tip.style.top = h.y + "px";
    tip.textContent = `${short(state.sites[h.r])} · ${fmtDate(timeOf(t.starts[i]))} · sun ${t.metrics.sun[i].toFixed(0)}% · DTE ${t.metrics.dte[i].toFixed(0)}% · ${h.cell.ok ? "OK" : FAIL_TEXT[h.cell.fail]}`;
  });
  $("#map").addEventListener("mouseleave", () => ($("#map-tip").hidden = true));
  $("#map").addEventListener("click", (ev) => {
    const h = mapHit(ev); if (!h || !h.cell) return;
    state.sel = { site: state.sites[h.r].id, k: h.cell.i, start: state.tables[h.r].starts[h.cell.i] };
    $("#scrub").value = 0; renderAll();
  });
  $("#map").addEventListener("keydown", (ev) => {
    if (!state.sel) return;
    let r = state.sites.findIndex((x) => x.id === state.sel.site), d = Math.floor(state.sel.start / DAY);
    const nDays = state.days[0].length;
    if (ev.key === "ArrowLeft") d = Math.max(0, d - 1);
    else if (ev.key === "ArrowRight") d = Math.min(nDays - 1, d + 1);
    else if (ev.key === "ArrowUp") r = Math.max(0, r - 1);
    else if (ev.key === "ArrowDown") r = Math.min(state.sites.length - 1, r + 1);
    else return;
    ev.preventDefault();
    const c = state.days[r][d]; if (!c) return;
    state.sel = { site: state.sites[r].id, k: c.i, start: state.tables[r].starts[c.i] };
    $("#map").setAttribute("aria-label", `${short(state.sites[r])}, ${fmtDate(timeOf(state.sel.start))}: ${c.ok ? "meets all requirements" : FAIL_TEXT[c.fail]}`);
    renderAll();
  });
  $("#scrub").addEventListener("input", () => { renderTimeline(Number($("#scrub").value) / 1000); renderHorizon(); time3d(); });
  $("#ev-prev").addEventListener("click", () => jumpEvent(-1));
  $("#ev-next").addEventListener("click", () => jumpEvent(+1));
  $("#play").addEventListener("click", () => {
    if (state.play) { cancelAnimationFrame(state.play); state.play = null; $("#play").textContent = "▶"; return; }
    $("#play").textContent = "❚❚";
    let last = 0;
    const step = (now) => {
      if (!state.play) return;
      if (now - last >= 40) {                                  // ~25 steps per second, in sync with the screen
        last = now;
        const v = (Number($("#scrub").value) + 4) % 1001; $("#scrub").value = v;
        renderTimeline(v / 1000); renderHorizon(); time3d();
      }
      state.play = requestAnimationFrame(step);
    };
    state.play = requestAnimationFrame(step);
  });
  document.querySelectorAll(".modes button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".modes button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    document.body.classList.toggle("explain", b.dataset.mode === "explain");
  }));
  let resizeT = 0;
  window.addEventListener("resize", () => { clearTimeout(resizeT); resizeT = setTimeout(renderAll, 120); });
  readHash();
  update(false);
  init3d();
  window.addEventListener("hashchange", () => { readHash(); update(false); });   // a pasted scenario link
  initTour();
  initJourney();
  if (PROF) window.__lunar = { state, update, compute, renderAll, readForm };     // ?prof: timing hooks for development
  $("#locator").addEventListener("click", locatorClick);
  $("#brief").addEventListener("click", missionBrief);
}
main();

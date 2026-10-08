"""Collect validation results into web/data/validation.json (shown under Methods & evidence).

Only numbers produced by the test suite are reported; nothing is typed by hand
except the reference descriptions and the pass criteria, which mirror the tests.

    python -m pytest tests && python -m lunarops.report
"""
from __future__ import annotations

import json

from .paths import DATA, DERIVED, WEB_DATA


def _load(name):
    p = DERIVED / name
    return json.loads(p.read_text()) if p.exists() else None


def main():
    checks = []
    for target in ("sun", "earth"):
        v = _load(f"validation_horizons_{target}.json")
        if v:
            checks.append({
                "check": f"{target.title()} azimuth/elevation at the IM-2 site, {v['n']} hourly samples (Nov 2026 - Nov 2027)",
                "reference": "JPL Horizons API (DE441), observer coord@301",
                "result": f"max error {max(v['el_max_deg'], v['az_max_deg']):.1e} deg",
                "criterion": "< 1e-2 deg", "status": "PASS" if max(v["el_max_deg"], v["az_max_deg"]) < 0.01 else "FAIL"})
    for z in (5, 1):
        v = _load(f"validation_barker2021_z{z}.json")
        if not v:
            continue
        pub = v["published"]
        lo, hi = v["criteria"]["avg"]
        ok = lo <= v["our_avg_pct"] <= hi
        ref = (f"Barker et al. 2021 Table 2, RoI 4, z={z} m: 1st percentile {pub['A']}% over 100 clones"
               + (f", longest shadow {pub['lcsp99_days']} d (99th pct)" if "lcsp99_days" in pub else f" (range {pub['B']}-{pub['C']}%)"))
        res = f"{v['our_avg_pct']}% average illumination, longest shadow {v['our_lcsp_days']} d"
        crit = f"{lo}-{hi}%" + (f", shadow <= {v['criteria']['lcsp_days_max']} d" if "lcsp_days_max" in v["criteria"] else "")
        if "lcsp_days_max" in v["criteria"]:
            ok = ok and v["our_lcsp_days"] <= v["criteria"]["lcsp_days_max"]
        checks.append({"check": f"Connecting Ridge RoI 4, 2024-2026, panels {z} m", "reference": ref,
                       "result": res, "criterion": crit, "status": "PASS" if ok else "FAIL"})
    sel = DATA / "sites_selected.json"
    web = WEB_DATA / "sites.json"
    if sel.exists() and web.exists():
        pub = {d["id"]: d for d in json.loads(sel.read_text())}
        ours = {d["id"]: d for d in json.loads(web.read_text())["sites"]}
        ids = [i for i in pub if i in ours]
        a = [ours[i]["summary"]["1"]["sun_avg_pct"] for i in ids]
        b = [100 * pub[i]["published_avg_sun"] for i in ids]
        rank_same = sorted(ids, key=lambda i: -ours[i]["summary"]["1"]["sun_avg_pct"]) == sorted(ids, key=lambda i: -pub[i]["published_avg_sun"])
        mad = sum(abs(x - y) for x, y in zip(a, b)) / len(ids)
        checks.append({"check": f"Average sunlight at {len(ids)} rule-selected sites, panels 1 m (2027-2028)",
                       "reference": "PGDA AVGVISIB_85S_060M (Mazarico et al.; 18.6-year average, different period)",
                       "result": "; ".join(f"{i}: {x:.1f}% vs {y:.1f}%" for i, x, y in zip(ids, a, b)) + f"; mean |diff| {mad:.1f} pp; same ranking: {rank_same}",
                       "criterion": "same ranking, mean |diff| < 5 pp (set after first look: indicative only)", "status": "PASS" if rank_same and mad < 5 else "FAIL"})
        e1 = [ours[i]["summary"]["1"]["dte_pct"] for i in ids]
        e2 = [100 * pub[i]["published_avg_earth"] for i in ids]
        lower = all(x <= y + 0.5 for x, y in zip(e1, e2))
        checks.append({"check": "Earth link vs published Earth visibility, same sites",
                       "reference": "PGDA AVGVISIB_..._EARTH (any part of Earth's disc visible)",
                       "result": "; ".join(f"{i}: {x:.1f}% vs {y:.1f}%" for i, x, y in zip(ids, e1, e2)),
                       "criterion": "ours not higher, since our rule is stricter (set after first look: indicative only)",
                       "status": "PASS" if lower else "FAIL"})
    vc = _load("validation_clones_connecting-ridge-roi4.json")
    if vc:
        import numpy as np
        for z in (5, 1):
            rows = [m for m in vc["members"] if m["z"] == z and m["name"].startswith("clone-")]
            if len(rows) < 20:
                continue
            p1 = float(np.percentile([r["avg_pct"] for r in rows], 1))
            if z == 5:
                p99 = float(np.percentile([r["lcsp_days"] for r in rows], 99))
                ok = abs(p1 - 88.12) <= 3.0 and abs(p99 - 4.00) <= 1.5
                res, crit = f"1st pct {p1:.2f}%, 99th pct longest shadow {p99:.2f} d over {len(rows)} clones", "|p1 - 88.12| <= 3 pp and |p99 - 4.00 d| <= 1.5 d"
                ref = "Barker et al. 2021 Table 2, RoI 4, z=5 m, 100 clones: 1st pct 88.12%, longest shadow 99th pct 4.00 d"
            else:
                ok = 52.19 <= p1 <= 86.81
                res, crit = f"1st pct {p1:.2f}% over {len(rows)} clones", "52.19% <= p1 <= 86.81%"
                ref = "Barker et al. 2021 Table 2, RoI 4, z=1 m, 100 clones: 1st pct 69.61% (range 52.19-86.81%)"
            checks.append({"check": f"DEM-error ensemble (NASA clones), Connecting Ridge RoI 4, 2024-2026, panels {z} m",
                           "reference": ref, "result": res, "criterion": crit + " (fixed before processing, D-024)",
                           "status": "PASS" if ok else "FAIL"})
    conv = _load("validation_convergence.json")
    if conv:
        checks.append({"check": "Horizon resolution test: 30-100 km and 100-300 km layers coarsened 2x (160->320 m, 480->960 m), Connecting Ridge", "reference": "same pipeline",
                       "result": f"max change {conv['max_change_deg']:.3f} deg", "criterion": "< 0.05 deg",
                       "status": "PASS" if conv["max_change_deg"] < 0.05 else "FAIL"})
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    (WEB_DATA / "validation.json").write_text(json.dumps({"checks": checks}, indent=1))
    print(f"{len(checks)} checks written")


if __name__ == "__main__":
    main()

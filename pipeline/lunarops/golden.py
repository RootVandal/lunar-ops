"""Golden fixtures: the Python solver's answers on real site series, for web/tests/golden.html.

    python -m lunarops.golden
"""
from __future__ import annotations

import json

import numpy as np

from .paths import WEB_DATA
from .solver import Requirements, SiteSeries, evaluate, minimal_relaxation, window_metrics

CASES = [
    Requirements(duration_h=168, min_sun_pct=70, min_dte_pct=50, max_blackout_h=24),
    Requirements(duration_h=72, min_sun_pct=85, min_dte_pct=80, max_blackout_h=6, max_shadow_h=12),
    Requirements(duration_h=240, min_sun_pct=95, min_dte_pct=95, max_blackout_h=1),     # no solution expected
]


def read_series(meta, site_id, h_index):
    n, nh = meta["grid"]["n"], len(meta["heights_m"])
    raw = np.fromfile(WEB_DATA / f"site_{site_id}.bin", dtype=np.uint8)
    f = raw[h_index * n:(h_index + 1) * n].astype(float) / meta["f_scale"]
    dte = (raw[(nh + h_index) * n:(nh + h_index + 1) * n] & 1).astype(bool)
    return SiteSeries(site_id, meta["grid"]["start_utc"], meta["grid"]["step_s"], f.astype(np.float32).astype(float), dte)


def main():
    meta = json.loads((WEB_DATA / "sites.json").read_text())
    out = []
    for h in range(len(meta["heights_m"])):
        series = [read_series(meta, s["id"], h) for s in meta["sites"]]
        for req in CASES:
            tables = evaluate([window_metrics(s, req) for s in series], req)
            rel = minimal_relaxation(tables, req)
            out.append({
                "height_index": h, "req": {"durationH": req.duration_h, "minSunPct": req.min_sun_pct, "minDtePct": req.min_dte_pct,
                                           "maxBlackoutH": req.max_blackout_h, "maxShadowH": req.max_shadow_h, "litThreshold": req.lit_threshold},
                "sites": [{"id": t.site_id, "n": int(len(t.starts)), "feasible": int(t.feasible.sum()),
                           "sample": {k: [round(float(x), 9) for x in t.metrics[k][::97]] for k in t.metrics}} for t in tables],
                "relax": {k: (None if v["relaxed_to"] is None else round(v["relaxed_to"], 9)) for k, v in rel.items()},
            })
    (WEB_DATA / "golden.json").write_text(json.dumps(out))
    print(len(out), "golden cases")


if __name__ == "__main__":
    main()

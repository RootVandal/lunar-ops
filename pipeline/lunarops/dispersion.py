"""Robustness to landing error (Stage 2, section 2.14, method B; decision D-008).

Real reference: IM-2 Athena landed ~250 m from its target, inside a small crater
(Spaceflight Now, 2025-03-07). We place 19 points inside a circle of radius
R_LAND around each site (centre, 6 at R/2, 12 at R), compute each point's own
terrain horizon with the same nested DEMs, and store hourly visibility series.
The browser then asks: for the selected landing window, at how many of these
points would the mission still meet every requirement?

    python -m lunarops.dispersion
"""
from __future__ import annotations

import json

import numpy as np

from . import geo, terrain
from .build import HEIGHTS, F_SCALE, global_ephemeris, site_series
from .horizon import compute_horizon
from .paths import WEB_DATA
from .sites import BY_ID
from .solver import runs

R_LAND_M = 250.0
HOURLY = 6        # keep every 6th 10-min sample


def ring_points(lat, lon, r_m=R_LAND_M):
    x, y = geo.stereo_forward(lat, lon)
    pts = [(0.0, 0.0)]
    pts += [(r_m / 2 * np.cos(a), r_m / 2 * np.sin(a)) for a in np.radians(np.arange(0, 360, 60))]
    pts += [(r_m * np.cos(a), r_m * np.sin(a)) for a in np.radians(np.arange(0, 360, 30))]
    return [(*geo.stereo_inverse(x + dx, y + dy), dx, dy) for dx, dy in pts]


class _P:  # minimal Site-like object for site_series
    def __init__(self, lat, lon):
        self.lat, self.lon = lat, lon


def main(site_ids=None):
    g = global_ephemeris()
    meta = json.loads((WEB_DATA / "sites.json").read_text())
    for s in meta["sites"]:
        if site_ids and s["id"] not in site_ids:
            continue
        site = BY_ID[s["id"]]
        pts = ring_points(site.lat, site.lon)
        rasters, _ = terrain.rasters_for(site.lat, site.lon,
                                         )
        blobs = []
        heights_at = []
        run_data = [[None] * len(pts) for _ in HEIGHTS]
        for lat, lon, dx, dy in pts:
            hz = {z: compute_horizon(float(lat), float(lon), z, rasters) for z in HEIGHTS}
            _, f, link, _, _ = site_series(g, _P(float(lat), float(lon)), hz)
            heights_at.append(round(hz[HEIGHTS[0]].h_site_m, 1))
            for hi, z in enumerate(HEIGHTS):
                blobs.append((np.round(np.clip(f[z][::HOURLY], 0, 1) * F_SCALE).astype("<u1"),
                              link[z][::HOURLY].astype("<u1")))
                # exact 10-min run boundaries: hourly sampling would merge blackouts (DTE flickers at the skyline)
                on_s, on_e = runs(link[z])
                dk_s, dk_e = runs(np.round(np.clip(f[z], 0, 1) * F_SCALE) == 0)   # same quantisation as the stored series
                pi = len(heights_at) - 1
                run_data[hi][pi] = {"on": np.stack([on_s, on_e], 1).ravel().tolist(),
                                    "dark": np.stack([dk_s, dk_e], 1).ravel().tolist()}
        # layout: for each height, for each point: f (n_h bytes) then dte (n_h bytes)
        ordered = []
        for hi in range(len(HEIGHTS)):
            for pi in range(len(pts)):
                ff, dd = blobs[pi * len(HEIGHTS) + hi]
                ordered += [ff.tobytes(), dd.tobytes()]
        (WEB_DATA / f"disp_{site.id}.bin").write_bytes(b"".join(ordered))
        s["dispersion"] = {"radius_m": R_LAND_M, "points": len(pts), "step_samples": HOURLY,
                           "offsets_m": [[round(dx, 1), round(dy, 1)] for _, _, dx, dy in pts],
                           "ground_height_m": heights_at,
                           "source": "IM-2 landed ~250 m from target (Spaceflight Now, 2025-03-07); uniform ring sampling",
                           "runs": run_data}
        print(s["id"], "terrain height spread across points: %.1f m" % (max(heights_at) - min(heights_at)), flush=True)
    (WEB_DATA / "sites.json").write_text(json.dumps(meta, separators=(",", ":")))


if __name__ == "__main__":
    import sys
    main(sys.argv[1:] or None)

"""Horizon resolution test (decision D-018): coarsen the 30-100 km and 100-300 km layers by 2x.

If halving the resolution of the far layers barely moves the horizon, refining
them (to Barker et al.'s 80/240 m) would move it even less.

    python -m lunarops.convergence
"""
from __future__ import annotations

import json

import numpy as np

from . import terrain
from .horizon import compute_horizon
from .paths import DERIVED
from .sites import BY_ID

COARSE = [(terrain.URL_10M, 0), (terrain.URL_80M, 0), (terrain.URL_80M, 2), (terrain.URL_240M, 2)]


def main(site_id="connecting-ridge-roi4", z=1.0):
    s = BY_ID[site_id]
    fine, _ = terrain.rasters_for(s.lat, s.lon)
    coarse, used = terrain.rasters_for(s.lat, s.lon, nest=COARSE)
    h1 = compute_horizon(s.lat, s.lon, z, fine)
    h2 = compute_horizon(s.lat, s.lon, z, coarse)
    d = np.abs(h2.elev - h1.elev)
    res = {"site": site_id, "z_m": z, "fine_layers_m": [10, 80, 160, 480], "coarse_layers_m": [u["pixel_m"] for u in used],
           "max_change_deg": float(d.max()), "median_change_deg": float(np.median(d)),
           "share_azimuths_changed_over_0p01": float((d > 0.01).mean())}
    (DERIVED / "validation_convergence.json").write_text(json.dumps(res, indent=2))
    print(res)


if __name__ == "__main__":
    main()

"""Validation against published illumination: Barker et al. 2021, Table 2, Site 1 RoI 4.

Published (100 DEM clones, 2024-01-01 .. 2026-01-01, hourly):
  z = 1 m  average illumination, 1st percentile:  A 69.61 %, B 52.19 % (pessimistic), C 86.81 % (optimistic)
  z = 5 m  average illumination, 1st percentile:  A 88.12 %
           longest continuous shadow, 99th percentile (A): 4.00 days

We compute ONE point (the RoI 4 centroid) on the NOMINAL 2023 DEM, whereas the
paper averages the RoI area over 100 clones of its 2021 DEM. The paper notes the
nominal DEM is usually more optimistic than the clones. So this is a
consistency check, and the pass ranges below were fixed BEFORE running it
(2026-10-08, decision log D-019):

  z = 1 m: 52 % <= our average <= 95 %
  z = 5 m: 85 % <= our average <= 97 %,  our longest shadow <= 6 days
"""
import json
from pathlib import Path

import numpy as np
import pytest

from lunarops import ephem, geo, visibility
from lunarops.horizon import Horizon
from lunarops.paths import DERIVED, KERNELS
from lunarops.sites import BY_ID

SITE = BY_ID["connecting-ridge-roi4"]
CRITERIA = {1: {"avg": (52.0, 95.0)}, 5: {"avg": (85.0, 97.0), "lcsp_days_max": 6.0}}


def load_hz(z):
    p = DERIVED / f"horizon_{SITE.id}_z{z}.npz"
    if not p.exists():
        pytest.skip("horizon not computed yet")
    d = np.load(p)
    return Horizon(SITE.lat, SITE.lon, float(z), float(d["h_site"]), d["az"], d["elev"], d["dist"], d["near"], d["far"])


@pytest.mark.skipif(not (KERNELS / "de440s.bsp").exists(), reason="kernels missing")
@pytest.mark.parametrize("z", [1, 5])
def test_connecting_ridge_roi4(z):
    import spiceypy as spice
    from lunarops.solver import runs
    ephem.load_kernels(stations=False)
    hz = load_hz(z)
    et = ephem.utc_grid("2024-01-01T00:00:00", "2026-01-01T00:00:00", 3600.0)
    site = geo.latlon_to_vec(SITE.lat, SITE.lon, (geo.R_MOON_M + hz.h_site_m) / 1000.0)
    basis = geo.enu_basis(site)
    sun = ephem.moon_centered("SUN", et) - site
    earth = ephem.moon_centered("EARTH", et) - site
    az, el = geo.az_el(sun, basis)
    dist = np.linalg.norm(sun, axis=1)
    sep = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", sun, earth) / (dist * np.linalg.norm(earth, axis=1)), -1, 1)))
    f = visibility.sun_fraction(el, hz.at(az), ephem.sun_radius_deg(dist), 0.0, sep, ephem.earth_radius_deg(np.linalg.norm(earth, axis=1)))
    avg = 100 * f.mean()
    rs, re = runs(f <= 0.0)
    lcsp_days = float((re - rs).max() / 24.0) if len(rs) else 0.0
    rs2, re2 = runs(f > 0.0)
    lcip_days = float((re2 - rs2).max() / 24.0) if len(rs2) else 0.0
    res = {"site": SITE.id, "z_m": z, "period": "2024-01-01..2026-01-01", "our_avg_pct": round(avg, 2),
           "our_lcsp_days": round(lcsp_days, 2), "our_lcip_days": round(lcip_days, 2),
           "published": {1: {"A": 69.61, "B": 52.19, "C": 86.81}, 5: {"A": 88.12, "lcsp99_days": 4.00}}[z],
           "criteria": CRITERIA[z]}
    out = DERIVED / f"validation_barker2021_z{z}.json"
    out.write_text(json.dumps(res, indent=2))
    print(res)
    lo, hi = CRITERIA[z]["avg"]
    assert lo <= avg <= hi
    if "lcsp_days_max" in CRITERIA[z]:
        assert lcsp_days <= CRITERIA[z]["lcsp_days_max"]

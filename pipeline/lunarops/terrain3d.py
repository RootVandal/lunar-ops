"""Local terrain patches for the 3D view (Stage 13). Illustration only: no decision uses them.

For each site we resample the same NASA LOLA DEM chain the horizons use onto a
local east/north grid centred on the site (great-circle offsets, so the grid is
aligned with the azimuths of the Sun and Earth), and store heights along the
site's local vertical relative to its ground, including the Moon's curvature
drop (about 4.6 m at 4 km).

Outputs: web/data/terrain_<id>.bin (int16, row 0 = north edge, scale 0.25 m) and
sites.json -> terrain3d {half_m, step_m, n, scale_m, points_enu_m}.

    python -m lunarops.terrain3d
"""
from __future__ import annotations

import json

import numpy as np

from . import geo, terrain
from .dispersion import ring_points
from .horizon import sample_chain
from .paths import WEB_DATA
from .sites import BY_ID

HALF_M = 4000.0
STEP_M = 20.0
SCALE_M = 0.25


def enu_of(lat, lon, basis):
    e, n, u = basis
    p = geo.latlon_to_vec(lat, lon, 1.0)
    g = np.arccos(np.clip(p @ u, -1, 1))
    az = np.arctan2(p @ e, p @ n)
    s = g * geo.R_MOON_M
    return s * np.sin(az), s * np.cos(az)


def patch(site):
    rasters, used = terrain.rasters_for(site.lat, site.lon)
    basis = geo.enu_basis(geo.latlon_to_vec(site.lat, site.lon, 1.0))
    e, n, u = basis
    ax = np.arange(-HALF_M, HALF_M + STEP_M / 2, STEP_M)
    E, N = np.meshgrid(ax, ax[::-1])
    s = np.hypot(E, N)
    g = s / geo.R_MOON_M
    with np.errstate(invalid="ignore", divide="ignore"):
        dirv = (E[..., None] * e + N[..., None] * n) / np.where(s > 0, s, 1.0)[..., None]
    p = np.cos(g)[..., None] * u + np.sin(g)[..., None] * dirv
    x, y = geo.unit_to_stereo(p)
    h = sample_chain(rasters, x.ravel(), y.ravel()).reshape(E.shape)
    sx, sy = geo.stereo_forward(site.lat, site.lon)
    h0 = float(sample_chain(rasters, np.array([sx]), np.array([sy]))[0])
    up = (geo.R_MOON_M + h) * np.cos(g) - (geo.R_MOON_M + h0)
    up = np.where(np.isnan(up), np.nanmin(up), up)
    return np.round(up / SCALE_M).astype("<i2"), basis, used


def main():
    meta_p = WEB_DATA / "sites.json"
    meta = json.loads(meta_p.read_text())
    for s in meta["sites"]:
        site = BY_ID[s["id"]]
        q, basis, used = patch(site)
        (WEB_DATA / f"terrain_{site.id}.bin").write_bytes(q.tobytes())
        pts = [enu_of(lat, lon, basis) for lat, lon, _, _ in ring_points(site.lat, site.lon)]
        s["terrain3d"] = {"half_m": HALF_M, "step_m": STEP_M, "n": int(q.shape[0]), "scale_m": SCALE_M,
                          "points_enu_m": [[round(float(a), 1), round(float(b), 1)] for a, b in pts],
                          "source": "NASA LOLA DEMs (Barker et al. 2023) resampled to a local east/north grid; illustration only",
                          "relief_m": [round(float(q.min()) * SCALE_M, 1), round(float(q.max()) * SCALE_M, 1)]}
        print(site.id, q.shape, "relief", s["terrain3d"]["relief_m"], flush=True)
    meta_p.write_text(json.dumps(meta, separators=(",", ":")))


if __name__ == "__main__":
    main()

"""Terrain horizon by ray casting over nested DEMs (Stage 2, section 2.8).

For each of 1440 azimuths (0.25 deg) we march along the great circle from the
site and keep the largest elevation angle of the terrain, with the Moon's
curvature handled exactly on the 1737.4 km sphere:

    theta(s) = atan2(r_q cos(g) - r_o, r_q sin(g)),   g = s / R

Every sample takes its height from the finest raster that covers it, so a gap in
a fine DEM falls back to the coarser one instead of producing a hole.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import geo
from .dem import Raster

N_AZ = 1440
AZ = np.arange(N_AZ) * (360.0 / N_AZ)

# (start_m, stop_m, step_m) - Barker et al. 2021 nest the 5 m DEM to 5 km,
# 80 m to 100 km and 240 m beyond; we follow that layout (decision D-003) and
# record the actual rasters used in the output metadata.
DEFAULT_SEGMENTS = [
    (20.0, 5_000.0, 10.0),
    (5_000.0, 30_000.0, 80.0),
    (30_000.0, 100_000.0, 160.0),
    (100_000.0, 300_000.0, 480.0),
]


@dataclass
class Horizon:
    lat: float
    lon: float
    z_m: float
    h_site_m: float
    az: np.ndarray
    elev: np.ndarray            # terrain horizon elevation, deg
    dist_m: np.ndarray          # distance of the occluding terrain, m
    elev_near: np.ndarray       # horizon from terrain closer than 5 km
    elev_far: np.ndarray        # horizon from terrain beyond 5 km
    meta: dict = field(default_factory=dict)

    def at(self, az_deg):
        """Linear interpolation of the horizon at arbitrary azimuths (wraps at 360)."""
        a = np.asarray(az_deg) % 360.0
        f = a / (360.0 / N_AZ)
        i0 = np.floor(f).astype(int) % N_AZ
        i1 = (i0 + 1) % N_AZ
        t = f - np.floor(f)
        return (1 - t) * self.elev[i0] + t * self.elev[i1]


def sample_chain(rasters: list[Raster], x, y) -> np.ndarray:
    """Height from the first (finest) raster that has a value at (x, y)."""
    z = np.full(np.shape(x), np.nan)
    for r in rasters:
        need = np.isnan(z)
        if not need.any():
            break
        z[need] = r.sample(x[need], y[need])
    return z


def compute_horizon(lat: float, lon: float, z_m: float, rasters: list[Raster],
                    segments=DEFAULT_SEGMENTS, h_site_m: float | None = None) -> Horizon:
    if abs(lat) > geo.POLE_LIMIT_DEG:
        raise ValueError("site too close to the pole for a defined azimuth")
    unit = geo.latlon_to_vec(lat, lon, 1.0)
    basis = geo.enu_basis(unit)
    if h_site_m is None:
        sx, sy = geo.stereo_forward(lat, lon)
        h_site_m = float(sample_chain(rasters, np.array([sx]), np.array([sy]))[0])
        if np.isnan(h_site_m):
            raise ValueError("no DEM covers the site")
    r_o = geo.R_MOON_M + h_site_m + z_m

    best = np.full(N_AZ, -90.0)
    best_d = np.zeros(N_AZ)
    near = np.full(N_AZ, -90.0)
    far = np.full(N_AZ, -90.0)
    for s0, s1, step in segments:
        s = np.arange(s0, s1, step)
        p = geo.great_circle_points(basis, AZ, s)               # (az, s, 3)
        x, y = geo.unit_to_stereo(p)
        h = sample_chain(rasters, x, y)
        g = s / geo.R_MOON_M
        r_q = geo.R_MOON_M + h
        theta = np.degrees(np.arctan2(r_q * np.cos(g) - r_o, r_q * np.sin(g)))
        theta = np.where(np.isnan(theta), -90.0, theta)
        k = np.argmax(theta, axis=1)
        tmax = theta[np.arange(N_AZ), k]
        upd = tmax > best
        best = np.where(upd, tmax, best)
        best_d = np.where(upd, s[k], best_d)
        if s1 <= 5_000.0:
            near = np.maximum(near, tmax)
        else:
            far = np.maximum(far, tmax)
    return Horizon(lat, lon, z_m, h_site_m, AZ.copy(), best, best_d, near, far,
                   meta={"segments": [list(x) for x in segments], "n_az": N_AZ})


def window_boxes(lat: float, lon: float, segments=DEFAULT_SEGMENTS, margin=1.05):
    """Square boxes (xmin, xmax, ymin, ymax) in stereographic metres each segment needs."""
    sx, sy = geo.stereo_forward(lat, lon)
    out = []
    for _, s1, _ in segments:
        d = s1 * margin * 1.01  # stereographic scale factor <= 1.01 within 15 deg of the pole
        out.append((sx - d, sx + d, sy - d, sy + d))
    return out

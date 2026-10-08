"""Lunar geometry on the 1737.4 km reference sphere (Stage 2, sections 2.1, 2.6, 2.8).

Conventions (must match SPICE azlcpo with azccw=False, elplsz=True):
  * frame MOON_ME, planetocentric latitude, east-positive longitude;
  * local "north" = projection of the body +Z axis onto the local horizontal;
  * azimuth measured clockwise from north (towards east), elevation from the
    plane perpendicular to the sphere normal.
"""
from __future__ import annotations

import numpy as np

R_MOON_KM = 1737.4          # LOLA LBL A/B/C_AXIS_RADIUS; Horizons "Center radii"
R_MOON_M = R_MOON_KM * 1000.0
POLE_LIMIT_DEG = 89.999     # azimuth undefined at the exact pole (Stage 2, 2.1)


def latlon_to_vec(lat_deg, lon_deg, r):
    """Body-fixed Cartesian vector(s) for planetocentric lat/lon at radius r."""
    lat = np.radians(lat_deg)
    lon = np.radians(lon_deg)
    c = np.cos(lat)
    return np.stack([r * c * np.cos(lon), r * c * np.sin(lon), r * np.sin(lat)], axis=-1)


def vec_to_latlon(v):
    v = np.asarray(v, dtype=float)
    r = np.linalg.norm(v, axis=-1)
    lat = np.degrees(np.arcsin(np.clip(v[..., 2] / r, -1, 1)))
    lon = np.degrees(np.arctan2(v[..., 1], v[..., 0]))
    return lat, lon, r


def enu_basis(site_vec):
    """East, north, up unit vectors at a site (sphere normal = up)."""
    u = np.asarray(site_vec, dtype=float)
    u = u / np.linalg.norm(u)
    z = np.array([0.0, 0.0, 1.0])
    e = np.cross(z, u)
    n_e = np.linalg.norm(e)
    if n_e < 1e-12:
        raise ValueError("site is on the polar axis; azimuth is undefined (|lat| > 89.999 deg)")
    e /= n_e
    n = np.cross(u, e)
    return e, n, u


def az_el(directions, basis):
    """Azimuth (deg, clockwise from north) and elevation (deg) of direction vectors."""
    e, n, u = basis
    d = np.asarray(directions, dtype=float)
    d = d / np.linalg.norm(d, axis=-1, keepdims=True)
    el = np.degrees(np.arcsin(np.clip(d @ u, -1.0, 1.0)))
    az = np.degrees(np.arctan2(d @ e, d @ n)) % 360.0
    return az, el


def great_circle_points(basis, az_deg, s_m):
    """Unit vectors of points at surface distance s (m) along azimuth az from the site.

    Vector form (stable near the pole): p = cos(g) u + sin(g) (cos(a) n + sin(a) e).
    Returns array of shape (len(az), len(s), 3).
    """
    e, n, u = basis
    a = np.radians(np.atleast_1d(az_deg))[:, None, None]
    g = (np.atleast_1d(s_m) / R_MOON_M)[None, :, None]
    dirv = np.cos(a) * n + np.sin(a) * e
    return np.cos(g) * u + np.sin(g) * dirv


# --- South polar stereographic projection on the sphere (Snyder 1987) -----------
# rho = 2R tan(pi/4 + lat/2); x = rho sin(lon); y = rho cos(lon).
# Sign convention is verified against the GeoTIFF georeferencing in tests.

def stereo_forward(lat_deg, lon_deg, r_m=R_MOON_M):
    lat = np.radians(lat_deg)
    lon = np.radians(lon_deg)
    rho = 2.0 * r_m * np.tan(np.pi / 4.0 + lat / 2.0)
    return rho * np.sin(lon), rho * np.cos(lon)


def stereo_inverse(x_m, y_m, r_m=R_MOON_M):
    rho = np.hypot(x_m, y_m)
    lat = 2.0 * np.arctan(rho / (2.0 * r_m)) - np.pi / 2.0
    lon = np.arctan2(x_m, y_m)
    return np.degrees(lat), np.degrees(lon)


def unit_to_stereo(p, r_m=R_MOON_M):
    """Stereographic x, y (m) of unit vectors p, without trig round-trips.

    South aspect: rho = 2R tan(pi/4 + lat/2) = 2R (1 + sin lat) / cos lat, and
    sin(lon) = p_y / cos(lat), so x = rho sin(lon) = 2R p_y / (1 - p_z) and
    y = rho cos(lon) = 2R p_x / (1 - p_z).
    """
    p = np.asarray(p, dtype=float)
    k = 2.0 * r_m / (1.0 - p[..., 2])
    return k * p[..., 1], k * p[..., 0]


def horizon_dip_deg(height_m):
    """Depression of the smooth-sphere horizon seen from height h (Explorer explanations)."""
    return -np.degrees(np.arccos(R_MOON_M / (R_MOON_M + np.asarray(height_m, dtype=float))))

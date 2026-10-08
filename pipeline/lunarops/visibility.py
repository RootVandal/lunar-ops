"""Sun/Earth visibility and direct-to-Earth links (Stage 2, sections 2.9-2.11)."""
from __future__ import annotations

import numpy as np

DSN_MIN_ELEV_DEG = 6.0   # DSN 810-005 module 302 Rev B, Table 1: elevation motion limits 6-89.5 deg


def segment_fraction(u):
    """Visible fraction of a uniform disc cut by a straight horizon.

    u = (centre elevation - horizon) / angular radius, clipped to [-1, 1].
    f(1) = 1, f(0) = 0.5, f(-1) = 0.
    """
    u = np.clip(np.asarray(u, dtype=float), -1.0, 1.0)
    return 1.0 - (np.arccos(u) - u * np.sqrt(1.0 - u * u)) / np.pi


def disc_overlap_fraction(sep_deg, r_sun_deg, r_occ_deg):
    """Fraction of the solar disc covered by an occulting disc (Earth), flat-sky approximation."""
    d = np.asarray(sep_deg, dtype=float)
    r1 = np.asarray(r_sun_deg, dtype=float)
    r2 = np.asarray(r_occ_deg, dtype=float)
    d, r1, r2 = np.broadcast_arrays(d, r1, r2)
    out = np.zeros(d.shape)
    full = d <= np.abs(r2 - r1)
    out[full] = np.minimum(1.0, (r2[full] / r1[full]) ** 2)
    part = (d < r1 + r2) & ~full
    if part.any():
        dd, a, b = d[part], r1[part], r2[part]
        c1 = np.clip((dd**2 + a**2 - b**2) / (2 * dd * a), -1, 1)
        c2 = np.clip((dd**2 + b**2 - a**2) / (2 * dd * b), -1, 1)
        k = (-dd + a + b) * (dd + a - b) * (dd - a + b) * (dd + a + b)
        area = a**2 * np.arccos(c1) + b**2 * np.arccos(c2) - 0.5 * np.sqrt(np.maximum(k, 0.0))
        out[part] = area / (np.pi * a**2)
    return out


def sun_fraction(sun_el, sun_horizon, r_sun_deg, clearance_deg=0.0, sep_deg=None, r_earth_deg=None):
    """f(t): visible fraction of the solar disc after terrain and Earth eclipses."""
    f = segment_fraction((np.asarray(sun_el) - np.asarray(sun_horizon) - clearance_deg) / np.asarray(r_sun_deg))
    if sep_deg is not None:
        f = f * (1.0 - disc_overlap_fraction(sep_deg, r_sun_deg, r_earth_deg))
    return f


def earth_los(earth_el, earth_horizon, margin_deg=0.0):
    """Earth disc centre above terrain plus antenna margin (working rule, 2.10)."""
    return (np.asarray(earth_el) - np.asarray(earth_horizon)) >= margin_deg


def earth_any_part(earth_el, earth_horizon, r_earth_deg):
    """PGDA AVGVISIB_EARTH rule: any part of the disc visible (validation only)."""
    return (np.asarray(earth_el) + np.asarray(r_earth_deg)) > np.asarray(earth_horizon)


def dte_link(station_el_ground: dict, station_el_site: dict, station_horizon: dict,
             min_ground_el=DSN_MIN_ELEV_DEG, margin_deg=0.0):
    """DTE(t) = OR over stations [station sees the lander >= e_min AND lander sees station above terrain].

    Returns (link bool array, index of the first station providing it or -1).
    """
    names = sorted(station_el_ground)
    ok = np.stack([(station_el_ground[s] >= min_ground_el)
                   & ((station_el_site[s] - station_horizon[s]) >= margin_deg) for s in names])
    link = ok.any(axis=0)
    who = np.where(link, ok.argmax(axis=0), -1)
    return link, who, names


SOLAR_CONSTANT = 1361.0   # W m^-2 at 1 au (Kopp & Lean 2011: 1360.8 +/- 0.5)
AU_KM = 149_597_870.7


def irradiance(f, sun_el_deg, sun_dist_km):
    """Irradiance on a vertical, azimuth-tracking panel (W m^-2); not lander power."""
    return SOLAR_CONSTANT * (AU_KM / np.asarray(sun_dist_km)) ** 2 * np.asarray(f) * np.cos(np.radians(sun_el_deg))

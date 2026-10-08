"""Validation: our SPICE geometry against JPL Horizons (gate G2, tolerance 0.01 deg).

Fixtures: Horizons API output for the IM-2 landing point (84.7906 S, 29.1957 E,
0 km above the 1737.4 km sphere), hourly, 2026-11-01 .. 2027-11-01, saved in
Stage 1 (tests/fixtures/*_im2.txt). Horizons uses DE441 and the mean-Earth frame
of DE421 for the Moon; we use DE440 + MOON_ME. Refraction is off for non-Earth
sites in Horizons; light-time and aberration are on in both.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from lunarops import ephem, geo
from lunarops.paths import KERNELS

FIX = Path(__file__).parent / "fixtures"
TOL_DEG = 0.01
SITE = (-84.7906, 29.1957)

needs_kernels = pytest.mark.skipif(not all((KERNELS / k).exists() for k in ephem.CORE_KERNELS),
                                   reason="SPICE kernels not downloaded")


def read_horizons(name):
    rows = []
    on = False
    for line in (FIX / name).read_text().splitlines():
        if line.startswith("$$SOE"):
            on = True
            continue
        if line.startswith("$$EOE"):
            break
        if on:
            p = [x.strip() for x in line.split(",")]
            rows.append((p[0], float(p[3]), float(p[4])))
    return rows


def angdiff(a, b):
    return (np.asarray(a) - np.asarray(b) + 180.0) % 360.0 - 180.0


@needs_kernels
@pytest.mark.parametrize("target,fixture", [("SUN", "sun_im2.txt"), ("EARTH", "earth_im2.txt")])
def test_against_horizons(target, fixture, record_property):
    import spiceypy as spice
    ephem.load_kernels(stations=False)
    rows = read_horizons(fixture)
    et = np.array([spice.str2et(r[0] + " UTC") for r in rows])
    hz_az = np.array([r[1] for r in rows])
    hz_el = np.array([r[2] for r in rows])
    site = geo.latlon_to_vec(*SITE, geo.R_MOON_KM)
    basis = geo.enu_basis(site)
    vec = ephem.moon_centered(target, et)
    az, el = geo.az_el(vec - site, basis)
    d_el = np.abs(el - hz_el)
    # azimuth error measured on the sky (scaled by cos el)
    d_az = np.abs(angdiff(az, hz_az)) * np.cos(np.radians(el))
    stats = {"target": target, "n": int(len(rows)), "el_mean_deg": float(d_el.mean()), "el_max_deg": float(d_el.max()),
             "az_mean_deg": float(d_az.mean()), "az_max_deg": float(d_az.max())}
    out = Path(__file__).parents[2] / "data" / "derived" / f"validation_horizons_{target.lower()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stats, indent=2))
    print(stats)
    assert d_el.max() < TOL_DEG
    assert d_az.max() < TOL_DEG


@needs_kernels
@pytest.mark.parametrize("target", ["SUN", "EARTH"])
def test_moon_centred_shortcut_matches_azlcpo(target):
    """D-013: computing from the Moon's centre then subtracting the site equals SPICE's surface observer."""
    import spiceypy as spice
    ephem.load_kernels(stations=False)
    rng = np.random.default_rng(7)
    et0 = spice.str2et("2027-01-01T00:00:00")
    worst = 0.0
    for _ in range(40):
        lat = rng.uniform(-89.9, -80.0)
        lon = rng.uniform(-180, 180)
        et = et0 + rng.uniform(0, 2 * 365.25 * 86400)
        site = geo.latlon_to_vec(lat, lon, geo.R_MOON_KM)
        az, el = geo.az_el(ephem.moon_centered(target, np.array([et]))[0] - site, geo.enu_basis(site))
        raz, rel, _ = ephem.azlcpo_reference(target, et, site)
        worst = max(worst, abs(el - rel), abs(angdiff(az, raz)) * np.cos(np.radians(el)))
    assert worst < 1e-3

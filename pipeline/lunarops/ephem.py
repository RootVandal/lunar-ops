"""Sun, Earth and DSN geometry from SPICE (Stage 2, sections 2.2-2.6 and 2.11).

Strategy (decision D-013): the directions to the Sun, Earth and DSN stations
are computed once per epoch relative to the Moon's centre in MOON_ME. Each
site's topocentric azimuth/elevation then follows by vector arithmetic. The
error of that shortcut against SPICE azlcpo for an observer on the surface is
measured in tests (it is far below the 0.01 deg tolerance).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import spiceypy as spice

from . import geo
from .paths import KERNELS

KERNEL_FILES = [
    "naif0012.tls",
    "pck00011.tpc",
    "moon_pa_de440_200625.bpc",
    "moon_de440_250416.tf",
    "de440s.bsp",
    "earth_1962_260806_2126_combined.bpc",
    "earthstns_itrf93_260814.bsp",
    "earth_topo_260814.tf",
]

FRAME = "MOON_ME"
ABCORR = "LT+S"
DSN_STATIONS = {"DSS-14": "Goldstone", "DSS-43": "Canberra", "DSS-63": "Madrid"}


CORE_KERNELS = KERNEL_FILES[:5]       # enough for Sun and Earth; the rest add DSN stations


def load_kernels(stations: bool = True) -> None:
    spice.kclear()
    wanted = KERNEL_FILES if stations else CORE_KERNELS
    missing = [k for k in wanted if not (KERNELS / k).exists()]
    if missing:
        raise FileNotFoundError(f"missing kernels {missing}; run: python -m lunarops.fetch")
    for k in wanted:
        spice.furnsh(str(KERNELS / k))


def utc_grid(start_utc: str, stop_utc: str, step_s: float) -> np.ndarray:
    """TDB seconds past J2000 on a uniform grid [start, stop)."""
    et0 = spice.str2et(start_utc)
    et1 = spice.str2et(stop_utc)
    n = int(np.floor((et1 - et0) / step_s))
    return et0 + step_s * np.arange(n, dtype=float)


def et_to_utc(et: float) -> str:
    return spice.et2utc(float(et), "ISOC", 0)


def moon_centered(target: str, et: np.ndarray, abcorr: str = ABCORR) -> np.ndarray:
    """Position of target relative to the Moon's centre in MOON_ME, km, shape (N, 3)."""
    pos, _ = spice.spkpos(target, et, FRAME, abcorr, "MOON")
    return np.asarray(pos, dtype=float).reshape(-1, 3)


def station_up_me(station: str, et: np.ndarray) -> np.ndarray:
    """Local zenith of a DSN station expressed in MOON_ME at each epoch, unit vectors."""
    frame = f"{station}_TOPO"
    out = np.empty((len(et), 3))
    for i, t in enumerate(et):
        out[i] = spice.pxform(frame, FRAME, float(t))[:, 2]
    return out


@dataclass
class GlobalEphemeris:
    """Everything that does not depend on the lunar site, sampled on one time grid."""

    et: np.ndarray
    sun: np.ndarray            # (N, 3) km, MOON_ME, Moon-centred, LT+S
    earth: np.ndarray          # (N, 3) km
    stations: dict             # name -> (pos (N, 3) km, up (N, 3) unit)

    @classmethod
    def compute(cls, et: np.ndarray) -> "GlobalEphemeris":
        stations = {}
        for s in DSN_STATIONS:
            stations[s] = (moon_centered(s, et), station_up_me(s, et))
        return cls(et=et, sun=moon_centered("SUN", et), earth=moon_centered("EARTH", et), stations=stations)


def sun_radius_deg(dist_km):
    return np.degrees(np.arcsin(695_700.0 / np.asarray(dist_km)))


def earth_radius_deg(dist_km):
    return np.degrees(np.arcsin(6_378.1366 / np.asarray(dist_km)))


@dataclass
class SiteGeometry:
    """Topocentric geometry at one site (no terrain yet)."""

    sun_az: np.ndarray
    sun_el: np.ndarray
    sun_dist: np.ndarray
    earth_az: np.ndarray
    earth_el: np.ndarray
    earth_dist: np.ndarray
    sun_earth_sep: np.ndarray      # deg, for Earth eclipses of the Sun (2.9)
    station_az: dict               # name -> az of the station seen from the site, deg
    station_el_site: dict          # name -> el of the station seen from the site, deg
    station_el_ground: dict        # name -> el of the site seen from the station, deg


def site_geometry(g: GlobalEphemeris, site_vec_km: np.ndarray) -> SiteGeometry:
    basis = geo.enu_basis(site_vec_km)
    to_sun = g.sun - site_vec_km
    to_earth = g.earth - site_vec_km
    sun_az, sun_el = geo.az_el(to_sun, basis)
    earth_az, earth_el = geo.az_el(to_earth, basis)
    sd = np.linalg.norm(to_sun, axis=1)
    ed = np.linalg.norm(to_earth, axis=1)
    cosang = np.einsum("ij,ij->i", to_sun, to_earth) / (sd * ed)
    sep = np.degrees(np.arccos(np.clip(cosang, -1, 1)))
    st_az, st_el_site, st_el_ground = {}, {}, {}
    for s, (pos, up) in g.stations.items():
        to_station = pos - site_vec_km
        st_az[s], st_el_site[s] = geo.az_el(to_station, basis)
        to_site = -to_station
        dist = np.linalg.norm(to_site, axis=1)
        st_el_ground[s] = np.degrees(np.arcsin(np.clip(np.einsum("ij,ij->i", to_site, up) / dist, -1, 1)))
    return SiteGeometry(sun_az, sun_el, sd, earth_az, earth_el, ed, sep, st_az, st_el_site, st_el_ground)


def azlcpo_reference(target: str, et: float, site_vec_km: np.ndarray):
    """SPICE's own constant-position observer az/el (deg), used to test the shortcut."""
    state, _ = spice.azlcpo("ELLIPSOID", target, float(et), ABCORR, False, True,
                            np.asarray(site_vec_km, dtype=float), "MOON", FRAME)
    return np.degrees(state[1]) % 360.0, np.degrees(state[2]), state[0]

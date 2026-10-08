"""Build the per-site time series the web app uses.

    python -m lunarops.build --sites connecting-ridge-roi4 im2-athena

Outputs (web/data/):
  ephem_meta.json                 grid, kernels, provenance
  sites.json                      sites, horizons, provenance, validation summary
  site_<id>.bin                   little-endian arrays on the 10-min grid:
      uint8  f[z]      visible solar fraction * 250, one array per panel height z
      uint8  dte[z]    bit0 DTE link, bits1-3 which station (0 none, 1..3)
      uint16 sun_az, int16 sun_el, uint16 earth_az, int16 earth_el   (deg * 100)
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json

import numpy as np

from . import ephem, geo, visibility
from .horizon import Horizon, compute_horizon
from .paths import DERIVED, WEB_DATA
from .sites import BY_ID, Site
from . import terrain

GRID = ("2027-01-01T00:00:00", "2029-01-01T00:00:00", 600.0)   # D-012
HEIGHTS = (1.0, 5.0)                                            # Barker et al. 2021 heights
F_SCALE = 250


def global_ephemeris() -> ephem.GlobalEphemeris:
    cache = DERIVED / "global_ephem.npz"
    if cache.exists():
        d = np.load(cache)
        st = {s: (d[f"{s}_pos"], d[f"{s}_up"]) for s in ephem.DSN_STATIONS}
        return ephem.GlobalEphemeris(d["et"], d["sun"], d["earth"], st)
    ephem.load_kernels(stations=True)
    et = ephem.utc_grid(*GRID)
    g = ephem.GlobalEphemeris.compute(et)
    DERIVED.mkdir(parents=True, exist_ok=True)
    extra = {f"{s}_pos": p for s, (p, u) in g.stations.items()} | {f"{s}_up": u for s, (p, u) in g.stations.items()}
    np.savez_compressed(cache, et=g.et, sun=g.sun, earth=g.earth, **extra)
    return g


def site_horizons(site: Site) -> dict[float, Horizon]:
    rasters, used = terrain.rasters_for(site.lat, site.lon)
    out = {}
    for z in HEIGHTS:
        hz = compute_horizon(site.lat, site.lon, z, rasters)
        hz.meta["rasters"] = used
        out[z] = hz
    return out


def site_series(g: ephem.GlobalEphemeris, site: Site, horizons: dict[float, Horizon]):
    h_site = horizons[HEIGHTS[0]].h_site_m
    vec = geo.latlon_to_vec(site.lat, site.lon, (geo.R_MOON_M + h_site) / 1000.0)
    sg = ephem.site_geometry(g, vec)
    r_sun = ephem.sun_radius_deg(sg.sun_dist)
    r_earth = ephem.earth_radius_deg(sg.earth_dist)
    f, link, who = {}, {}, {}
    for z, hz in horizons.items():
        f[z] = visibility.sun_fraction(sg.sun_el, hz.at(sg.sun_az), r_sun, 0.0, sg.sun_earth_sep, r_earth)
        st_h = {s: hz.at(sg.station_az[s]) for s in sg.station_az}
        link[z], who[z], names = visibility.dte_link(sg.station_el_ground, sg.station_el_site, st_h)
    return sg, f, link, who, names


def write_site(site: Site, sg, f, link, who, horizons, out_dir):
    parts = []
    for z in HEIGHTS:
        parts.append(np.round(np.clip(f[z], 0, 1) * F_SCALE).astype("<u1"))
    for z in HEIGHTS:
        parts.append((link[z].astype(np.uint8) | ((who[z] + 1).astype(np.uint8) << 1)).astype("<u1"))
    for arr, dt in ((sg.sun_az, "<u2"), (sg.sun_el, "<i2"), (sg.earth_az, "<u2"), (sg.earth_el, "<i2")):
        parts.append(np.round(arr * 100).astype(dt))     # azimuth 0..36000 needs uint16 (same bytes as before)
    blob = b"".join(p.tobytes() for p in parts)
    (out_dir / f"site_{site.id}.bin").write_bytes(blob)
    return hashlib.sha256(blob).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", nargs="+", default=list(BY_ID))
    a = ap.parse_args()
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    g = global_ephemeris()
    n = len(g.et)
    meta_sites = []
    for sid in a.sites:
        site = BY_ID[sid]
        print("site", sid, flush=True)
        hz = site_horizons(site)
        sg, f, link, who, names = site_series(g, site, hz)
        digest = write_site(site, sg, f, link, who, hz, WEB_DATA)
        meta_sites.append({
            "id": site.id, "name": site.name, "lat": site.lat, "lon": site.lon, "region": site.region,
            "source": site.source, "clones": site.clones, "h_site_m": round(hz[HEIGHTS[0]].h_site_m, 2),
            "sha256": digest,
            "horizon": {str(int(z)): {"elev_cdeg": np.round(h.elev * 100).astype(int).tolist(),
                                      "dist_m": np.round(h.dist_m).astype(int).tolist()} for z, h in hz.items()},
            "rasters": hz[HEIGHTS[0]].meta["rasters"],
            "summary": {str(int(z)): {"sun_avg_pct": round(float(f[z].mean() * 100), 2),
                                      "dte_pct": round(float(link[z].mean() * 100), 2)} for z in HEIGHTS},
        })
        print("   ", meta_sites[-1]["summary"], flush=True)
    meta = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "grid": {"start_utc": GRID[0], "stop_utc": GRID[1], "step_s": GRID[2], "n": n},
        "heights_m": list(HEIGHTS), "f_scale": F_SCALE, "stations": names,
        "kernels": ephem.KERNEL_FILES, "frame": ephem.FRAME, "abcorr": ephem.ABCORR,
        "dsn_min_elev_deg": visibility.DSN_MIN_ELEV_DEG,
        "layout": "per height: uint8 f; per height: uint8 dte|station<<1; uint16 sun_az, int16 sun_el, uint16 earth_az, int16 earth_el (cdeg)",
        "sites": meta_sites,
    }
    (WEB_DATA / "sites.json").write_text(json.dumps(meta, separators=(",", ":")))
    print("wrote", WEB_DATA / "sites.json")


if __name__ == "__main__":
    main()

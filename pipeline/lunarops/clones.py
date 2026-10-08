"""Robustness to DEM error with NASA's own error ensemble (Stage 2, section 2.14, method A; decision D-024).

Barker et al. (2021) published, for each 5 m site DEM, 100 "clones": the same
surface plus one Monte Carlo realization of its error, built from the LOLA
measurement and orbit-adjustment uncertainties (PGDA product 78). We do not
invent an error model; we rerun our horizon and visibility on each clone.

Within 5 km of the site the horizon is cast over the clone (5 m); beyond it
over the same 10/80/240 m DEMs as the main series. The member "nominal-2021"
uses the published surface the clones were made from, so the ensemble spread
is measured against the right reference. The main site series uses the newer
2023 10 m DEM; that version difference is reported separately, not mixed in.

Clones are read from data/raw/pgda/... when downloaded (tools/get_clones.py),
otherwise by HTTP range (about 27 MB per clone: the strips are full rows).

    python -m lunarops.clones connecting-ridge-roi4 --count 30
"""
from __future__ import annotations

import argparse
import json

import numpy as np

from . import ephem, geo, terrain, visibility
from .build import F_SCALE, HEIGHTS, global_ephemeris, site_series
from .dem import RemoteTiff, mirror_path
from .horizon import compute_horizon, window_boxes
from .paths import DERIVED, WEB_DATA
from .sites import BY_ID
from .solver import runs

BASE = "https://pgda.gsfc.nasa.gov/data/LOLA_5mpp"
HOURLY = 6
VALIDATION_PERIOD = ("2024-01-01T00:00:00", "2026-01-01T00:00:00", 3600.0)   # Barker et al. 2021, Table 2


def surf_url(tile: str) -> str:
    return f"{BASE}/{tile}/{tile}_final_adj_5mpp_surf.tif"


def clone_url(tile: str, k: int) -> str:
    return f"{BASE}/{tile}/Clones/{tile}_final_adj_5mpp_{k:04d}_err.tif"


def local_clones(tile: str, count: int) -> list[int]:
    return [k for k in range(1, count + 1) if mirror_path(clone_url(tile, k)).exists()]


class _Validation:
    """Hourly 2024-2025 Sun geometry at one site, to compare with Barker et al. 2021 Table 2."""

    def __init__(self, lat, lon):
        ephem.load_kernels(stations=False)
        self.et = ephem.utc_grid(*VALIDATION_PERIOD)
        self.lat, self.lon = lat, lon
        self.cache = {}

    def stats(self, hz):
        key = round(hz.h_site_m, 3)
        if key not in self.cache:
            site = geo.latlon_to_vec(self.lat, self.lon, (geo.R_MOON_M + hz.h_site_m) / 1000.0)
            basis = geo.enu_basis(site)
            sun = ephem.moon_centered("SUN", self.et) - site
            earth = ephem.moon_centered("EARTH", self.et) - site
            az, el = geo.az_el(sun, basis)
            d_s, d_e = np.linalg.norm(sun, axis=1), np.linalg.norm(earth, axis=1)
            sep = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", sun, earth) / (d_s * d_e), -1, 1)))
            self.cache[key] = (az, el, ephem.sun_radius_deg(d_s), sep, ephem.earth_radius_deg(d_e))
        az, el, r_s, sep, r_e = self.cache[key]
        f = visibility.sun_fraction(el, hz.at(az), r_s, 0.0, sep, r_e)
        rs, re = runs(f <= 0.0)
        return {"avg_pct": round(float(100 * f.mean()), 3),
                "lcsp_days": round(float((re - rs).max() / 24.0) if len(rs) else 0.0, 3)}


def prefetch(urls, box, jobs):
    """Fetch only the rows of each DEM that the 0-5 km skyline needs, several files in parallel.

    The PGDA server limits the speed of one connection; files not already mirrored
    locally are range-read into the pinned tile cache (lunarops.dem) by `jobs` threads.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    todo = [u for u in urls if not mirror_path(u).exists()]
    if not todo:
        return
    t0 = time.time()

    def one(u):
        for attempt in range(5):
            try:
                RemoteTiff(u).window(0, *box)
                return u, None
            except Exception as e:                      # network hiccup: retry, cached ranges are kept
                err = e
                time.sleep(5 * (attempt + 1))
        return u, err

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for i, f in enumerate(as_completed([ex.submit(one, u) for u in todo]), 1):
            u, err = f.result()
            print(f"  [{i}/{len(todo)}] {'FAILED ' + str(err) if err else 'ok'} {u.rsplit('/', 1)[-1]}  ({(time.time() - t0) / 60:.1f} min)", flush=True)


def main(site_id: str, count: int = 30, remote: bool = False, validate: bool = False, jobs: int = 8):
    site = BY_ID[site_id]
    if not site.clones:
        raise SystemExit(f"{site_id}: NASA publishes no DEM error clones for this site")
    tile = site.clones
    ks = list(range(1, count + 1)) if remote else local_clones(tile, count)
    print(f"{site_id}: {len(ks)} clones ({sum(mirror_path(clone_url(tile, k)).exists() for k in ks)} on disk, rest by HTTP range)", flush=True)
    if not ks:
        raise SystemExit(f"no downloaded clones for {tile}; run tools/get_clones.py {tile} or pass --remote")
    g = global_ephemeris()
    base, _ = terrain.rasters_for(site.lat, site.lon)
    box = window_boxes(site.lat, site.lon)[0]
    val = _Validation(site.lat, site.lon) if validate else None

    members = [("nominal-2021", surf_url(tile))] + [(f"clone-{k:04d}", clone_url(tile, k)) for k in ks]
    if remote:
        prefetch([u for _, u in members], box, jobs)
    f_blob, member_meta = [], []
    run_data = [[] for _ in HEIGHTS]
    for name, url in members:
        fine = RemoteTiff(url).window(0, *box)
        hz = {z: compute_horizon(site.lat, site.lon, z, [fine] + base) for z in HEIGHTS}
        _, f, link, _, _ = site_series(g, site, hz)
        m = {"name": name, "url": url, "h_site_m": round(hz[HEIGHTS[0]].h_site_m, 3),
             "summary": {str(int(z)): {"sun_avg_pct": round(float(f[z].mean() * 100), 2),
                                       "dte_pct": round(float(link[z].mean() * 100), 2)} for z in HEIGHTS}}
        if val:
            m["validation_2024_2025"] = {str(int(z)): val.stats(hz[z]) for z in HEIGHTS}
        member_meta.append(m)
        for hi, z in enumerate(HEIGHTS):
            q = np.round(np.clip(f[z], 0, 1) * F_SCALE)
            f_blob.append(q[::HOURLY].astype("<u1").tobytes())
            on_s, on_e = runs(link[z])
            dk_s, dk_e = runs(q == 0)
            run_data[hi].append({"on": np.stack([on_s, on_e], 1).ravel().tolist(),
                                 "dark": np.stack([dk_s, dk_e], 1).ravel().tolist()})
        print(name, m["h_site_m"], m["summary"], m.get("validation_2024_2025", ""), flush=True)

    # layout: member-major, then height: hourly f (uint8, f * F_SCALE)
    (WEB_DATA / f"clones_{site.id}.bin").write_bytes(b"".join(f_blob))
    out = {"site": site.id, "tile": tile, "members": member_meta, "step_samples": HOURLY,
           "heights_m": list(HEIGHTS), "runs": run_data,
           "source": "NASA GSFC PGDA product 78 (Barker et al. 2021): 5 m site DEM and Monte Carlo DEM error clones",
           "near_field_m": [0, 5000]}
    (WEB_DATA / f"clones_{site.id}.json").write_text(json.dumps(out, separators=(",", ":")))
    meta_p = WEB_DATA / "sites.json"
    meta = json.loads(meta_p.read_text())
    for s in meta["sites"]:
        if s["id"] == site.id:
            s["dem_ensemble"] = {"members": len(members), "clones": len(ks), "tile": tile}
    meta_p.write_text(json.dumps(meta, separators=(",", ":")))
    if val:
        DERIVED.mkdir(parents=True, exist_ok=True)
        (DERIVED / f"validation_clones_{site.id}.json").write_text(json.dumps(
            {"site": site.id, "period": VALIDATION_PERIOD[:2], "members": [
                {"name": m["name"], **m["validation_2024_2025"]["1"], "z": 1} for m in member_meta] + [
                {"name": m["name"], **m["validation_2024_2025"]["5"], "z": 5} for m in member_meta]}, indent=1))
    print("wrote", WEB_DATA / f"clones_{site.id}.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("site")
    ap.add_argument("--count", type=int, default=30)
    ap.add_argument("--remote", action="store_true", help="read missing clones over HTTP range")
    ap.add_argument("--validate", action="store_true", help="also compute 2024-2025 stats for Barker et al. 2021")
    ap.add_argument("--jobs", type=int, default=8, help="parallel range downloads with --remote (default 8)")
    a = ap.parse_args()
    main(a.site, a.count, a.remote, a.validate, a.jobs)

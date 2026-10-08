"""Pick one point per NASA GSFC 5 m site tile by a documented rule (decision D-020).

Rule: inside the footprint of the PGDA LOLA_5mpp site DEM (shrunk by 1 km so the
5 m clones cover the near field), take the 60 m pixel with the highest
published average solar visibility (PGDA product 69, AVGVISIB_85S_060M_201608,
Mazarico et al.). Ties: first pixel in row-major order. The published solar and
Earth visibility at the chosen pixel are stored for later comparison.

    python -m lunarops.select_sites
"""
from __future__ import annotations

import json

import numpy as np

from . import geo
from .dem import RemoteTiff
from .paths import DATA

AVG_SCALE = 0.00004     # PDS label: AVERAGE_VISIBILITY = DN * 0.00004 + 0.0
AVG_SUN = "https://pgda.gsfc.nasa.gov/data/MoonIllumination/AVGVISIB_85S_060M_201608.TIF"
AVG_EARTH = "https://pgda.gsfc.nasa.gov/data/MoonIllumination/AVGVISIB_85S_060M_201608_EARTH.TIF"
SITE_TILES = {
    "malapert": ("Site23", "Malapert Massif"),
    "nobile-rim-1": ("Site06", "Nobile Rim 1"),
    "nobile-rim-2": ("DM2", "Nobile Rim 2"),
    "haworth": ("Haworth", "Haworth"),
}
OUT = DATA / "sites_selected.json"


def published_at(lat, lon):
    x, y = geo.stereo_forward(lat, lon)
    vals = {}
    for key, url in (("sun", AVG_SUN), ("earth", AVG_EARTH)):
        r = RemoteTiff(url).window(0, x - 200, x + 200, y - 200, y + 200)
        vals[key] = float(r.sample(np.array([x]), np.array([y]))[0] * AVG_SCALE)
    return vals


def select(shrink_m=1000.0):
    sun = RemoteTiff(AVG_SUN)
    out = []
    for sid, (tile, name) in SITE_TILES.items():
        t = RemoteTiff(f"https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/{tile}/{tile}_final_adj_5mpp_surf.tif")
        L = t.levels[0]
        xmin, xmax = L.x0 + shrink_m, L.x0 + L.width * L.pixel - shrink_m
        ymax, ymin = L.y0 - shrink_m, L.y0 - L.height * L.pixel + shrink_m
        r = sun.window(0, xmin, xmax, ymin, ymax)
        xs = r.x0 + (np.arange(r.z.shape[1]) + 0.5) * r.pixel
        ys = r.y0 - (np.arange(r.z.shape[0]) + 0.5) * r.pixel
        inside = (xs[None, :] >= xmin) & (xs[None, :] <= xmax) & (ys[:, None] >= ymin) & (ys[:, None] <= ymax)
        z = np.where(inside & ~np.isnan(r.z), r.z, -np.inf)
        i, j = np.unravel_index(int(np.argmax(z)), z.shape)
        lat, lon = geo.stereo_inverse(xs[j], ys[i])
        pub = published_at(float(lat), float(lon))
        out.append({"id": sid, "name": f"{name} (max published illumination in PGDA {tile} tile)",
                    "lat": float(lat), "lon": float(lon), "region": name, "clones": tile,
                    "x_m": float(xs[j]), "y_m": float(ys[i]),
                    "published_avg_sun": pub["sun"], "published_avg_earth": pub["earth"],
                    "source": f"Rule D-020: argmax of PGDA AVGVISIB_85S_060M_201608 within PGDA LOLA_5mpp {tile} footprint minus 1 km"})
        print(sid, round(lat, 4), round(lon, 4), pub, flush=True)
    OUT.write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    select()

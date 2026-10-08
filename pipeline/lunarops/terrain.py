"""Assemble the nested DEM windows a site needs (decision D-018)."""
from __future__ import annotations

from functools import lru_cache

from .dem import RemoteTiff, Raster
from .horizon import DEFAULT_SEGMENTS, window_boxes

PGDA = "https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/"
URL_10M = PGDA + "LDEM_83S_10MPP_ADJ.TIF"     # 83-90 S, 10 m (levels: 10, 20, 40 ... m)
URL_80M = PGDA + "LDEM_80S_80MPP_ADJ.TIF"     # 80-90 S, 80 m (levels: 80, 160, 320 m)
URL_240M = PGDA + "LDEM_60S_240MPP_ADJ.TIF"   # 60-90 S, 240 m (levels: 240, 480 ... m)

# segment index -> (url, overview level). Order inside rasters_for() is finest first.
NEST = [(URL_10M, 0), (URL_80M, 0), (URL_80M, 1), (URL_240M, 1)]


@lru_cache(maxsize=None)
def remote(url: str) -> RemoteTiff:
    return RemoteTiff(url)


def rasters_for(lat: float, lon: float, segments=DEFAULT_SEGMENTS, nest=NEST) -> tuple[list[Raster], list[dict]]:
    boxes = window_boxes(lat, lon, segments)
    rasters, used = [], []
    for (url, level), box in zip(nest, boxes):
        t = remote(url)
        r = t.window(level, *box)
        rasters.append(r)
        used.append({"url": url, "level": level, "pixel_m": t.levels[level].pixel, "box_m": [round(v) for v in box]})
    return rasters, used

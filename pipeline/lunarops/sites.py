"""Candidate sites with the provenance of every coordinate.

No coordinate is invented: each one is either published (paper, LROC, NASA) or
produced by a documented rule from a NASA product. `source` says which.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import geo


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    lat: float
    lon: float
    source: str
    region: str = ""
    clones: str = ""          # PGDA LOLA_5mpp site id with 100 DEM error clones, if any

    @classmethod
    def from_stereo_km(cls, id, name, x_km, y_km, source, **kw):
        lat, lon = geo.stereo_inverse(x_km * 1000.0, y_km * 1000.0)
        return cls(id, name, float(lat), float(lon), source, **kw)


SITES = [
    Site.from_stereo_km(
        "connecting-ridge-roi4", "Connecting Ridge (RoI 4)", -11.2875, -12.1675,
        "Barker et al. 2021, PSS 203:105119, Table 2, Site 1 RoI 4 centroid (stereographic X, Y)",
        region="Connecting Ridge", clones="Site01"),
    Site("im2-athena", "IM-2 Athena landing point (Mons Mouton)", -84.7906, 29.1957,
         "Wikipedia IM-2 landing coordinates; LROC pre-landing target -84.78, 29.13 E",
         region="Mons Mouton"),
]

def _load_selected():
    import json
    from .paths import DATA
    p = DATA / "sites_selected.json"
    if not p.exists():
        return []
    return [Site(d["id"], d["name"], d["lat"], d["lon"], d["source"], region=d["region"], clones=d["clones"])
            for d in json.loads(p.read_text())]


SITES = SITES + _load_selected()
BY_ID = {s.id: s for s in SITES}

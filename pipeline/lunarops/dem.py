"""Read only the parts of NASA GeoTIFF DEMs that a horizon needs.

The PGDA polar DEMs are cloud-optimized GeoTIFFs (512x512 tiles, deflate,
floating-point predictor, internal overviews). The 5 m site DEMs are
uncompressed one-row strips. Both can be read with HTTP range requests, so a
horizon for a handful of sites needs tens of megabytes instead of gigabytes.

Every fetched byte range is cached under data/raw/tiles/ and its SHA-256 is
recorded in data/tiles.lock.json, so a rerun uses identical bytes.

Georeferencing is read from the file (ModelPixelScale, ModelTiepoint,
PixelIsArea) and the projection keys are checked against the south polar
stereographic sphere used in geo.py; any mismatch raises.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import threading
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import requests
import tifffile

from .geo import R_MOON_M
from .paths import DATA, RAW

CACHE = RAW / "tiles"
TILE_LOCK = DATA / "tiles.lock.json"
_lock_mutex = threading.Lock()


class DemError(RuntimeError):
    pass


def _range_get(url: str, start: int, length: int) -> bytes:
    r = requests.get(url, headers={"Range": f"bytes={start}-{start + length - 1}"}, timeout=180)
    r.raise_for_status()
    if r.status_code != 206 and len(r.content) != length:
        raise DemError(f"server ignored Range for {url}")
    if len(r.content) != length:
        raise DemError(f"short read {len(r.content)} != {length} from {url}")
    return r.content


MIRROR = RAW / "pgda"          # optional whole-file mirror: <root>/<path after /data/ in the PGDA URL>
MIRROR_CONFIG = DATA / "mirror_roots.txt"   # extra mirror roots, one per line (e.g. a second drive); written by tools/get_clones.py


def mirror_roots() -> list[Path]:
    roots = [MIRROR]
    if MIRROR_CONFIG.exists():
        roots += [Path(line.strip()) for line in MIRROR_CONFIG.read_text().splitlines() if line.strip()]
    return roots


def mirror_path(url: str) -> Path | None:
    """Local copy of a PGDA file if one exists in any mirror root, else the default location."""
    marker = "pgda.gsfc.nasa.gov/data/"
    if marker not in url:
        return None
    rel = url.split(marker, 1)[1]
    for root in mirror_roots():
        if (root / rel).exists():
            return root / rel
    return MIRROR / rel


def _local_range(path: Path, start: int, length: int) -> bytes:
    with path.open("rb") as fh:
        fh.seek(start)
        data = fh.read(length)
    if len(data) != length:
        raise DemError(f"{path} is shorter than expected (incomplete download?)")
    return data


def _cached_range(url: str, start: int, length: int) -> bytes:
    local = mirror_path(url)
    if local is not None and local.exists():         # same bytes as the server, so the same pins apply
        data = _local_range(local, start, length)
        _check_pin(url, start, length, data)
        return data
    key = hashlib.sha1(f"{url}|{start}|{length}".encode()).hexdigest()
    path = CACHE / key[:2] / key
    if path.exists():
        data = path.read_bytes()
        _check_pin(url, start, length, data)
        return data
    data = _range_get(url, start, length)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    _check_pin(url, start, length, data)
    return data


def _check_pin(url: str, start: int, length: int, data: bytes) -> None:
    digest = hashlib.sha256(data).hexdigest()
    k = f"{url}#{start}+{length}"
    with _lock_mutex:
        lock = json.loads(TILE_LOCK.read_text()) if TILE_LOCK.exists() else {}
        if k in lock and lock[k] != digest:
            raise DemError(f"bytes changed for {k}; upstream file was modified")
        if k not in lock:
            lock[k] = digest
            TILE_LOCK.write_text(json.dumps(lock, indent=1, sort_keys=True))


def _unpredict_float32(buf: bytes, rows: int, cols: int) -> np.ndarray:
    """Undo TIFF predictor 3 (floating point, Adobe TN3) for little-endian float32."""
    b = np.frombuffer(buf, np.uint8).reshape(rows, cols * 4)
    b = np.cumsum(b, axis=1, dtype=np.uint8)               # horizontal byte differencing
    return b.reshape(rows, 4, cols).transpose(0, 2, 1).copy().view(">f4").reshape(rows, cols).astype(np.float32)


@dataclass
class Level:
    width: int
    height: int
    tile: int            # 0 for strips
    offsets: np.ndarray
    counts: np.ndarray
    pixel: float         # metres
    x0: float            # left edge of column 0 (metres)
    y0: float            # top edge of row 0 (metres)
    compression: int
    predictor: int
    dtype: str = "<f4"


class RemoteTiff:
    """A georeferenced TIFF on a web server, read lazily by tiles or rows."""

    HEADER_STEPS = (65_536, 600_000, 4_000_000)

    def __init__(self, url: str):
        self.url = url
        quiet = logging.getLogger("tifffile")
        level = quiet.level
        quiet.setLevel(logging.CRITICAL)          # a truncated header is expected on the first, small read
        try:
            for size in self.HEADER_STEPS:
                head = _cached_range(url, 0, size)
                tif = tifffile.TiffFile(io.BytesIO(head))
                p = tif.pages[0]
                if p.geotiff_tags and len(p.dataoffsets) > 0 and all(len(q.dataoffsets) for q in tif.pages):
                    break
            else:
                raise DemError(f"could not read TIFF header of {url}")
        finally:
            quiet.setLevel(level)
        if tif.byteorder != "<":
            raise DemError("only little-endian TIFFs are supported")
        p0 = tif.pages[0]
        gt = p0.geotiff_tags
        self._check_projection(gt)
        scale = gt["ModelPixelScale"][0]
        tie = gt["ModelTiepoint"]
        if int(gt.get("GTRasterTypeGeoKey", 1)) != 1:
            raise DemError("expected PixelIsArea raster")
        x0, y0 = tie[3] - tie[0] * scale, tie[4] + tie[1] * scale
        self.levels: list[Level] = []
        for p in tif.pages:
            if p.dtype not in (np.float32, np.int16):
                raise DemError(f"unexpected dtype {p.dtype}")
            f = p0.imagewidth / p.imagewidth
            self.levels.append(Level(p.imagewidth, p.imagelength, p.tilewidth if p.is_tiled else 0,
                                     np.asarray(p.dataoffsets, dtype=np.int64),
                                     np.asarray(p.databytecounts, dtype=np.int64),
                                     scale * f, x0, y0, int(p.compression), int(p.predictor),
                                     "<f4" if p.dtype == np.float32 else "<i2"))
        nod = p0.tags.get("GDAL_NODATA")
        txt = str(nod.value).replace(chr(0), "").strip() if nod is not None else ""
        self.nodata = float(txt) if txt and txt.lower() != "nan" else None

    @staticmethod
    def _check_projection(gt: dict) -> None:
        ok = (int(gt.get("ProjCoordTransGeoKey", 0)) == 15
              and abs(gt.get("ProjNatOriginLatGeoKey", 0) + 90.0) < 1e-9
              and abs(gt.get("ProjStraightVertPoleLongGeoKey", 0)) < 1e-9
              and abs(gt.get("GeogSemiMajorAxisGeoKey", 0) - R_MOON_M) < 1e-6
              and abs(gt.get("GeogSemiMinorAxisGeoKey", 0) - R_MOON_M) < 1e-6
              and abs(gt.get("ProjScaleAtNatOriginGeoKey", 1.0) - 1.0) < 1e-12
              and gt.get("ProjFalseEastingGeoKey", 0) == 0 and gt.get("ProjFalseNorthingGeoKey", 0) == 0)
        if not ok:
            raise DemError(f"projection is not the 1737.4 km south polar stereographic sphere: {gt}")

    # -- reading --------------------------------------------------------------
    def window(self, level: int, xmin: float, xmax: float, ymin: float, ymax: float) -> "Raster":
        """Mosaic of every tile/row of `level` that intersects the box (metres)."""
        L = self.levels[level]
        c0 = max(int(np.floor((xmin - L.x0) / L.pixel)), 0)
        c1 = min(int(np.ceil((xmax - L.x0) / L.pixel)), L.width)
        r0 = max(int(np.floor((L.y0 - ymax) / L.pixel)), 0)
        r1 = min(int(np.ceil((L.y0 - ymin) / L.pixel)), L.height)
        if c0 >= c1 or r0 >= r1:
            raise DemError("requested window is outside the DEM")
        if L.tile:
            t = L.tile
            ntx = -(-L.width // t)
            tr0, tr1, tc0, tc1 = r0 // t, (r1 - 1) // t + 1, c0 // t, (c1 - 1) // t + 1
            out = np.full(((tr1 - tr0) * t, (tc1 - tc0) * t), np.nan, np.float32)
            for tr in range(tr0, tr1):
                if tr * t >= L.height:
                    break
                for tc in range(tc0, tc1):
                    i = tr * ntx + tc
                    out[(tr - tr0) * t:(tr - tr0 + 1) * t, (tc - tc0) * t:(tc - tc0 + 1) * t] = self._tile(L, i)
            return Raster(out, L.x0 + tc0 * t * L.pixel, L.y0 - tr0 * t * L.pixel, L.pixel)
        # one-row strips, uncompressed
        if L.compression != 1:
            raise DemError("compressed strips are not supported")
        offs, cnts = L.offsets[r0:r1], L.counts[r0:r1]
        if not np.all(np.diff(offs) == cnts[:-1]):
            raise DemError("strips are not contiguous")
        blob = _cached_range(self.url, int(offs[0]), int(cnts.sum()))
        rows = np.frombuffer(blob, L.dtype).reshape(r1 - r0, L.width)
        return Raster(self._clean(rows), L.x0, L.y0 - r0 * L.pixel, L.pixel)

    def _clean(self, a: np.ndarray) -> np.ndarray:
        a = a.astype(np.float32)
        if self.nodata is not None:
            a[a == self.nodata] = np.nan
        return a

    def _tile(self, L: Level, i: int) -> np.ndarray:
        cnt = int(L.counts[i])
        if cnt == 0:
            return np.full((L.tile, L.tile), np.nan, np.float32)
        raw = _cached_range(self.url, int(L.offsets[i]), cnt)
        if L.compression in (8, 32946):
            raw = zlib.decompress(raw)
        elif L.compression != 1:
            raise DemError(f"unsupported compression {L.compression}")
        if L.predictor == 3 and L.dtype == "<f4":
            return self._clean(_unpredict_float32(raw, L.tile, L.tile))
        a = np.frombuffer(raw, L.dtype).reshape(L.tile, L.tile)
        if L.predictor == 2:          # horizontal differencing of integer samples
            a = np.cumsum(a, axis=1, dtype=np.int16 if L.dtype == "<i2" else np.float32)
        elif L.predictor != 1:
            raise DemError(f"unsupported predictor {L.predictor}")
        return self._clean(a)


@dataclass
class Raster:
    """A north-up grid in polar stereographic metres; values are heights (m) above 1737.4 km."""

    z: np.ndarray
    x0: float     # left edge
    y0: float     # top edge
    pixel: float

    @property
    def extent(self):
        h, w = self.z.shape
        return self.x0, self.x0 + w * self.pixel, self.y0 - h * self.pixel, self.y0

    def sample(self, x, y) -> np.ndarray:
        """Bilinear interpolation at pixel centres; NaN outside or near gaps."""
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        fc = (x - self.x0) / self.pixel - 0.5
        fr = (self.y0 - y) / self.pixel - 0.5
        c = np.floor(fc).astype(np.int64)
        r = np.floor(fr).astype(np.int64)
        h, w = self.z.shape
        ok = (c >= 0) & (r >= 0) & (c < w - 1) & (r < h - 1)
        cc, rr = np.where(ok, c, 0), np.where(ok, r, 0)
        tx, ty = fc - cc, fr - rr
        z = self.z
        v = ((1 - ty) * ((1 - tx) * z[rr, cc] + tx * z[rr, cc + 1])
             + ty * ((1 - tx) * z[rr + 1, cc] + tx * z[rr + 1, cc + 1]))
        return np.where(ok, v, np.nan)


def cache_size_bytes(root: Path = CACHE) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) if root.exists() else 0

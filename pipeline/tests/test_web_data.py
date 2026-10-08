"""Sanity of the files the browser reads (web/data): sizes, value ranges, encodings."""
import json

import numpy as np
import pytest

from lunarops.paths import WEB_DATA

META = WEB_DATA / "sites.json"
pytestmark = pytest.mark.skipif(not META.exists(), reason="web data not built")


def meta():
    return json.loads(META.read_text())


def test_site_series_encoding():
    m = meta()
    n, nh = m["grid"]["n"], len(m["heights_m"])
    for s in m["sites"]:
        buf = (WEB_DATA / f"site_{s['id']}.bin").read_bytes()
        assert len(buf) == n * (2 * nh + 8), s["id"]
        u8 = np.frombuffer(buf, np.uint8)
        assert u8[: nh * n].max() <= m["f_scale"]                       # visible solar fraction * f_scale
        assert (u8[nh * n: 2 * nh * n] >> 1).max() <= len(m["stations"])  # station index
        tail = buf[2 * nh * n:]
        az_s = np.frombuffer(tail, "<u2", n, 0); el_s = np.frombuffer(tail, "<i2", n, 2 * n)
        az_e = np.frombuffer(tail, "<u2", n, 4 * n); el_e = np.frombuffer(tail, "<i2", n, 6 * n)
        for az in (az_s, az_e):                                          # uint16 centidegrees (int16 would wrap > 327.67 deg)
            assert az.max() <= 36000                                     # 359.995 deg rounds to 36000 (= 0 deg)
        assert np.abs(el_s).max() < 1000 and np.abs(el_e).max() < 1500     # |el| < 10 deg / 15 deg near the pole


def test_horizons_and_ensembles():
    m = meta()
    for s in m["sites"]:
        for z, h in s["horizon"].items():
            assert len(h["elev_cdeg"]) == 1440 and len(h["dist_m"]) == 1440
            assert max(abs(v) for v in h["elev_cdeg"]) < 3000
        if "dispersion" in s:
            d = s["dispersion"]
            assert d["points"] == len(d["offsets_m"]) == 19
            for runs_h in d["runs"]:
                for r in runs_h:
                    on = r["on"]
                    assert all(a < b for a, b in zip(on[0::2], on[1::2]))       # runs are non-empty
                    assert all(b <= a for b, a in zip(on[1::2], on[2::2]))      # and sorted, non-overlapping
        if "terrain3d" in s:
            t = s["terrain3d"]
            assert (WEB_DATA / f"terrain_{s['id']}.bin").stat().st_size == t["n"] * t["n"] * 2

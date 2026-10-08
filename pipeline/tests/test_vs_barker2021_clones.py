"""Validation of the DEM-error ensemble against Barker et al. 2021, Table 2, Site 1 RoI 4.

Published (100 clones of the 2021 5 m DEM, 2024-01-01 .. 2026-01-01, hourly):
  z = 5 m: average illumination, 1st percentile (A) 88.12 %; longest shadow, 99th percentile 4.00 d
  z = 1 m: average illumination, 1st percentile A 69.61 %, B 52.19 %, C 86.81 %

Ours: the same clones (first N downloaded, N >= 20), the RoI 4 centroid only, our
horizon and visibility code (lunarops.clones --validate). Statistics are taken over
clones exactly as named in the paper (1st / 99th percentile).

Pass criteria FIXED BEFORE ANY CLONE WAS PROCESSED (2026-10-08, decision log D-024):
  z = 5 m: |our 1st percentile - 88.12| <= 3.0 pp  and  |our 99th pct shadow - 4.00 d| <= 1.5 d
  z = 1 m: 52.19 % <= our 1st percentile <= 86.81 %
A failure is reported as a failure; the criteria will not be moved afterwards.
"""
import json

import numpy as np
import pytest

from lunarops.paths import DERIVED

P = DERIVED / "validation_clones_connecting-ridge-roi4.json"


def members(z):
    if not P.exists():
        pytest.skip("run python -m lunarops.clones connecting-ridge-roi4 --validate first")
    rows = [m for m in json.loads(P.read_text())["members"] if m["z"] == z and m["name"].startswith("clone-")]
    if len(rows) < 20:
        pytest.skip(f"only {len(rows)} clones processed; need >= 20")
    return rows


def test_clones_z5():
    rows = members(5)
    p1 = np.percentile([r["avg_pct"] for r in rows], 1)
    p99 = np.percentile([r["lcsp_days"] for r in rows], 99)
    print(f"n={len(rows)} p1 avg {p1:.2f}% (paper 88.12), p99 shadow {p99:.2f} d (paper 4.00)")
    assert abs(p1 - 88.12) <= 3.0
    assert abs(p99 - 4.00) <= 1.5


def test_clones_z1():
    rows = members(1)
    p1 = np.percentile([r["avg_pct"] for r in rows], 1)
    print(f"n={len(rows)} p1 avg {p1:.2f}% (paper A 69.61, range 52.19-86.81)")
    assert 52.19 <= p1 <= 86.81

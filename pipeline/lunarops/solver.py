"""Mission-window metrics, feasibility and minimal relaxation (Stage 2, 2.12-2.16).

Reference implementation. The browser engine (web/engine.js) must reproduce
these numbers exactly on the same inputs; golden fixtures are generated from
this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Requirements:
    duration_h: float = 168.0          # mission length D
    min_sun_pct: float | None = 70.0   # average visible solar disc over the window
    min_dte_pct: float | None = 50.0   # share of time with a DTE link
    max_blackout_h: float | None = 24.0
    max_shadow_h: float | None = None  # longest period with no Sun at all (battery)
    lit_threshold: float = 0.5         # f >= this counts as "powered" for overlap

    def active(self):
        return {k: v for k, v in {"sun": self.min_sun_pct, "dte": self.min_dte_pct,
                                  "blackout": self.max_blackout_h, "shadow": self.max_shadow_h}.items() if v is not None}


SENSE = {"sun": +1, "dte": +1, "blackout": -1, "shadow": -1}   # +1: metric must be >= req
UNITS = {"sun": "pp", "dte": "pp", "blackout": "h", "shadow": "h"}


def runs(mask: np.ndarray):
    """Start/end indices (end exclusive) of the True runs of a boolean array."""
    m = np.concatenate([[False], np.asarray(mask, bool), [False]])
    d = np.diff(m.astype(np.int8))
    return np.flatnonzero(d == 1), np.flatnonzero(d == -1)


def longest_run_in_windows(mask: np.ndarray, starts: np.ndarray, length: int) -> np.ndarray:
    """For each window [i, i+length) the longest run of True samples inside it (samples)."""
    rs, re = runs(mask)
    out = np.zeros(len(starts), dtype=np.int64)
    if len(rs) == 0:
        return out
    ws = starts[:, None]
    we = ws + length
    clipped = np.minimum(re[None, :], we) - np.maximum(rs[None, :], ws)
    return np.maximum(clipped, 0).max(axis=1)


@dataclass
class SiteSeries:
    """Per-site time series on a uniform grid (dt seconds)."""

    site_id: str
    t0_utc: str
    dt_s: float
    f: np.ndarray        # visible fraction of the solar disc, 0..1
    dte: np.ndarray      # bool, direct-to-Earth link available


@dataclass
class WindowTable:
    site_id: str
    starts: np.ndarray            # sample index of each candidate start
    metrics: dict                 # name -> array over starts
    margins: dict = field(default_factory=dict)
    feasible: np.ndarray | None = None


def window_metrics(s: SiteSeries, req: Requirements, start_step_h: float = 1.0) -> WindowTable:
    per_h = 3600.0 / s.dt_s
    L = int(round(req.duration_h * per_h))
    step = max(int(round(start_step_h * per_h)), 1)
    n = len(s.f)
    starts = np.arange(0, n - L + 1, step)
    cf = np.concatenate([[0.0], np.cumsum(s.f, dtype=float)])
    cd = np.concatenate([[0], np.cumsum(s.dte.astype(np.int64))])
    lit = s.f >= req.lit_threshold
    ov = lit & s.dte
    co = np.concatenate([[0], np.cumsum(ov.astype(np.int64))])
    m = {
        "sun": 100.0 * (cf[starts + L] - cf[starts]) / L,
        "dte": 100.0 * (cd[starts + L] - cd[starts]) / L,
        "overlap": 100.0 * (co[starts + L] - co[starts]) / L,
        "blackout": longest_run_in_windows(~s.dte, starts, L) / per_h,
        "shadow": longest_run_in_windows(s.f <= 0.0, starts, L) / per_h,
    }
    return WindowTable(s.site_id, starts, m)


def evaluate(tables: list[WindowTable], req: Requirements) -> list[WindowTable]:
    act = req.active()
    for t in tables:
        t.margins = {k: SENSE[k] * (t.metrics[k] - v) for k, v in act.items()}
        t.feasible = np.all(np.stack([t.margins[k] >= -1e-9 for k in act]), axis=0) if act else np.ones(len(t.starts), bool)
    return tables


def minimal_relaxation(tables: list[WindowTable], req: Requirements) -> dict:
    """Exact single-constraint relaxation (2.16): best attainable value of k with all others held."""
    act = req.active()
    out = {}
    for k, v in act.items():
        others = [j for j in act if j != k]
        best, where = None, None
        for t in tables:
            ok = np.all(np.stack([t.margins[j] >= -1e-9 for j in others]), axis=0) if others else np.ones(len(t.starts), bool)
            if not ok.any():
                continue
            vals = t.metrics[k][ok]
            i = np.argmax(vals) if SENSE[k] > 0 else np.argmin(vals)
            if best is None or SENSE[k] * (vals[i] - best) > 0:
                best, where = float(vals[i]), (t.site_id, int(t.starts[ok][i]))
        if best is None:
            out[k] = {"relaxed_to": None, "change": None, "note": "relaxing this constraint alone is not enough"}
        else:
            already = SENSE[k] * (best - v) >= -1e-9
            out[k] = {"relaxed_to": best, "change": 0.0 if already else best - v, "at": where, "already_feasible": bool(already)}
    return out


def feasible_windows(t: WindowTable, dt_s: float, start_step_h: float = 1.0):
    """Merge consecutive feasible start times into launch-window-like intervals (start sample, end sample)."""
    if t.feasible is None or not t.feasible.any():
        return []
    rs, re = runs(t.feasible)
    return [(int(t.starts[a]), int(t.starts[b - 1])) for a, b in zip(rs, re)]

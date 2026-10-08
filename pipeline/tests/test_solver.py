"""Solver tests on hand-built series whose answers are known exactly."""
import numpy as np
import pytest

from lunarops.solver import (Requirements, SiteSeries, evaluate, feasible_windows,
                             longest_run_in_windows, minimal_relaxation, runs, window_metrics)

DT = 600.0          # 10 min
PER_H = 6


def series(f, dte, sid="s"):
    return SiteSeries(sid, "2027-01-01T00:00:00", DT, np.asarray(f, float), np.asarray(dte, bool))


def test_runs():
    s, e = runs(np.array([0, 1, 1, 0, 1, 0, 0, 1, 1, 1], bool))
    assert s.tolist() == [1, 4, 7] and e.tolist() == [3, 5, 10]


def test_longest_run_clipped_to_window():
    m = np.zeros(100, bool)
    m[10:40] = True          # 30-sample run
    starts = np.array([0, 20, 35, 50])
    got = longest_run_in_windows(m, starts, 25)
    assert got.tolist() == [15, 20, 5, 0]


def test_metrics_constant_series():
    n = 24 * 30 * PER_H
    s = series(np.full(n, 0.8), np.ones(n, bool))
    t = window_metrics(s, Requirements(duration_h=48))
    assert np.allclose(t.metrics["sun"], 80.0)
    assert np.allclose(t.metrics["dte"], 100.0)
    assert np.allclose(t.metrics["blackout"], 0.0)
    assert np.allclose(t.metrics["overlap"], 100.0)


def test_blackout_and_feasibility_and_relaxation():
    n = 24 * 20 * PER_H
    f = np.ones(n)
    dte = np.ones(n, bool)
    dte[24 * PER_H * 5: 24 * PER_H * 5 + 30 * PER_H] = False      # one 30 h blackout on day 5
    a = series(f, dte, "A")
    b = series(np.full(n, 0.6), np.ones(n, bool), "B")           # always talking, too dark
    req = Requirements(duration_h=72, min_sun_pct=70, min_dte_pct=50, max_blackout_h=24)
    ta, tb = window_metrics(a, req), window_metrics(b, req)
    evaluate([ta, tb], req)
    # B fails only the solar requirement, by exactly 10 pp everywhere
    assert not tb.feasible.any()
    assert np.allclose(tb.margins["sun"], -10.0)
    # A is feasible except for windows that contain more than 24 h of the blackout
    bad = ta.metrics["blackout"] > 24
    assert np.array_equal(ta.feasible, ~bad)
    assert ta.metrics["blackout"].max() == pytest.approx(30.0)
    wins = feasible_windows(ta, DT)
    assert len(wins) == 2                      # before and after the blackout
    # forbid A by tightening the blackout limit, then ask for the minimal relaxation
    strict = Requirements(duration_h=72, min_sun_pct=70, min_dte_pct=50, max_blackout_h=0.0)
    ta2, tb2 = window_metrics(a, strict), window_metrics(b, strict)
    evaluate([ta2, tb2], strict)
    assert ta2.feasible.any()                  # windows away from the blackout still pass
    rel = minimal_relaxation([ta2, tb2], strict)
    assert rel["sun"]["already_feasible"]
    # if only B existed, relaxing sun 70 -> 60 is the exact answer
    rel_b = minimal_relaxation([tb2], strict)
    assert rel_b["sun"]["relaxed_to"] == pytest.approx(60.0)
    assert rel_b["sun"]["change"] == pytest.approx(-10.0)

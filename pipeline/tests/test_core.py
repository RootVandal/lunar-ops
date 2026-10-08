"""Unit tests that need no network and no NASA data (analytic cases only)."""
import numpy as np
import pytest

from lunarops import geo, visibility
from lunarops.dem import Raster, _unpredict_float32
from lunarops.horizon import compute_horizon


# --- projection -------------------------------------------------------------
@pytest.mark.parametrize("lat,lon", [(-89.5, 0.0), (-85.0, 29.2), (-84.79, 129.0), (-80.0, -120.0), (-88.0, 180.0)])
def test_stereo_roundtrip_and_vector_form(lat, lon):
    x, y = geo.stereo_forward(lat, lon)
    la, lo = geo.stereo_inverse(x, y)
    assert la == pytest.approx(lat, abs=1e-10)
    assert ((lo - lon + 180) % 360 - 180) == pytest.approx(0.0, abs=1e-9)
    xv, yv = geo.unit_to_stereo(geo.latlon_to_vec(lat, lon, 1.0))
    assert xv == pytest.approx(x, rel=1e-12, abs=1e-6)
    assert yv == pytest.approx(y, rel=1e-12, abs=1e-6)


def test_stereo_scale_is_true_at_pole():
    # 1 km from the pole along lon=0 is ~1 km of stereographic y
    lat = -90.0 + np.degrees(1000.0 / geo.R_MOON_M)
    x, y = geo.stereo_forward(lat, 0.0)
    assert x == pytest.approx(0.0, abs=1e-9)
    assert y == pytest.approx(1000.0, rel=1e-6)


# --- topocentric frame --------------------------------------------------------
def test_azimuth_convention_north_east():
    site = geo.latlon_to_vec(-85.0, 0.0, 1.0)
    basis = geo.enu_basis(site)
    e, n, u = basis
    az, el = geo.az_el(np.stack([n, e, -n, u]), basis)
    assert az[0] == pytest.approx(0.0, abs=1e-9)
    assert az[1] == pytest.approx(90.0, abs=1e-9)
    assert az[2] == pytest.approx(180.0, abs=1e-9)
    assert el[3] == pytest.approx(90.0, abs=1e-9)
    # near the south pole, "north" points away from the pole (towards +x at lon 0)
    assert n[0] > 0.99


def test_pole_rejected():
    with pytest.raises(ValueError):
        geo.enu_basis(np.array([0.0, 0.0, -1.0]))


# --- solar disc ---------------------------------------------------------------
def test_segment_fraction_limits_and_monotonic():
    assert visibility.segment_fraction(1.0) == pytest.approx(1.0)
    assert visibility.segment_fraction(0.0) == pytest.approx(0.5)
    assert visibility.segment_fraction(-1.0) == pytest.approx(0.0)
    u = np.linspace(-1, 1, 201)
    assert np.all(np.diff(visibility.segment_fraction(u)) >= 0)
    # area of a circular segment, checked against numeric integration
    uu = 0.3
    xs = np.linspace(-1, 1, 200001)
    chord = 2 * np.sqrt(1 - xs**2)
    numeric = np.trapezoid(np.where(xs <= uu, chord, 0.0), xs) / np.pi
    assert visibility.segment_fraction(uu) == pytest.approx(numeric, abs=2e-5)  # grid step 1e-5 at the cut


def test_eclipse_overlap():
    rs, re = 0.27, 0.95
    assert visibility.disc_overlap_fraction(0.0, rs, re) == pytest.approx(1.0)
    assert visibility.disc_overlap_fraction(2.0, rs, re) == pytest.approx(0.0)
    half = visibility.disc_overlap_fraction(re, rs, re)   # Earth limb through the Sun's centre
    assert 0.4 < half < 0.6


# --- TIFF floating point predictor ------------------------------------------------
def test_unpredict_float32_roundtrip():
    rng = np.random.default_rng(1)
    a = rng.normal(0, 1000, (4, 6)).astype(np.float32)
    planes = a.astype(">f4").view(np.uint8).reshape(4, 6, 4).transpose(0, 2, 1).reshape(4, 24)
    enc = planes.copy()
    enc[:, 1:] = np.diff(planes.astype(np.int16), axis=1).astype(np.uint8)
    assert np.array_equal(_unpredict_float32(enc.tobytes(), 4, 6), a)


# --- horizon on a perfect sphere ------------------------------------------------
def _flat_raster(half_m=320_000.0, pixel=160.0):
    n = int(2 * half_m / pixel)
    return Raster(np.zeros((n, n), np.float32), -half_m, half_m, pixel)


@pytest.mark.parametrize("z", [2.0, 10.0])
def test_horizon_on_smooth_sphere_equals_dip(z):
    r = _flat_raster()
    hz = compute_horizon(-87.0, 45.0, z, [r], h_site_m=0.0)
    expected = geo.horizon_dip_deg(z)
    assert np.allclose(hz.elev, expected, atol=2e-4)
    assert np.all(hz.elev < 0)


def test_single_ridge_is_found_at_right_azimuth_and_distance():
    pixel = 80.0
    r = _flat_raster(pixel=pixel)
    lat, lon = -88.0, 0.0
    sx, sy = geo.stereo_forward(lat, lon)
    # a 500 m wall 20 km "north" of the site (north = +y at lon 0, away from the pole)
    xs = r.x0 + (np.arange(r.z.shape[1]) + 0.5) * pixel
    ys = r.y0 - (np.arange(r.z.shape[0]) + 0.5) * pixel
    X, Y = np.meshgrid(xs, ys)
    r.z[(np.abs(Y - (sy + 20_000)) < 200) & (np.abs(X - sx) < 3_000)] = 500.0
    hz = compute_horizon(lat, lon, 2.0, [r], h_site_m=0.0)
    i = int(np.argmax(hz.elev))
    assert min(hz.az[i], 360 - hz.az[i]) < 1.0
    assert abs(hz.dist_m[i] - 20_000) < 400
    # elevation of a 500 m wall at ~19.8 km including curvature
    s = hz.dist_m[i]
    g = s / geo.R_MOON_M
    expect = np.degrees(np.arctan2((geo.R_MOON_M + 500) * np.cos(g) - (geo.R_MOON_M + 2), (geo.R_MOON_M + 500) * np.sin(g)))
    assert hz.elev[i] == pytest.approx(expect, abs=0.02)

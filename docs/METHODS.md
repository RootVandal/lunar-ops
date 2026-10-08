# LUNAR//OPS — scientific methods

This document specifies every quantity the tool computes: **input → method → output → assumptions → limitations**.
Section numbers (2.1–2.16) are the ones used in the code comments. Validation results are in
[VALIDATION.md](VALIDATION.md) (generated from the test suite), data sources in [DATA.md](DATA.md),
and the reasons behind each choice in [DECISIONS.md](DECISIONS.md).

The method deliberately follows the published NASA GSFC approach (Mazarico et al. 2011; Barker et al. 2021, 2023)
so that our numbers can be compared directly with NASA products — and they are (see VALIDATION.md).

```
NASA / JPL data                  precomputed once (Python, pipeline/)              browser (web/, static files)
SPICE kernels (NAIF)  ─────────► Sun, Earth, DSN directions 2027–2028, 10 min ──┐
LOLA DEMs (NASA GSFC PGDA) ────► terrain skylines, 1440 azimuths, 2 heights   ──┼──► visibility series f(t), DTE(t)
5 m site DEMs + 100 error clones ► DEM-error ensemble (where NASA publishes it) ─┤        │
19 landing points per site ────► landing-error ensemble                        ─┘        ▼
JPL Horizons, Barker et al. 2021, PGDA AVGVISIB ─► validation tests         requirements ► solver ► site × date map,
                                                                             evidence, relaxation, robustness, timeline,
                                                                             skyline, 3D illustration
```

The browser never computes geometry; it decides. `web/engine.js` mirrors `pipeline/lunarops/solver.py`
and `web/tests/golden.html` checks both give identical results (max difference 5·10⁻¹⁰).

---

## 2.1–2.6 Geometry

### 2.1 Reference frame
- **Input:** planetocentric latitude φ, east longitude λ, terrain height h (from the DEM), sensor height z above ground.
- **Method:** frame `MOON_ME` (mean-Earth/polar-axis, DE421 realization — the frame of the LOLA DEMs), reference sphere R = 1737.4 km.
  **r** = (R + h + z)(cos φ cos λ, cos φ sin λ, sin φ).
  DEM pixels are south polar stereographic on the sphere: ρ = 2R tan(π/4 + φ/2), x = ρ sin λ, y = ρ cos λ
  (vector form used in code: x = 2R p_y/(1 − p_z), y = 2R p_x/(1 − p_z) for a unit vector p).
- **Assumptions:** local vertical = sphere normal (as LOLA and Horizons).
- **Limitations:** azimuth is undefined exactly at the pole; |φ| > 89.999° is rejected. The projection is checked against each GeoTIFF's geokeys at read time; a mismatch raises.

### 2.2 Time
- **Method:** UTC → TDB with `naif0012.tls`. Grid 2027-01-01 to 2029-01-01, Δt = 10 min (105 264 samples).
  The Sun moves ≈ 0.085° in azimuth per step, a third of its radius.
- **Limitations:** leap seconds announced after naif0012 are not included; durations are exact to ±10 min.

### 2.3 Lunar orientation
- **Method:** binary PCK `moon_pa_de440_200625.bpc` (DE440 librations) + fixed PA→ME rotation from `moon_de440_250416.tf`
  (`MOON_ME` is an alias of `MOON_ME_DE440_ME421`).
- **Limitations:** IAU_MOON (no physical librations) is never used.

### 2.4–2.5 Sun and Earth
- **Method:** SPICE `spkpos` in `MOON_ME`, aberration correction LT+S, ephemeris `de440s.bsp`; topocentric vectors = Moon-centred vector − site vector
  (identical to SPICE `azlcpo` for a surface observer to < 10⁻³°, tested).
  Angular radii: ρ☉ = asin(695 700 km / d☉) ≈ 0.27°, ρ⊕ = asin(6378.1 km / d⊕) ≈ 0.95°.
- **Validation:** 8761 hourly samples at the IM-2 site against JPL Horizons (DE441): max error 6·10⁻⁷° (Sun), 3·10⁻⁵° (Earth); criterion < 0.01° fixed in advance.
- **Limitations:** no relativistic light deflection (Horizons includes it; far below tolerance).

### 2.6 Topocentric geometry
- **Method:** east-north-up basis û = r/|r|, ê = ẑ×û/|ẑ×û|, n̂ = û×ê; el = asin(d·û), az = atan2(d·ê, d·n̂), clockwise from north (same convention as `azlcpo`).
- **Assumptions:** no atmosphere, no refraction.

## 2.7–2.8 Horizons

### 2.7 Three horizons
- **Mathematical horizon:** the plane el = 0° (what Horizons reports).
- **Terrain skyline H(α):** the highest terrain elevation angle along azimuth α. Only this decides visibility.
- **Visibility classes shown in the app:** above 0° and above the skyline (visible) · above 0° but below the skyline (*blocked by terrain*) · below 0° but above the skyline (*visible from a peak*) · neither.

### 2.8 Terrain ray casting
- **Input:** site, height z ∈ {1 m, 5 m} (the heights of Barker et al. 2021), nested NASA GSFC LOLA DEMs (PGDA product 90, Barker et al. 2023):

| Range | DEM | Sample step |
|---|---|---|
| 0–5 km | LDEM_83S_10MPP_ADJ (10 m) | 10 m |
| 5–30 km | LDEM_80S_80MPP_ADJ (80 m) | 80 m |
| 30–100 km | LDEM_80S_80MPP_ADJ, overview level 1 (160 m) | 160 m |
| 100–300 km | LDEM_60S_240MPP_ADJ, overview level 1 (480 m) | 480 m |

- **Method:** 1440 azimuths (0.25°, finer than the 0.53° solar disc). Points along the great circle in vector form
  p̂ = cos γ û + sin γ (cos α n̂ + sin α ê), γ = s/R; height by bilinear interpolation from the finest DEM that covers the point;
  elevation angle with exact curvature θ(s) = atan2(r_q cos γ − r_o, r_q sin γ), r_o = R + h_site + z, r_q = R + h(p̂); H(α) = max θ.
  The distance of the occluding point is stored too (used by explanations: "hidden by terrain 37 km away").
- **Output:** H(α), occluder distance, for each site and height.
- **Assumptions:** 300 km maximum range (Barker: 50–200 km far horizon).
- **Limitations:** boulders and features below the DEM's effective resolution (≈ 15–35 m) are not seen; nor is the lander itself. When the occluder is closer than 100 m, the app says so and flags the explanation as uncertain.
- **Validation:** coarsening the 30–300 km layers 2× changes the skyline by ≤ 0.017° (criterion < 0.05°); Connecting Ridge illumination reproduces Barker et al. 2021 (see VALIDATION.md).

## 2.9–2.11 Sun, Earth and the radio link

### 2.9 Visible fraction of the solar disc
- **Method:** the skyline is treated as a straight line across the disc at the Sun's azimuth (as Barker et al. 2021).
  u = clip((el☉ − H(az☉))/ρ☉, −1, 1), f_ter = 1 − (acos u − u√(1−u²))/π.
  Solar eclipses by Earth: overlap area of two discs (ρ☉, ρ⊕, separation δ), f = f_ter · (1 − f_ecl).
- **Output:** f(t) ∈ [0, 1], stored as f·250 in one byte (quantization 0.4 %).
- **Assumptions:** uniform disc (no limb darkening); skyline straight across the disc; terrain and Earth occlude independently.
- **Limitations:** all three only affect partial phases (sunrise, sunset, eclipse), not fully lit or fully dark periods.

### 2.10 Earth visibility
- **Method:** Earth's centre above the skyline: el⊕ > H(az⊕). For comparison with PGDA AVGVISIB_EARTH, their rule "any part of the disc visible" (el⊕ + ρ⊕ > H) is also computed.
- **Limitations:** antenna pattern and terrain multipath are not modelled.

### 2.11 Direct-to-Earth (DTE) link
- **Input:** DSN stations DSS-14 (Goldstone), DSS-43 (Canberra), DSS-63 (Madrid) from `earthstns_itrf93_260814.bsp` and `earth_topo_260814.tf`; Earth orientation `earth_1962_260806_2126_combined.bpc`; minimum antenna elevation 6° (DSN 810-005, module 302 Rev B, Table 1).
- **Method:** DTE(t) is true if at least one station sees the Moon at ≥ 6° above its local horizon **and** the lander sees that station (not just Earth's centre — they differ by up to 0.95°) above the lunar skyline.
- **Assumptions:** one antenna per complex, always available.
- **Limitations (all optimistic):** no DSN scheduling, no link budget, no station terrain masks, no relays. The app calls this a *geometric* link window.

## 2.12–2.13 Window metrics

For a landing window W = [t₀, t₀ + D] (t₀ on an hourly grid, D = 1–60 days):

| Metric | Definition | Unit |
|---|---|---|
| Solar availability | mean of f(t) over W (Barker et al. 2021 "average illumination") | % |
| Longest darkness (LCSP) | longest run with f = 0 inside W | h |
| DTE availability | share of W with DTE(t) | % |
| Longest blackout | longest run without DTE inside W, clipped to W | h |
| Power + link | share of W with f ≥ 0.5 and DTE at once (information only) | % |

- **Method:** prefix sums for shares (O(1) per window); run lists for longest runs. All sites × all landing hours are re-evaluated on every slider change.
- **Limitations:** irradiance on the panel is not lander power (no efficiency, dust, temperature, self-shadowing).

## 2.14 Robustness

The tool never treats a terrain-derived answer as certain. Two independent ensembles, both built only from published data:

### Method A — DEM error (NASA error clones)
- **Input:** PGDA product 78 (Barker et al. 2021): a 5 m DEM of the site region and 100 Monte Carlo *clones*. Each clone is a complete DEM = the published surface plus one realization of its error, built by NASA from LOLA ranging and orbit uncertainties with realistic spatial correlation (median RMS 0.3–0.5 m; 1σ map ranges 0.07–2 m around Connecting Ridge).
- **Method:** for each clone the skyline is recomputed with the clone inside 5 km and the same 10/80/240 m DEMs beyond (as Barker et al. — far terrain is three orders of magnitude less sensitive); then the full visibility series and the selected window are re-evaluated. The member *nominal-2021* (the surface the clones were made from) is evaluated too, so the spread is measured against the right reference; the main result uses the newer 2023 DEM and the version difference is reported separately.
- **Output:** share of clones in which the window still passes; pessimistic and optimistic value of every metric (worst / best member); label ROBUST ≥ 90 %, MARGINAL 50–90 %, FRAGILE < 50 % (our convention, stated in the app). With fewer than 20 clones the label reads PRELIMINARY.
- **Limitations:** available only where NASA publishes clones (Connecting Ridge, Malapert, Nobile Rim 1 & 2, Haworth among our sites; not IM-2). Boulders are not in the clones. Elsewhere the app says "not assessed" — no synthetic noise is invented.

### Method B — landing error
- **Input:** a radius of 250 m — the real example of IM-2, which landed about 250 m from its target (Spaceflight Now, 2025-03-07). It is an example, not a CLPS requirement.
- **Method:** 19 points (centre, 6 at 125 m, 12 at 250 m), each with its own terrain skyline from the same DEMs and its own visibility series. Link and darkness are evaluated from exact 10-minute run boundaries, sunlight from hourly means.
- **Output:** share of points where the window passes, worst point and why, pessimistic / optimistic metrics. On the site × date map, feasible days that hold at ≥ 90 % of points are dark green.
- **Limitations:** uniform sampling of the landing area (a real dispersion ellipse depends on the vehicle); slope and landing safety are not assessed.

## 2.15–2.16 Decisions

### 2.15 Feasibility
Each requirement is checked separately and gets a margin in its own unit (pp for shares, hours for durations). A window passes if all margins ≥ 0.
There is **no composite score**. Failures are explained with what failed, by how much, when, and why — the cause is classified from the data:
the body is below the mathematical horizon (libration), hidden by terrain at a given distance and azimuth, or no DSN antenna sees the Moon at ≥ 6°.

### 2.16 Minimal relaxation
If nothing passes, for each requirement k the engine holds all others and finds the best achievable value of metric k over all sites and landing hours:
q_k* = max m_k (or min, for upper limits) subject to δ_j ≥ 0 for all j ≠ k. This is exact, not a heuristic. If no window passes all the other requirements, relaxing k alone cannot help, and the app says so.

## Known limitations (summary)
- Geometric DTE only: no DSN scheduling, link budget, relays or commercial stations.
- Uniform solar disc; straight skyline across the disc.
- Features below DEM resolution (≈ 15–35 m), boulders and the lander body are not seen.
- Irradiance is for an ideal vertical, Sun-tracking panel.
- DEM-error robustness only where NASA publishes clones; landing-error sampling is uniform.
- The 3D view is an illustration: no result is computed there, and local cast shadows are not simulated.

## References
- Barker, M.K. et al. (2021) Improved LOLA elevation maps for south pole landing sites: error estimates and their impact on illumination conditions. *Planetary & Space Science* 203, 105119. doi:10.1016/j.pss.2020.105119
- Barker, M.K. et al. (2023) *Planetary Science Journal* 4, 183. doi:10.3847/PSJ/acf3e1; data doi:10.60903/gsfcpgda-lola-spole
- Mazarico, E. et al. (2011) Illumination conditions of the lunar polar regions using LOLA topography. *Icarus* 211, 1066–1081. doi:10.1016/j.icarus.2010.10.030
- NASA GSFC Planetary Geodesy Data Archive: products 69, 78, 90 — https://pgda.gsfc.nasa.gov/
- NAIF SPICE Toolkit and generic kernels — https://naif.jpl.nasa.gov/
- JPL Horizons — https://ssd.jpl.nasa.gov/horizons/
- DSN Telecommunications Link Design Handbook 810-005, module 302 Rev B (Antenna Positioning)
- Spaceflight Now (2025-03-07): Intuitive Machines IM-2 mission ends with lander on its side

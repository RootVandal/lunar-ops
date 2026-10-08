# LUNAR//OPS

**Where and when can a CLPS mission operate at the lunar south pole — and why do the other options fail?**

LUNAR//OPS is an open-source planning and education prototype on the topic of the NASA Space Apps
Challenge 2026 challenge *CLPS Lunar Mission Browser*. You state what a mission needs — sunlight on the
panels, time with a direct-to-Earth (DTE) link, the longest blackout and darkness
it can survive, how long it stays — and the tool searches every landing date in
2027–2028 at candidate south-pole sites. It answers with evidence: which sites and
dates work, which requirement fails elsewhere and by how much, what physically
causes the failure (libration, a ridge 37 km away, a DSN gap), and the smallest
change to the requirements that would make a mission possible.

> **Status.** Independent open-source tool, developed in October 2026 — before the Space Apps 2026 hackathon
> weekend (14–15 November). It is **not** a hackathon submission and is published openly so its dates are public.
>
> Not a NASA product and not endorsed by NASA. Not for flight operations.

**Live app:** https://rootvandal.github.io/lunar-ops/

## Why this is hard at the south pole

Measured with JPL Horizons for the IM-2 landing point and the pole (Nov 2026 – Nov 2027):

| | Sun elevation | Earth elevation | Earth absent up to |
|---|---|---|---|
| Geographic south pole | −1.55° … +1.56° | −7.10° … +6.57° | 14.8 days |
| IM-2 site, 84.8° S | −6.74° … +6.75° | −2.30° … +10.79° | 8.0 days |

With the Sun skimming the horizon, terrain decides everything — in both directions: a
ridge can hide a Sun that is above the mathematical horizon, and a peak can see a Sun
that is below it. LUNAR//OPS therefore never uses the mathematical horizon for a
decision; it always uses a skyline computed from NASA LOLA laser altimetry.

## What it does

1. **Define the mission** — length (1–60 days), minimum sunlight on the panels, optional limit on the longest darkness, panel/antenna height, minimum DTE link time, longest acceptable blackout.
2. **Find windows** — every landing hour of 2027–2028 at six south-pole sites is checked; a site × date map shows where and when the mission works, and which requirement fails elsewhere.
3. **Compare sites** — the same landing time at all six sites, every requirement with its margin. No composite score.
4. **Understand failures** — the cause of the longest blackout or darkness is classified from the data (libration, a ridge at a given distance, a DSN gap). If nothing works, the engine computes the exact smallest single change that brings a mission back.
5. **Inspect robustness** — the same window re-evaluated at 19 landing points within 250 m (IM-2 landed ≈ 250 m off target) and, where NASA publishes them, on NASA's Monte Carlo DEM error clones.
6. **Explore** — a timeline with sunrise / Earthset / link events, a skyline panorama that separates geometric from terrain-blocked visibility, and a 3D view of the terrain from the lander's eye.

A **Guided demo** button walks through a complete decision in eight deterministic steps; every view is also a shareable URL (`#d=30&sun=80&dte=60&blk=120&shd=48&h=1`).

## Evidence that the numbers are right

All checks run in the test suite; pass criteria were fixed before running them. Full table: [docs/VALIDATION.md](docs/VALIDATION.md).

| Check | Reference | Result | Criterion |
|---|---|---|---|
| Sun az/el, 8761 hourly samples | JPL Horizons (DE441) | max error 6×10⁻⁷ ° | < 0.01° |
| Earth az/el, 8761 hourly samples | JPL Horizons | max error 3×10⁻⁵ ° | < 0.01° |
| Moon-centred shortcut vs SPICE surface observer | SPICE `azlcpo` | < 10⁻³ ° | < 10⁻³ ° |
| Connecting Ridge RoI 4, 2024–2026, panels 5 m | Barker et al. 2021, Table 2: 88.1 % | **88.9 %**, longest shadow 3.75 d (paper: 4.0 d) | 85–97 %, ≤ 6 d |
| Same, panels 1 m | Barker et al. 2021: 52.2–86.8 % | 82.2 % | 52–95 % |
| DEM-error ensemble, 20 NASA clones, panels 5 m | Barker et al. 2021 (100 clones): 1st pct 88.12 %, longest shadow 4.00 d | **88.32 %**, 3.75 d | ±3 pp, ±1.5 d (fixed before processing) |
| Same, panels 1 m | Barker et al. 2021: 1st pct 69.61 % | 67.36 % | 52.19–86.81 % |
| Skyline convergence (far layers coarsened 2×) | same pipeline | ≤ 0.017° | < 0.05° |
| Browser engine vs Python solver | `web/tests/golden.html` | max difference 5×10⁻¹⁰ | identical |

## How it works

```
NASA / JPL data                 precomputed (Python, pipeline/)          browser (web/, no server)
SPICE kernels  ──────────────►  ephemerides 2027–2028, 10 min  ──┐
LOLA DEMs (PGDA, range reads) ► terrain horizons, 1440 azimuths ─┼─►  visibility f(t), DTE(t) ─► solver ─► site × date map
JPL Horizons   ──────────────►  validation tests                ─┘                                      evidence, timeline, skyline
```

* **Frame and ephemerides** — NAIF SPICE, DE440, `MOON_ME` (DE421 mean-Earth, the frame of the LOLA DEMs), light time + stellar aberration.
* **Terrain horizon** — ray casting over nested NASA GSFC LOLA DEMs (Barker et al. 2023): 10 m to 5 km, 80 m to 30 km, 160 m to 100 km, 480 m to 300 km, exact lunar curvature, after the method of Mazarico et al. 2011 / Barker et al. 2021.
* **Sunlight** — visible fraction of the solar disc split by the skyline, including Earth eclipses.
* **DTE link** — the lander sees a DSN antenna (DSS-14 Goldstone, DSS-43 Canberra, DSS-63 Madrid) above lunar terrain **and** that antenna sees the Moon ≥ 6° (DSN 810-005, module 302).
* **Decisions** — metrics per landing date (hourly) for the chosen mission length; per-requirement margins instead of a single score; exact minimal single-requirement relaxation.

Documentation: [methods](docs/METHODS.md) (16 quantities, each with input, method, output, assumptions and limitations) · [data sources](docs/DATA.md) · [validation](docs/VALIDATION.md) · [decision log](docs/DECISIONS.md).

## Sites

Every coordinate has a source; none is invented.

| Site | Coordinate source |
|---|---|
| Connecting Ridge (RoI 4) | Barker et al. 2021, Table 2 |
| IM-2 Athena landing point, Mons Mouton | published landing coordinates (84.7906° S, 29.1957° E) |
| Malapert Massif, Nobile Rim 1, Nobile Rim 2, Haworth | rule D-020: brightest published 60 m pixel (PGDA AVGVISIB) inside the NASA GSFC 5 m site DEM footprint |

## Run it

```bash
cd pipeline
python -m pip install numpy spiceypy tifffile requests pyyaml pytest
python -m lunarops.fetch          # SPICE kernels (77 MB), SHA-256 pinned
python -m lunarops.select_sites   # documented site rule (D-020)
python -m lunarops.build          # skylines (DEM tiles via HTTP range) + site series
python -m lunarops.dispersion     # landing-error ensemble (19 points per site)
python -m lunarops.terrain3d      # local terrain patches for the 3D view
python ../tools/get_clones.py Site01 --count 30          # optional: NASA DEM error clones (41 MB each)
python -m lunarops.clones connecting-ridge-roi4 --validate
python -m pytest                  # unit tests + validation against Horizons and Barker et al. 2021
python -m lunarops.report && python -m lunarops.golden && python -m lunarops.docs
python -m lunarops.pack           # gzip copies of web/data/*.bin (what the published site ships)
cd .. && python tools/serve.py 8801   # then open http://localhost:8801
```

`web/tests/golden.html` checks that the browser engine and the Python solver give identical numbers.

## Limitations (also shown in the app)

* Geometric DTE link only: no DSN scheduling, no link budget, no relay satellites.
* Uniform solar disc (no limb darkening); straight skyline across the disc.
* Boulders and features below the DEM's effective resolution (≈ 15–35 m) are not seen.
* Irradiance is for an ideal vertical, Sun-tracking panel — not lander power.
* Terrain-uncertainty robustness is reported only where NASA publishes DEM error clones; landing-error sampling is uniform.
* The 3D view is an illustration: no result is computed there and local cast shadows are not simulated.

## Data and credits

NASA LRO LOLA via the NASA GSFC Planetary Geodesy Data Archive (Barker et al. 2021, PSS 203:105119;
Barker et al. 2023, PSJ 4:183, data doi:10.60903/gsfcpgda-lola-spole; Mazarico et al. 2011, Icarus 211:1066),
NAIF SPICE Toolkit and generic kernels, JPL Horizons, DSN 810-005. Third-party code: three.js (MIT), loaded from
cdn.jsdelivr.net for the optional 3D view; Python packages numpy, spiceypy, tifffile, requests, PyYAML, pytest.
NASA content is used under NASA's media usage guidelines; the NASA insignia is not used.

## License

Original code and documentation: Apache License 2.0 (see `LICENSE`).

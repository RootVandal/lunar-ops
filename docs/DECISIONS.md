# Decision log

Every scientific and architectural choice, why it was made, and what was rejected. A changed decision gets a new row;
old rows are kept and marked *superseded*.

| # | Decision | Why | Rejected | Status |
|---|---|---|---|---|
| D-001 | Ephemeris DE440 (`de440s.bsp`) | NAIF's lunar orientation is built from DE440; the Horizons check (DE441) shows the difference is negligible | newer DE442 | accepted |
| D-002 | Frame `MOON_ME`, sphere 1737.4 km | The frame of the LOLA DEMs and of Horizons' topocentric output | IAU_MOON, MOON_PA | accepted |
| D-003 | Skyline: nested DEMs, 1440 azimuths, 300 km | Comparable with the GSFC method (Barker et al. 2021) | one 20 m grid; 720 azimuths | accepted after convergence test (D-018) |
| D-004 | Sun = visible fraction of the disc, no limb darkening | As Barker et al.; affects only partial phases | "Sun centre above horizon" | accepted |
| D-005 | DTE = lunar terrain + DSN antenna ≥ 6° | Official DSN limit (810-005); the ray goes to the station, not Earth's centre | "Earth above the horizon" | accepted |
| D-006 | Metrics by GSFC definitions (average illumination, LCIP, LCSP) | Directly comparable with publications | own definitions | accepted |
| D-007 | Terrain robustness only from official NASA clones, otherwise "not assessed" | Do not invent an error model | noise on the ERR map with an invented correlation | accepted |
| D-008 | Add robustness to landing error | Real IM-2 example (≈ 250 m, crater); works for every site | — | accepted |
| D-009 | No composite score; margins + Pareto view | Team requirement; a score hides causes | weighted index | accepted |
| D-010 | Every feature is justified against Impact / Creativity / Validity / Relevance / Presentation | Team rule; the official 2026 criteria are published on 13 Nov 2026 | — | to verify on 13 Nov |
| D-011 | "Minimum Sun elevation" replaced by margin over the skyline | At the pole the Sun never exceeds 1.56° | elevation thresholds 2–8° | accepted |
| D-012 | Planning horizon 2027–2028, 10-minute step | Next CLPS flights and Artemis; 0.085° per step | 1 year at 1 h | accepted |
| D-013 | Heavy computation precomputed, solver in the browser | The demo does not depend on a server or an API | live Horizons queries | accepted |
| D-014 | Corrected an early claim about IM-2 | The company named Sun direction, panel orientation and cold in the crater among the causes | "not related to illumination" | accepted |
| D-015 | Terrain from PGDA 90 (2023 adjusted DEMs): 240 m, 80 m, 10 m | Newer, same `MOON_ME`, has error and effective-resolution maps, readable by HTTP range | 2017 PDS LDEM (kept as an optional cross-check) | accepted |
| D-016 | AVGVISIB maps as `.TIF`, not `*_COG.TIF` | The COG links on PGDA returned Not Found (checked 2026-10-08) | COG versions | accepted |
| D-017 | SHA-256 pinned on first download (`manifest.lock.json`, `tiles.lock.json`); data not in git | No published checksums; reproducible without gigabytes in the repository | git LFS | accepted |
| D-018 | DEMs read as tiles by HTTP range; layers 10/80/160/480 m | ≈ 28 KB/s link; Barker et al. 2021 check passes on these layers; 2× coarsening moves the skyline ≤ 0.017° | downloading 0.66 GB whole | accepted |
| D-019 | Validation criteria fixed before running; checks whose criterion was set afterwards are labelled *indicative* | Honest validation is the main argument for the judges | tuning thresholds to the result | accepted |
| D-020 | Point inside a NASA 5 m site tile = brightest published 60 m pixel (AVGVISIB) | No published targets inside the regions; the rule is reproducible | tile centre; "by eye" | accepted |
| D-021 | Mission length up to 60 days | Short missions almost always pass; sites separate when the lander must survive the night | 14-day limit | accepted |
| D-022 | Plain JavaScript UI without a build step; engine checked against Python by a golden test | No Node.js; static hosting | React / Next.js | accepted |
| D-023 | Landing robustness: 19 points within 250 m, exact run boundaries | Works on cached data | synthetic noise | accepted |
| D-024 | DEM-error robustness from the NASA clones (Method A); pass criteria against Barker et al. 2021 Table 2 fixed before any clone was processed (see `pipeline/tests/test_vs_barker2021_clones.py`) | Uses NASA's own uncertainty model; a pre-registered comparison | — | accepted |
| D-025 | The PGDA `*_err.tif` files are full DEMs (surface + error realization), not error maps | Checked on Site01: clone heights differ from the surface by centimetres to metres; the 1σ map `*_toterr.tif` is 0.07–2 m. Corrects an assumption in the original Stage 2 checklist | treating them as additive error fields | accepted |
| D-026 | Ensemble "pessimistic / optimistic" = worst / best member (not 10th / 90th percentile) | With 19 points or ≤ 30 clones percentiles are unstable; extremes are honest and easy to read | percentiles | accepted |
| D-027 | Map cells: dark green = passes at ≥ 90 % of landing points, light green = passes only at the target point | Robustness must be visible where the decision is made, not only in a detail panel | a separate robustness map | accepted |
| D-028 | 3D terrain view is an illustration; its skyline ring, Sun/Earth positions and pin colours come from the engine | Avoids a second, inconsistent "truth"; local cast shadows would be misleading at 1–2° Sun elevation | shadow-mapped 3D lighting as evidence | accepted |
| D-029 | Guided demo and every scenario are URL states (`#d=30&sun=80…`) | The demo is deterministic and every screenshot is reproducible from its link | free-form demo | accepted |
| D-030 | Published openly in October 2026 as an independent open-source tool, not as a hackathon submission; any Space Apps 2026 submission will be written during the event (or will disclose this work if the organisers allow it) | The 2026 Participant FAQ: "Teams are not allowed to begin working on the challenges prior to the hackathon" | hiding the dates | accepted |

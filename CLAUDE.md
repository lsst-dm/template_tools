# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Tools and dashboards for visualizing Rubin Observatory Alert Production
template coverage on the sky. There are **two independent dashboards**, each
backed by a Python data generator and an Aladin Lite HTML viewer:

### 1. Deployed template coverage (`web/template_coverage.html`)

Shows which tracts/patches have `template_coadd` datasets actually deployed in
the Butler.

- **`scripts/query_embargo_templates.py`** — Queries the `embargo` Butler for
  `template_coadd` datasets in `LSSTCam/templates`. It produces three kinds of
  output in one run:
  1. `web/deployed_template_data.json` — tract corner coords + per-band summary
     stats (patch/tract counts, area in deg² via spherical excess).
  2. `output/template_coverage_healpix_{band}_nside{N}.fits` — per-band
     fractional HEALPix coverage maps (NESTED), computed by sub-sampling patch
     polygons at 4× the target NSIDE.
  3. `output/template_coverage_healpix_{band}_nside{N}.png` — Mollweide renders
     of the same maps with galactic/ecliptic plane overlays.
- **`web/template_coverage.html`** — loads `deployed_template_data.json`,
  renders tract polygons on Aladin Lite with per-band toggles.

### 2. N-exposure coverage (`web/nexp_coverage.html`)

Shows the *input* exposure depth (nexp) feeding template generation, before
templates are built — answers "where do we have enough images to make a
template."

- **`scripts/generate_nexp_dashboard_data.py`** — reads healsparse nexp maps
  (`.hsp` files), degrades them for display, assigns pixels to tracts, computes
  per-tract fraction of pixels above each nexp threshold, and writes
  `web/nexp_dashboard_data.json` (large, ~20 MB).
- **`web/nexp_coverage.html`** — loads `nexp_dashboard_data.json` plus
  (optionally) `deployed_template_data.json` as a white overlay, so you can
  compare *input depth* against *already-deployed templates* on the same map.
  Has band + nexp-threshold + min-coverage-fraction controls.
- **`scripts/healpix_to_tracts.py`** — same tract-fraction computation as the
  dashboard generator but exports a flat `output/tract_nexp_fractions.csv`
  instead of JSON (for offline analysis).

The three generators share **`scripts/common.py`**, which holds the skymap
loading, pixel→tract assignment, tract-corner extraction, and per-tract
fraction logic.

### Upstream input: the `.hsp` nexp maps

The `.hsp` files in `output_incremental_test/` are **decasu** outputs, not
produced by anything in this repo. `config/decasu_incremental_templates_config.yaml`
is the decasu config that generates them: it queries the LSST consdb for
science visits since `day_obs >= 20250424` across specific `BLOCK-*` programs,
applies quality cuts (eff_time, psf_sigma, zero_point) and a bad-detector list,
and accumulates `nexp` and `psf_fwhm` maps at NSIDE 1024.

## Running

### Regenerate deployed-template data + maps

Requires the LSST Science Pipelines environment (Butler access to `embargo`):

```bash
python scripts/query_embargo_templates.py            # default NSIDE 64
python scripts/query_embargo_templates.py --nside 128
```

Writes `web/deployed_template_data.json` and FITS/PNG maps into `output/`.

### Regenerate nexp dashboard data

Requires the pipelines env (uses `/repo/main` for the skymap) plus the `.hsp`
inputs in `output_incremental_test/`:

```bash
python scripts/generate_nexp_dashboard_data.py        # -> web/nexp_dashboard_data.json
python scripts/healpix_to_tracts.py                    # -> output/tract_nexp_fractions.csv
```

Both accept `--input-dir`, `--bands`, `--butler-repo`, and (for the dashboard
generator) `--display-nside`.

### Aladin Lite source (CDS primary vs. mirror)

Both dashboards load Aladin Lite via `web/aladin_config.js`, which exposes
`window.loadAladin()` and resolves to `{ A, survey }`. The HTML pages run
their main code in a `<script type="module">` so they can `await` it. The
`ALADIN_SOURCE` constant in that file selects the backend:

- `cds` — classic script from `aladin.cds.unistra.fr` (defines global `A`),
  survey `P/DSS2/color` (resolved via the CDS MocServer).
- `mirror` — pinned npm build from jsDelivr (an ES module whose default
  export is `A`), survey loaded directly from
  `https://skies.esac.esa.int/DSSColor` so no CDS lookup is needed.

A `?aladin=cds|mirror` URL query parameter overrides the file setting for
testing. The two builds load differently (classic script vs. `import()`), so
keep both code paths in `loadAladin()` when adding a new source.

### Deploy

Each dashboard has its own production + dev sync script. They push the HTML,
`aladin_config.js`, and the JSON each dashboard fetches, then make the files
world-readable. All four scripts `cd` to the repo root and source files from
`web/`.

```bash
# Deployed-template dashboard (web/template_coverage.html + web/deployed_template_data.json)
./deploy/sync.sh             # -> ~/public_html/template_coverage/ (production)
./deploy/dev_sync.sh         # -> ~/public_html/dev_template_coverage/ (dev/testing)

# Nexp dashboard (web/nexp_coverage.html + web/nexp_dashboard_data.json
#                 + web/deployed_template_data.json overlay)
./deploy/sync_nexp.sh        # -> ~/public_html/nexp_coverage/ (production)
./deploy/dev_sync_nexp.sh    # -> ~/public_html/dev_nexp_coverage/ (dev/testing)
```

Note: the nexp sync also ships `deployed_template_data.json` (the white
comparison overlay) and `nexp_dashboard_data.json` is ~20 MB, so its first
rsync is noticeably slower than the template dashboard's.

### Local preview

Serve the directory over HTTP (relative `fetch()` of the JSON fails on
`file://` due to CORS):

```bash
cd web && python -m http.server
# then open template_coverage.html or nexp_coverage.html
```

## Key Dependencies

All from the LSST Science Pipelines stack (no separate build step):

- **Butler / skymap**: `lsst.daf.butler`, `lsst.geom`
- **HEALPix**: `healpy`, `hpgeom`, `healsparse`
- **Numerics / IO**: `numpy`, `pandas`, `astropy`, `matplotlib`
- **Frontend**: [Aladin Lite v3](https://aladin.cds.unistra.fr/AladinLite/doc/)
  from CDN

## Design Notes

- **Two skymap repos are in play**: `scripts/query_embargo_templates.py` reads
  the skymap from the `embargo` repo; the nexp scripts default to `/repo/main`.
  Both use the `lsst_cells_v2` skymap from the `skymaps` collection.
- **Two different band-color palettes exist** — these are intentionally
  different and should not be unified blindly:
  - PNG/Mollweide maps use the colorblind-friendly RTN-045 palette in
    `BAND_COLORS` in `scripts/query_embargo_templates.py`.
  - The HTML dashboards use a brighter screen palette in their own
    `BAND_COLORS` JS constants.
- Tract polygons come from `tract_info.getInnerSkyPolygon().getVertices()`;
  patch polygons from `patch_info.inner_sky_polygon`.
- Coordinates are rounded when serialized to keep JSON small (tract corners to
  3 decimals, display-pixel corners to 2).
- Area calculations use spherical excess (solid angle) → square degrees.
- The nexp dashboard JSON is large (~20 MB); it is degraded to a lower display
  NSIDE (default 64) for the rendered pixel layer while tract fractions are
  computed from the full-resolution `.hsp` map.

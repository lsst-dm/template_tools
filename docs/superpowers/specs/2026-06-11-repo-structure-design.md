# Repo structure formalization — design

Date: 2026-06-11

## Goal

Impose more formal structure on the `template_tools` repo. Three things, per
the user:

1. **Tidy the layout** — move source into role-based subdirectories and stop
   generated artifacts from cluttering the root.
2. **Reduce duplication** — extract the Butler/HEALPix/tract logic copied across
   the three Python generators into a shared module.
3. **Project hygiene** — add `.gitignore`, ruff config, a README, and a small
   set of unit tests.

Explicitly **out of scope**: making the repo a pip-installable Python package
(no `pyproject.toml`, no `src/` package, no console entry points). It stays a
script-based repo, just organized.

## Current state

8 tracked files, all flat in the repo root:

- `query_embargo_templates.py`, `generate_nexp_dashboard_data.py`,
  `healpix_to_tracts.py` (Python generators)
- `template_coverage.html`, `nexp_coverage.html` (dashboards)
- `sync.sh`, `dev_sync.sh` (deploy; `sync_nexp.sh`/`dev_sync_nexp.sh` exist
  untracked)
- `decasu_incremental_templates_config.yaml` (external decasu config)

Generated artifacts (untracked, currently in root): per-band FITS + PNG coverage
maps, `deployed_template_data.json`, `nexp_dashboard_data.json`,
`tract_nexp_fractions.csv`, `log_decasu_incremental.txt`,
`output_incremental_test/`, `.ipynb_checkpoints/`.

No README, `.gitignore`, ruff config, or tests.

## Path coupling (constraints the design must respect)

- The dashboards `fetch()` their JSON by **bare filename**, so HTML and its JSON
  must be co-located at both preview and deploy time.
- The deploy scripts `rsync` files from the current working directory into
  `~/public_html/...`, expecting HTML + JSON to be siblings there.
- The generators write their output files to the current working directory.

## Target layout

```
template_tools/
  README.md
  .gitignore
  ruff.toml
  scripts/
    common.py
    query_embargo_templates.py
    generate_nexp_dashboard_data.py
    healpix_to_tracts.py
  web/
    template_coverage.html
    nexp_coverage.html
  deploy/
    sync.sh  dev_sync.sh
    sync_nexp.sh  dev_sync_nexp.sh
  config/
    decasu_incremental_templates_config.yaml
  output/              # gitignored: FITS, PNG, CSV, logs
  tests/
    conftest.py
    test_common.py
  docs/superpowers/specs/2026-06-11-repo-structure-design.md
```

### Decision A — `common.py` lives in `scripts/`

Because we are not packaging, keeping `common.py` as a sibling of the generators
lets them `import common` with no `sys.path` manipulation: running
`python scripts/<generator>.py` automatically puts `scripts/` on `sys.path[0]`.
A root-level `common.py` would require a path workaround in every script.
`tests/conftest.py` adds `scripts/` to `sys.path` so tests can import it.

### Decision B — dashboard JSON is written into `web/`

The generators write the JSON the dashboards consume
(`deployed_template_data.json`, `nexp_dashboard_data.json`) into `web/`, which is
gitignored via `web/*.json`. This keeps:

- **local preview trivial:** `cd web && python -m http.server`
- **deploy trivial:** sync scripts rsync `*.html` + `*.json` from `web/`
- the bare-filename `fetch()` unchanged.

Bulkier, non-web artifacts (FITS, PNG, CSV, decasu log) go to `output/`. The
deployed-template generator currently emits both dashboard JSON *and* FITS/PNG;
after the change it writes JSON to `web/` and FITS/PNG to `output/`.

## Deduplication — `scripts/common.py`

The three generators independently re-implement the same operations. `common.py`
holds the shared pieces; behavior is preserved exactly.

- `BANDS = ["u", "g", "r", "i", "z", "y"]` — the constant duplicated in all
  three scripts.
- `load_skymap(butler_repo, skymap_name="lsst_cells_v2")` — replaces
  `get_skymap()` (query_embargo, hardwired to `embargo`) and `load_skymap()`
  (nexp scripts, default `/repo/main`). The repo stays a caller-supplied
  argument so each script keeps its existing default.
- `assign_pixels_to_tracts(valid_pixels, nside, skymap)` — the
  `pix2ang → ra/dec → findTractIdArray` block, currently in `healpix_to_tracts`
  and inline in `generate_nexp_dashboard_data.build_tract_data`.
- `tract_corners(tract_info, ndigits=3)` — `getInnerSkyPolygon().getVertices()
  → SpherePoint → (ra, dec)` with the `FutureWarning` suppression. Returns a
  canonical `[[ra, dec], ...]` list; callers reformat as needed (the
  deployed-template script maps it to `{"ra": ..., "dec": ...}` dicts).
- `compute_tract_fractions(tract_ids, values, thresholds)` — the per-tract
  "fraction of pixels ≥ threshold" loop shared by `healpix_to_tracts` (CSV
  output) and the nexp dashboard generator (JSON output).

After extraction, each generator keeps only its unique logic: Butler querying,
healsparse map degrading, FITS/PNG rendering, and output-format assembly, plus
imports from `common`.

### Intentional differences preserved (do NOT unify)

- `THRESHOLDS` differ by design: `healpix_to_tracts` uses `[1, 2, 3, 5, 10]`;
  the dashboard generator uses `[1, 2, 3, 4, 5, 7, 10]`. Each script keeps its
  own list and passes it to `compute_tract_fractions`.
- Butler repo defaults differ (`embargo` vs `/repo/main`) — preserved via the
  `load_skymap` argument.

## Hygiene

- **`.gitignore`**: `output/`, `web/*.json`, `*.fits`, `*.png`, `*.csv`,
  `log_*.txt`, `.ipynb_checkpoints/`.
- **`ruff.toml`**: line length 110; ignore `E133, E226, E228, N802, N803, N806,
  N812, N813, N815, N816, W503` (matches the DM global Python style). Enables
  `ruff check scripts/ tests/`.
- **`README.md`**: lean, human-facing — what the two dashboards are, how to
  regenerate data, preview, and deploy. Cross-references `CLAUDE.md` rather than
  duplicating its detail.
- **`tests/test_common.py`**: unit tests for the pure-logic helpers that need no
  Butler:
  - `compute_tract_fractions` — synthetic `tract_ids`/`values` arrays produce
    known fractions at each threshold.
  - `tract_corners` — formatting/rounding against a small fake tract object
    exposing `getInnerSkyPolygon().getVertices()`.
  - `load_skymap` and `assign_pixels_to_tracts` require a real Butler/skymap and
    are left untested for now (noted here intentionally).
  - `conftest.py` puts `scripts/` on `sys.path`.

## Files that need edits beyond moving

- **Generators**: import from `common`; drop the now-shared local functions;
  redirect output paths (dashboard JSON → `web/`, FITS/PNG/CSV → `output/`,
  defaults overridable by existing CLI args).
- **Deploy scripts**: resolve paths relative to the repo root (e.g.
  `cd "$(dirname "$0")/.."`) and source HTML + JSON from `web/`.
- **CLAUDE.md**: update the file paths and run/preview/deploy commands to match
  the new layout.

## Success criteria

- Repo root contains only top-level dirs + `README.md`, `.gitignore`,
  `ruff.toml`, `CLAUDE.md` (and the existing `.git`/docs).
- `git status` is clean of generated artifacts.
- Each generator runs from the repo root and produces byte-equivalent output
  content to today (in the new locations).
- `ruff check scripts/ tests/` passes.
- `pytest tests/` passes.
- Local preview and both deploy scripts work against the new layout.
```

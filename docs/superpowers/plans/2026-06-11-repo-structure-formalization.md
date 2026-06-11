# Repo Structure Formalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize `template_tools` into role-based subdirectories, extract shared Butler/HEALPix/tract logic into `scripts/common.py`, and add project hygiene (`.gitignore`, `ruff.toml`, `README.md`, unit tests) — while keeping every generator's output byte-equivalent to today.

**Architecture:** Stays a script-based repo (no pip packaging). Source moves to `scripts/`, dashboards to `web/`, deploy scripts to `deploy/`, decasu config to `config/`. `scripts/common.py` is a plain sibling module the generators `import common` (no `sys.path` hacks); `tests/conftest.py` puts `scripts/` on the path for pytest. Dashboard JSON is written into `web/` (gitignored) so the bare-filename `fetch()`, local preview, and rsync deploys all keep working unchanged. Bulkier artifacts (FITS/PNG/CSV/logs) go to `output/` (gitignored).

**Tech Stack:** Python (LSST Science Pipelines: `lsst.daf.butler`, `lsst.geom`; `healpy`, `hpgeom`, `healsparse`, `numpy`, `pandas`, `astropy`, `matplotlib`), Aladin Lite v3 (CDN), bash deploy scripts, pytest, ruff.

---

## Reference design

Spec: `docs/superpowers/specs/2026-06-11-repo-structure-design.md`.

Target layout:

```
template_tools/
  README.md  .gitignore  ruff.toml  CLAUDE.md
  scripts/   common.py  query_embargo_templates.py  generate_nexp_dashboard_data.py  healpix_to_tracts.py
  web/       template_coverage.html  nexp_coverage.html   (+ gitignored *.json)
  deploy/    sync.sh  dev_sync.sh  sync_nexp.sh  dev_sync_nexp.sh
  config/    decasu_incremental_templates_config.yaml
  output/    (gitignored: FITS, PNG, CSV, logs)
  tests/     conftest.py  test_common.py
  docs/superpowers/...
```

**Byte-equivalence rules to preserve (verify mentally on every generator edit):**
- `compute_tract_fractions` returns *unrounded* float fractions; the CSV writer applies `%.4f`, the nexp generator applies `round(...,4)`.
- `tract_corners(..., ndigits=None)` for `query_embargo_templates.py` (it currently does **not** round); `ndigits=3` for the nexp generator (it currently rounds to 3).
- Tract iteration stays in ascending tract-id order (`np.unique`).
- Butler repo defaults unchanged: `embargo` for the template query, `/repo/main` for the nexp scripts.
- `THRESHOLDS` stay per-script: `[1, 2, 3, 5, 10]` (healpix CSV) vs `[1, 2, 3, 4, 5, 7, 10]` (nexp dashboard).

---

## Task 1: Scaffolding — directories and hygiene files

**Files:**
- Create: `scripts/`, `web/`, `deploy/`, `config/`, `output/`, `tests/` (directories)
- Create: `.gitignore`
- Create: `ruff.toml`

- [ ] **Step 1: Create the directories**

Run:
```bash
mkdir -p scripts web deploy config output tests
```

- [ ] **Step 2: Write `.gitignore`**

Create `.gitignore`:
```gitignore
# Generated artifacts
output/
web/*.json
*.fits
*.png
*.csv
log_*.txt

# Decasu input maps (large, not produced by this repo)
output_incremental_test/

# Notebook checkpoints
.ipynb_checkpoints/
```

- [ ] **Step 3: Write `ruff.toml`**

Create `ruff.toml` (matches the DM global Python style):
```toml
line-length = 110

[lint]
ignore = [
    "E133", "E226", "E228",
    "N802", "N803", "N806", "N812", "N813", "N815", "N816",
    "W503",
]
```

Note: `ruff` may print a warning that `W503`/`E133` have no effect (they are flake8-era codes kept for parity with the DM style guide). That warning is harmless.

- [ ] **Step 4: Commit**

```bash
git add .gitignore ruff.toml
git commit -m "Add gitignore and ruff config; scaffold dirs"
```

(`scripts/`, `web/`, etc. are empty so far and won't appear in git until they contain tracked files — that happens in Task 2.)

---

## Task 2: Move existing files into the new layout

**Files:**
- Move (tracked): `query_embargo_templates.py`, `generate_nexp_dashboard_data.py`, `healpix_to_tracts.py` → `scripts/`
- Move (tracked): `template_coverage.html`, `nexp_coverage.html` → `web/`
- Move (tracked): `sync.sh`, `dev_sync.sh` → `deploy/`
- Move (untracked): `sync_nexp.sh`, `dev_sync_nexp.sh` → `deploy/`
- Move (tracked): `decasu_incremental_templates_config.yaml` → `config/`
- Move (untracked generated artifacts): JSON → `web/`, FITS/PNG/CSV/log → `output/`

- [ ] **Step 1: Move tracked source with `git mv`**

```bash
git mv query_embargo_templates.py generate_nexp_dashboard_data.py healpix_to_tracts.py scripts/
git mv template_coverage.html nexp_coverage.html web/
git mv sync.sh dev_sync.sh deploy/
git mv decasu_incremental_templates_config.yaml config/
```

- [ ] **Step 2: Move untracked deploy scripts (plain `mv`, they are not yet tracked)**

```bash
mv sync_nexp.sh dev_sync_nexp.sh deploy/
```

- [ ] **Step 3: Relocate existing generated artifacts so the root is clean and preview/deploy still find the JSON**

```bash
mv deployed_template_data.json nexp_dashboard_data.json web/ 2>/dev/null || true
mv template_coverage_healpix_*.fits template_coverage_healpix_*.png output/ 2>/dev/null || true
mv tract_nexp_fractions.csv log_decasu_incremental.txt output/ 2>/dev/null || true
```

- [ ] **Step 4: Verify the root is clean**

Run:
```bash
ls -1
git status
```
Expected: root shows only directories (`config docs deploy output scripts tests web`) plus `.gitignore CLAUDE.md ruff.toml` (and `.git`, `output_incremental_test`). `git status` shows the renames staged and no stray generated artifacts as untracked (they are now gitignored or moved). `CLAUDE.md` and the `deploy/*_nexp.sh` scripts show as untracked — they get added in later tasks.

- [ ] **Step 5: Commit the moves**

```bash
git add deploy/sync_nexp.sh deploy/dev_sync_nexp.sh
git commit -m "Move sources into role-based subdirectories"
```

---

## Task 3: Create `scripts/common.py` (TDD)

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_common.py`
- Create: `scripts/common.py`

- [ ] **Step 1: Write `tests/conftest.py`**

Create `tests/conftest.py` (puts `scripts/` on `sys.path` so tests can `import common`):
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_common.py`:
```python
import numpy as np
import pytest

import common
from lsst.geom import SpherePoint, degrees


def test_compute_tract_fractions_basic():
    tract_ids = np.array([10, 10, 10, 20, 20])
    values = np.array([1, 3, 5, 2, 8])
    thresholds = [1, 2, 5]

    records = common.compute_tract_fractions(tract_ids, values, thresholds)

    assert [r["tract"] for r in records] == [10, 20]
    assert all(isinstance(r["tract"], int) for r in records)

    t10, t20 = records
    assert t10["n_pixels"] == 3 and isinstance(t10["n_pixels"], int)
    assert t10["fractions"][1] == pytest.approx(1.0)
    assert t10["fractions"][2] == pytest.approx(2 / 3)
    assert t10["fractions"][5] == pytest.approx(1 / 3)
    assert all(isinstance(v, float) for v in t10["fractions"].values())

    assert t20["n_pixels"] == 2
    assert t20["fractions"][1] == pytest.approx(1.0)
    assert t20["fractions"][2] == pytest.approx(1.0)
    assert t20["fractions"][5] == pytest.approx(0.5)


class _FakePolygon:
    def __init__(self, vertices):
        self._vertices = vertices

    def getVertices(self):
        return self._vertices


class _FakeTract:
    def __init__(self, vertices):
        self._polygon = _FakePolygon(vertices)

    def getInnerSkyPolygon(self):
        return self._polygon


def _unit_vector(ra_deg, dec_deg):
    return SpherePoint(ra_deg * degrees, dec_deg * degrees).getVector()


def test_tract_corners_rounds_by_default():
    verts = [_unit_vector(10.123456, -5.654321), _unit_vector(11.0, -6.0)]
    tract = _FakeTract(verts)

    corners = common.tract_corners(tract)

    assert corners == [[10.123, -5.654], [11.0, -6.0]]


def test_tract_corners_no_rounding_when_ndigits_none():
    verts = [_unit_vector(10.123456, -5.654321)]
    tract = _FakeTract(verts)

    corners = common.tract_corners(tract, ndigits=None)

    ra, dec = corners[0]
    assert ra == pytest.approx(10.123456, abs=1e-6)
    assert dec == pytest.approx(-5.654321, abs=1e-6)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run:
```bash
pytest tests/test_common.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'common'` (collection error), because `scripts/common.py` does not exist yet.

- [ ] **Step 4: Write `scripts/common.py`**

Create `scripts/common.py`:
```python
"""Shared Butler / HEALPix / tract helpers for the template-tools generators."""

import warnings

import healpy as hp
import numpy as np

import lsst.daf.butler as dafButler
from lsst.geom import SpherePoint

BANDS = ["u", "g", "r", "i", "z", "y"]


def load_skymap(butler_repo, skymap_name="lsst_cells_v2"):
    """Load a skymap from a Butler repo's ``skymaps`` collection."""
    butler = dafButler.Butler(butler_repo)
    return butler.get("skyMap", skymap=skymap_name, collections="skymaps")


def assign_pixels_to_tracts(valid_pixels, nside, skymap):
    """Return tract IDs for each valid HEALPix pixel (NESTED ordering)."""
    theta, phi = hp.pix2ang(nside, valid_pixels, nest=True)
    ra = np.degrees(phi)
    dec = 90.0 - np.degrees(theta)
    return skymap.findTractIdArray(ra, dec, degrees=True)


def tract_corners(tract_info, ndigits=3):
    """Return tract inner-polygon corners as ``[[ra, dec], ...]`` in degrees.

    Parameters
    ----------
    tract_info : object
        Skymap tract info exposing ``getInnerSkyPolygon().getVertices()``.
    ndigits : int or None, optional
        Decimal places to round to. If ``None``, coordinates are not rounded.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        vertices = tract_info.getInnerSkyPolygon().getVertices()
    corners = []
    for v in vertices:
        point = SpherePoint(v)
        ra = point.getRa().asDegrees()
        dec = point.getDec().asDegrees()
        if ndigits is not None:
            ra = round(ra, ndigits)
            dec = round(dec, ndigits)
        corners.append([ra, dec])
    return corners


def compute_tract_fractions(tract_ids, values, thresholds):
    """For each unique tract, compute the fraction of pixels >= each threshold.

    Returns a list of dicts, ordered by ascending tract id, each with keys
    ``tract`` (int), ``n_pixels`` (int), and ``fractions`` (dict mapping each
    threshold to an unrounded float). Callers apply their own rounding/format.
    """
    records = []
    for tract_id in np.unique(tract_ids):
        mask = tract_ids == tract_id
        tract_values = values[mask]
        n_pixels = int(len(tract_values))
        fractions = {
            thresh: float(np.sum(tract_values >= thresh) / n_pixels)
            for thresh in thresholds
        }
        records.append({
            "tract": int(tract_id),
            "n_pixels": n_pixels,
            "fractions": fractions,
        })
    return records
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:
```bash
pytest tests/test_common.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 6: Lint the new module and tests**

Run:
```bash
ruff check scripts/common.py tests/
```
Expected: no errors (ignore the harmless `W503`/`E133` "no effect" warning, if any).

- [ ] **Step 7: Commit**

```bash
git add scripts/common.py tests/conftest.py tests/test_common.py
git commit -m "Add scripts/common.py with shared helpers and unit tests"
```

---

## Task 4: Refactor `scripts/query_embargo_templates.py` to use `common` and write to `web/`/`output/`

**Files:**
- Modify: `scripts/query_embargo_templates.py`

The script keeps all its unique logic (Butler query, area, patch polygons, HEALPix coverage, FITS/PNG rendering, `BAND_COLORS`). It loses its private `get_skymap()` and the body of `get_tract_corners()`, gains `import common`, repo-relative output paths, and reformats `common.tract_corners` output to the existing `{"ra":..., "dec":...}` dict shape.

- [ ] **Step 1: Update imports and add repo-relative path constants**

In `scripts/query_embargo_templates.py`, the import block currently ends at the `from lsst.geom import SpherePoint` line (around line 23) followed by `STERADIANS_TO_SQDEG = ...`. Add `from pathlib import Path` to the stdlib imports, add `import common`, and define path constants. After editing, the top of the file reads:

```python
"""
Query the embargo Butler for deployed template_coadd datasets in
LSSTCam/templates and produce a JSON data file with tract corner
coordinates for the embargo templates dashboard, plus per-band
HEALPix fractional coverage maps.
"""

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import healpy as hp
import hpgeom as hpg
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from astropy.io import fits

from lsst.geom import SpherePoint

import common

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = REPO_ROOT / "web"
OUTPUT_DIR = REPO_ROOT / "output"

STERADIANS_TO_SQDEG = (180.0 / math.pi) ** 2
```

Note: `lsst.daf.butler` is no longer imported here (skymap loading moves to `common`). `SpherePoint` is still used directly by `get_patch_polygons`.

- [ ] **Step 2: Delete the private `get_skymap()` function**

Remove the whole function (originally lines 73-76):
```python
def get_skymap():
    """Load the lsst_cells_v2 skymap from the embargo Butler."""
    butler = dafButler.Butler("embargo")
    return butler.get("skyMap", skymap="lsst_cells_v2", collections="skymaps")
```

- [ ] **Step 3: Replace the body of `get_tract_corners()` to delegate to `common.tract_corners` (unrounded, then reformat to dicts)**

Replace the existing `get_tract_corners` (originally lines 79-98) with:
```python
def get_tract_corners(skymap, tracts_by_band):
    """Compute RA, Dec corners for each tract that has any patch coverage."""
    records = []
    for band, tract_ids in tracts_by_band.items():
        for tract_id in sorted(tract_ids):
            corners = [
                {"ra": ra, "dec": dec}
                for ra, dec in common.tract_corners(skymap[tract_id], ndigits=None)
            ]
            records.append({
                "band": band,
                "tract": tract_id,
                "corners": corners,
            })
    return records
```

`ndigits=None` reproduces the original unrounded coordinates exactly; the list-of-pairs is remapped to the original `{"ra":..., "dec":...}` dict shape, so the JSON is byte-identical.

- [ ] **Step 4: Use `common.BANDS` in the Butler query loop**

In `query_template_patches` (originally line 56), replace the inline band list:
```python
    for band in ['u', 'g', 'r', 'i', 'z', 'y']:
```
with:
```python
    for band in common.BANDS:
```

- [ ] **Step 5: Load the skymap via `common.load_skymap("embargo")`**

In `main()` (originally line 280), replace:
```python
    skymap = get_skymap()
```
with:
```python
    skymap = common.load_skymap("embargo")
```

- [ ] **Step 6: Write the JSON to `web/` and FITS/PNG to `output/`**

In `main()`, ensure the output dirs exist and redirect the paths. Replace the JSON-writing block (originally lines 293-298):
```python
    outfile = "deployed_template_data.json"
    with open(outfile, "w") as f:
        json.dump(output, f)
```
with:
```python
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    outfile = WEB_DIR / "deployed_template_data.json"
    with open(outfile, "w") as f:
        json.dump(output, f)
```

Then in the FITS/PNG loop (originally lines 304-308), replace:
```python
    for band, cov_map in coverage_maps.items():
        fits_fname = f"template_coverage_healpix_{band}_nside{args.nside}.fits"
        png_fname = f"template_coverage_healpix_{band}_nside{args.nside}.png"
        write_healpix_fits(cov_map, args.nside, band, fits_fname)
        write_healpix_png(cov_map, args.nside, band, png_fname)
```
with:
```python
    for band, cov_map in coverage_maps.items():
        fits_fname = OUTPUT_DIR / f"template_coverage_healpix_{band}_nside{args.nside}.fits"
        png_fname = OUTPUT_DIR / f"template_coverage_healpix_{band}_nside{args.nside}.png"
        write_healpix_fits(cov_map, args.nside, band, str(fits_fname))
        write_healpix_png(cov_map, args.nside, band, str(png_fname))
```

(`write_healpix_fits`/`write_healpix_png` and the `print` lines accept these path objects; the `print(f"  {band}: {fits_fname}, {png_fname} ...")` line works unchanged since `Path` stringifies.)

- [ ] **Step 7: Lint**

Run:
```bash
ruff check scripts/query_embargo_templates.py
```
Expected: no errors. (If ruff flags the intentional `matplotlib.use("Agg")`-before-`pyplot` import ordering with `E402`, that matches the pre-existing code; leave it. If it newly flags it, add a `# noqa: E402` on the `import matplotlib.pyplot as plt` line to preserve the required ordering.)

- [ ] **Step 8: Smoke-test if Butler access is available (optional but recommended)**

If running in the pipelines env with `embargo` access:
```bash
python scripts/query_embargo_templates.py --nside 64
```
Expected: writes `web/deployed_template_data.json` and `output/template_coverage_healpix_*.fits|png`. Compare the JSON against a known-good copy if one exists (content should be identical to the pre-refactor output).

- [ ] **Step 9: Commit**

```bash
git add scripts/query_embargo_templates.py
git commit -m "Refactor template query to use common helpers and new output dirs"
```

---

## Task 5: Refactor `scripts/generate_nexp_dashboard_data.py` to use `common` and write JSON to `web/`

**Files:**
- Modify: `scripts/generate_nexp_dashboard_data.py`

Keeps its unique logic: `get_healpix_cell_corners`, `build_nexp_layer`, the display-pixel assembly, and the output structure. Loses its private `load_skymap`, the inline pix2ang/tract-id block, the inline corner extraction, and the inline fraction loop — all replaced by `common`.

- [ ] **Step 1: Update imports and add path constants**

Replace the import block (originally lines 9-23) with:
```python
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import healpy as hp
import healsparse
import numpy as np

import common

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = REPO_ROOT / "web"

BANDS = common.BANDS
THRESHOLDS = [1, 2, 3, 4, 5, 7, 10]
```

Note: `warnings`, `lsst.daf.butler`, and `lsst.geom.SpherePoint` are no longer imported here — that logic now lives in `common`. `BANDS` is re-exported from `common`; `THRESHOLDS` stays local (intentionally different from the CSV script).

- [ ] **Step 2: Delete the private `load_skymap()` function**

Remove (originally lines 26-28):
```python
def load_skymap(butler_repo="/repo/main", skymap_name="lsst_cells_v2"):
    butler = dafButler.Butler(butler_repo)
    return butler.get("skyMap", skymap=skymap_name, collections="skymaps")
```

- [ ] **Step 3: Rewrite `build_tract_data()` to use `common.assign_pixels_to_tracts`, `common.compute_tract_fractions`, and `common.tract_corners`**

Replace the entire `build_tract_data` function (originally lines 68-111) with:
```python
def build_tract_data(input_dir, band, skymap):
    """Compute tract polygons and coverage fractions for a band."""
    filename = input_dir / f"incremental_template_inputs_{band}_nexp_sum.hsp"
    hsp_map = healsparse.HealSparseMap.read(str(filename))
    valid_pixels = hsp_map.valid_pixels
    values = hsp_map[valid_pixels]
    nside = hsp_map.nside_sparse

    tract_ids = common.assign_pixels_to_tracts(valid_pixels, nside, skymap)

    tracts_data = []
    for record in common.compute_tract_fractions(tract_ids, values, THRESHOLDS):
        tract_id = record["tract"]
        corners = common.tract_corners(skymap[tract_id], ndigits=3)
        fractions = {
            str(thresh): round(record["fractions"][thresh], 4)
            for thresh in THRESHOLDS
        }
        tracts_data.append({
            "id": tract_id,
            "corners": corners,
            "n": record["n_pixels"],
            "f": fractions,
        })

    return tracts_data
```

Byte-equivalence: `compute_tract_fractions` iterates `np.unique(tract_ids)` (ascending), same as the original loop; `tract_id`, `n`, and the `round(...,4)` fractions match the original exactly; `tract_corners(..., ndigits=3)` reproduces the original rounded `[[ra,dec],...]` corners.

- [ ] **Step 4: Load the skymap via `common.load_skymap` and write JSON to `web/`**

In `main()`, replace the skymap load (originally line 139):
```python
    skymap = load_skymap(args.butler_repo)
```
with:
```python
    skymap = common.load_skymap(args.butler_repo)
```

Change the `--output` default (originally lines 120-123) from:
```python
    parser.add_argument(
        "--output", type=Path, default=Path("nexp_dashboard_data.json"),
        help="Output JSON file",
    )
```
to:
```python
    parser.add_argument(
        "--output", type=Path, default=WEB_DIR / "nexp_dashboard_data.json",
        help="Output JSON file",
    )
```

And ensure the directory exists right before writing (originally line 164, `with open(args.output, "w") as f:`). Insert just above it:
```python
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f)
```

- [ ] **Step 5: Lint**

Run:
```bash
ruff check scripts/generate_nexp_dashboard_data.py
```
Expected: no errors.

- [ ] **Step 6: Smoke-test if inputs + Butler are available (optional)**

```bash
python scripts/generate_nexp_dashboard_data.py --bands g
```
Expected: writes `web/nexp_dashboard_data.json`. Tract `id`/`n`/`f` and `corners` content should match the pre-refactor output.

- [ ] **Step 7: Commit**

```bash
git add scripts/generate_nexp_dashboard_data.py
git commit -m "Refactor nexp dashboard generator to use common helpers"
```

---

## Task 6: Refactor `scripts/healpix_to_tracts.py` to use `common` and write CSV to `output/`

**Files:**
- Modify: `scripts/healpix_to_tracts.py`

Keeps its unique logic: `process_band`, the DataFrame assembly, column ordering, and CSV writing. Loses its private `load_skymap`, `assign_pixels_to_tracts`, and `compute_tract_fractions`.

- [ ] **Step 1: Update imports and add path constants**

Replace the import block + constants (originally lines 4-21) with:
```python
import argparse
from pathlib import Path

import healsparse
import pandas as pd

import common

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"

BANDS = common.BANDS
THRESHOLDS = [1, 2, 3, 5, 10]
```

Note: `healpy`, `numpy`, and `lsst.daf.butler` are no longer imported here (that logic moved to `common`). `THRESHOLDS` stays local (intentionally different from the nexp dashboard).

- [ ] **Step 2: Delete the private `load_skymap`, `assign_pixels_to_tracts`, and `compute_tract_fractions`**

Remove all three functions (originally lines 19-46). They are now in `common`.

- [ ] **Step 3: Rewrite `process_band()` to use the `common` helpers**

Replace `process_band` (originally lines 49-60) with:
```python
def process_band(band, input_dir, skymap):
    filename = input_dir / f"incremental_template_inputs_{band}_nexp_sum.hsp"
    hsp_map = healsparse.HealSparseMap.read(str(filename))
    valid_pixels = hsp_map.valid_pixels
    values = hsp_map[valid_pixels]
    nside = hsp_map.nside_sparse

    tract_ids = common.assign_pixels_to_tracts(valid_pixels, nside, skymap)

    records = []
    for record in common.compute_tract_fractions(tract_ids, values, THRESHOLDS):
        row = {"tract": record["tract"], "n_pixels": record["n_pixels"]}
        for thresh in THRESHOLDS:
            row[f"frac_ge_{thresh}"] = record["fractions"][thresh]
        records.append(row)

    df = pd.DataFrame(records)
    df["band"] = band
    return df
```

Byte-equivalence: the per-row dict has the same keys (`tract`, `n_pixels`, `frac_ge_{t}`) and unrounded float values as before; the DataFrame, `col_order`, sort, and `to_csv(..., float_format="%.4f")` are unchanged, so the CSV is byte-identical.

- [ ] **Step 4: Load the skymap via `common.load_skymap` and write the CSV to `output/`**

In `main()`, replace the skymap load (originally line 92):
```python
    skymap = load_skymap(args.butler_repo)
```
with:
```python
    skymap = common.load_skymap(args.butler_repo)
```

Change the `--output` default (originally lines 71-76) from:
```python
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tract_nexp_fractions.csv"),
        help="Output CSV file",
    )
```
to:
```python
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_DIR / "tract_nexp_fractions.csv",
        help="Output CSV file",
    )
```

And ensure the directory exists before the write (originally line 104, `result.to_csv(...)`). Insert just above it:
```python
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False, float_format="%.4f")
```

- [ ] **Step 5: Lint**

Run:
```bash
ruff check scripts/healpix_to_tracts.py
```
Expected: no errors.

- [ ] **Step 6: Smoke-test if inputs + Butler are available (optional)**

```bash
python scripts/healpix_to_tracts.py --bands g
```
Expected: writes `output/tract_nexp_fractions.csv`; content matches the pre-refactor CSV.

- [ ] **Step 7: Commit**

```bash
git add scripts/healpix_to_tracts.py
git commit -m "Refactor healpix_to_tracts to use common helpers"
```

---

## Task 7: Update deploy scripts for the new layout

**Files:**
- Modify: `deploy/sync.sh`
- Modify: `deploy/dev_sync.sh`
- Modify: `deploy/sync_nexp.sh`
- Modify: `deploy/dev_sync_nexp.sh`

Each script `cd`s to the repo root (one level up from `deploy/`) and rsyncs HTML + JSON from `web/`. Targets and chmod logic are unchanged.

- [ ] **Step 1: Rewrite `deploy/sync.sh`**

```bash
#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
rsync -av web/template_coverage.html web/deployed_template_data.json ~/public_html/template_coverage/
chmod a+r ~/public_html/template_coverage/template_coverage.html
chmod a+r ~/public_html/template_coverage/deployed_template_data.json
```

- [ ] **Step 2: Rewrite `deploy/dev_sync.sh`**

```bash
#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
rsync -av web/template_coverage.html web/deployed_template_data.json ~/public_html/dev_template_coverage/
chmod a+r ~/public_html/dev_template_coverage/template_coverage.html
chmod a+r ~/public_html/dev_template_coverage/deployed_template_data.json
```

- [ ] **Step 3: Rewrite `deploy/sync_nexp.sh`**

```bash
#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
rsync -av web/nexp_coverage.html web/nexp_dashboard_data.json web/deployed_template_data.json ~/public_html/nexp_coverage/
chmod a+r ~/public_html/nexp_coverage/nexp_coverage.html
chmod a+r ~/public_html/nexp_coverage/nexp_dashboard_data.json
chmod a+r ~/public_html/nexp_coverage/deployed_template_data.json
```

- [ ] **Step 4: Rewrite `deploy/dev_sync_nexp.sh`**

```bash
#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
rsync -av web/nexp_coverage.html web/nexp_dashboard_data.json web/deployed_template_data.json ~/public_html/dev_nexp_coverage/
chmod a+r ~/public_html/dev_nexp_coverage/nexp_coverage.html
chmod a+r ~/public_html/dev_nexp_coverage/nexp_dashboard_data.json
chmod a+r ~/public_html/dev_nexp_coverage/deployed_template_data.json
```

- [ ] **Step 5: Re-assert the executable bit**

Run:
```bash
chmod +x deploy/sync.sh deploy/dev_sync.sh deploy/sync_nexp.sh deploy/dev_sync_nexp.sh
```

- [ ] **Step 6: Sanity-check path resolution without deploying**

Run:
```bash
bash -c 'cd "$(dirname deploy/sync.sh)/.." 2>/dev/null; pwd'
ls web/*.html
```
Expected: confirms `web/template_coverage.html` and `web/nexp_coverage.html` exist. (Do not run the real sync scripts here — they push to `~/public_html`. The user runs those when ready.)

- [ ] **Step 7: Commit**

```bash
git add deploy/sync.sh deploy/dev_sync.sh deploy/sync_nexp.sh deploy/dev_sync_nexp.sh
git commit -m "Update deploy scripts for new layout"
```

---

## Task 8: README and CLAUDE.md updates

**Files:**
- Create: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Write a lean `README.md`**

Create `README.md` (human-facing; cross-references CLAUDE.md instead of duplicating detail):
```markdown
# template_tools

Tools and dashboards for visualizing Rubin Observatory Alert Production
template coverage on the sky. Two independent dashboards, each backed by a
Python data generator and an [Aladin Lite v3](https://aladin.cds.unistra.fr/AladinLite/doc/)
HTML viewer:

- **Deployed template coverage** (`web/template_coverage.html`) — which
  tracts/patches have `template_coadd` datasets deployed in the Butler.
- **N-exposure coverage** (`web/nexp_coverage.html`) — input exposure depth
  (nexp) feeding template generation, before templates are built.

## Layout

- `scripts/` — data generators and shared `common.py`.
- `web/` — the two dashboards (HTML). Generators write their JSON here
  (gitignored); the dashboards `fetch()` it by bare filename.
- `deploy/` — production + dev rsync scripts (one pair per dashboard).
- `config/` — the external decasu config that produces the `.hsp` nexp inputs.
- `output/` — generated FITS/PNG/CSV/logs (gitignored).
- `tests/` — unit tests for the pure helpers in `common.py`.

## Regenerate data

Requires the LSST Science Pipelines environment (Butler access).

```bash
python scripts/query_embargo_templates.py          # deployed-template JSON + maps
python scripts/generate_nexp_dashboard_data.py     # -> web/nexp_dashboard_data.json
python scripts/healpix_to_tracts.py                # -> output/tract_nexp_fractions.csv
```

## Preview locally

```bash
cd web && python -m http.server
# then open template_coverage.html or nexp_coverage.html
```

## Deploy

```bash
./deploy/sync.sh        ./deploy/dev_sync.sh         # deployed-template dashboard
./deploy/sync_nexp.sh   ./deploy/dev_sync_nexp.sh    # nexp dashboard
```

## Tests / lint

```bash
pytest tests/
ruff check scripts/ tests/
```

See `CLAUDE.md` for architecture details, the decasu input pipeline, and
design notes.
```

- [ ] **Step 2: Update `CLAUDE.md` file references in the Project Overview**

In `CLAUDE.md`, prefix the source filenames with their new directories. Update these references in the "Project Overview" section:
- `template_coverage.html` → `web/template_coverage.html`
- `nexp_coverage.html` → `web/nexp_coverage.html`
- `query_embargo_templates.py` → `scripts/query_embargo_templates.py`
- `generate_nexp_dashboard_data.py` → `scripts/generate_nexp_dashboard_data.py`
- `healpix_to_tracts.py` → `scripts/healpix_to_tracts.py`
- `decasu_incremental_templates_config.yaml` → `config/decasu_incremental_templates_config.yaml`
- the `.hsp` inputs description: note they live in `output_incremental_test/` at the repo root (unchanged).

Also add a one-line note that the three generators now share `scripts/common.py` (skymap loading, pixel→tract assignment, tract corners, per-tract fractions).

- [ ] **Step 3: Update the "Running" section commands in `CLAUDE.md`**

Replace the run commands so they invoke the scripts under `scripts/` and reflect the new output locations:
```bash
python scripts/query_embargo_templates.py            # default NSIDE 64
python scripts/query_embargo_templates.py --nside 128
python scripts/generate_nexp_dashboard_data.py        # -> web/nexp_dashboard_data.json
python scripts/healpix_to_tracts.py                   # -> output/tract_nexp_fractions.csv
```
Note that `query_embargo_templates.py` now writes `deployed_template_data.json` into `web/` and the FITS/PNG maps into `output/`.

- [ ] **Step 4: Update the "Deploy" section in `CLAUDE.md`**

Point the four scripts at their new `deploy/` location:
```bash
./deploy/sync.sh             # -> ~/public_html/template_coverage/ (production)
./deploy/dev_sync.sh         # -> ~/public_html/dev_template_coverage/ (dev/testing)
./deploy/sync_nexp.sh        # -> ~/public_html/nexp_coverage/ (production)
./deploy/dev_sync_nexp.sh    # -> ~/public_html/dev_nexp_coverage/ (dev/testing)
```
Keep the existing note that the nexp sync also ships `deployed_template_data.json` and that `nexp_dashboard_data.json` is ~20 MB. Add that all four scripts `cd` to the repo root and source HTML + JSON from `web/`.

- [ ] **Step 5: Update the "Local preview" section in `CLAUDE.md`**

Replace with:
```bash
cd web && python -m http.server
# then open template_coverage.html or nexp_coverage.html
```

- [ ] **Step 6: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "Add README and update CLAUDE.md for new layout"
```

---

## Task 9: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Lint everything**

Run:
```bash
ruff check scripts/ tests/
```
Expected: passes (ignore the harmless `W503`/`E133` "no effect" warning if printed).

- [ ] **Step 2: Run the test suite**

Run:
```bash
pytest tests/ -v
```
Expected: all tests pass.

- [ ] **Step 3: Confirm the repo root is tidy**

Run:
```bash
ls -1
```
Expected top-level entries: `CLAUDE.md`, `README.md`, `config`, `deploy`, `docs`, `output`, `output_incremental_test`, `ruff.toml`, `scripts`, `tests`, `web` (plus `.git`, `.gitignore`). No loose `.py`, `.html`, `.sh`, `.fits`, `.png`, `.csv`, `.json`, or `.txt` files in the root.

- [ ] **Step 4: Confirm git status is clean of generated artifacts**

Run:
```bash
git status
```
Expected: no untracked generated artifacts (FITS/PNG/CSV/JSON/log) and no untracked `output_incremental_test/` — all covered by `.gitignore`. Working tree clean after the Task 8 commit.

- [ ] **Step 5: Verify imports resolve when run from the repo root (no Butler needed for the import check)**

Run:
```bash
python -c "import sys; sys.path.insert(0, 'scripts'); import common; print(common.BANDS)"
```
Expected: prints `['u', 'g', 'r', 'i', 'z', 'y']`.

- [ ] **Step 6: (If Butler access available) confirm end-to-end output equivalence**

Regenerate each dataset and diff against pre-refactor copies if available:
```bash
python scripts/query_embargo_templates.py --nside 64
python scripts/generate_nexp_dashboard_data.py
python scripts/healpix_to_tracts.py
```
Expected: `web/deployed_template_data.json`, `web/nexp_dashboard_data.json`, `output/tract_nexp_fractions.csv`, and `output/template_coverage_healpix_*.{fits,png}` are produced; JSON/CSV content matches the originals. Then preview locally (`cd web && python -m http.server`) and confirm both dashboards render.

---

## Self-review notes

- **Spec coverage:** layout move (Task 2), `common.py` + dedup of all four shared pieces (Task 3, consumed in Tasks 4-6), Decision A — `common.py` in `scripts/`, no `sys.path` hacks (Task 3; `conftest.py` for tests), Decision B — JSON in `web/`, gitignored (Tasks 4-5, `.gitignore` Task 1), preserved intentional differences (THRESHOLDS per-script in Tasks 5-6; Butler repos via `load_skymap` arg in Tasks 4-6), hygiene (`.gitignore`/`ruff.toml` Task 1, README Task 8, tests Task 3), deploy-script root-relative paths (Task 7), CLAUDE.md updates (Task 8), success criteria (Task 9). All covered.
- **Byte-equivalence:** the `ndigits=None` path for `query_embargo` (unrounded tract corners) and `ndigits=3` for nexp, plus unrounded `compute_tract_fractions` with caller-side rounding, are the load-bearing details — called out at the top and in each refactor task.
- **Type consistency:** `common.tract_corners` returns `[[ra, dec], ...]`; `common.compute_tract_fractions` returns `[{"tract", "n_pixels", "fractions"}]`. Callers in Tasks 4-6 reformat consistently with those exact keys.

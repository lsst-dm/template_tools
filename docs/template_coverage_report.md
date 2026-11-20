# Template coverage reports

`scripts/template_curation/template_coverage_report.py` summarizes the templates in one or more
collections, tract by tract. It writes `template_coverage_report_<band>.csv`
for each band with templates in any of the collections. Each file has one row
per tract with templates in that band.

Only `template_coadd` and `template_coadd_decam` datasets with the skymap given
by the required `--skymap` option are counted. Other dataset types and
skymaps are ignored, and the script logs which other skymaps it found. Run
the script once per skymap to report on more than one.

## Usage

Set up the LSST Science Pipelines environment, then give the repo and the
collections to summarize:

```bash
python scripts/template_curation/template_coverage_report.py main LSSTCam/templates_prep DECam/templates_prep --skymap lsst_cells_v2
```

The reports are written to the current directory, or to `--output-dir`:

```bash
python scripts/template_curation/template_coverage_report.py main LSSTCam/templates_prep DECam/templates_prep --skymap lsst_cells_v2 --output-dir output
```

The skymap definition is read from the `skymaps` collection; use
`--skymap-collection` to read it from another.

## Columns

Multiple values in one column are separated by semicolons.

| Column | Meaning |
|---|---|
| `tract` | Tract ID. |
| `collections` | The given collections with templates in any patch of the tract, in the order given. |
| `single_collection` | `True` if exactly one collection has templates in the tract. |
| `n_patches` | Patches with templates from any collection. |
| `n_patches_total` | Patches in the tract. |
| `percent_patches` | `n_patches` as a percentage of `n_patches_total`. |
| `n_patches_<collection>` | Patches with templates from that collection, one column per given collection. |
| `n_patches_multiple` | Patches with templates from more than one collection. |
| `members` | The collections that hold the templates. For a chain, these are its members, e.g. `DECam/templates/DM-57022/release_01`. |
| `bands` | All bands with templates in the tract, from any collection, e.g. `gri`. |
| `patches` | IDs of the patches with templates, as ranges, e.g. `0-3;7;9-10`. |
| `ra`, `dec` | Tract center, in degrees. |
| `first_ingest_utc`, `last_ingest_utc` | Earliest and latest ingest time of the tract's templates, in UTC. |

## Checking DECam coverage

When summarizing `LSSTCam/templates_prep` and `DECam/templates_prep` together,
`single_collection` should be `True` for every tract. DECam templates are only
staged for tract/bands with no LSSTCam coverage, so a tract with both
collections has new LSSTCam templates that `prune_decam_templates.py` has not
yet removed from DECam (see [curate_decam_templates.md](curate_decam_templates.md)).

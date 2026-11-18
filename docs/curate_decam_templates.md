# Curating DECam templates

DECam templates fill gaps in LSSTCam template coverage for Prompt Processing.
They are staged in the `DECam/templates_prep` chained collection in the `main`
repo by two scripts:

- `scripts/template_curation/curate_decam_templates.py` adds a new release of DECam templates,
  skipping what is already covered.
- `scripts/template_curation/prune_decam_templates.py` drops DECam templates from the chain once
  new LSSTCam templates cover them.

## Collections

Each release of DECam templates is ingested to a RUN collection named
`DECam/templates/<ticket>/<release>/run`, e.g.
`DECam/templates/DM-57022/release_01/run`, with dataset type
`template_coadd_decam`.

The curation script tags the selected templates into a TAGGED collection with
the same name minus `/run`, e.g. `DECam/templates/DM-57022/release_01`, and
prepends it to `DECam/templates_prep`. The templates are tagged, not copied.

Pruning replaces a release with a new TAGGED collection under the next unused
release number for its ticket, e.g. `DECam/templates/DM-57022/release_02`. That
collection tags datasets from the earlier RUN, so there is no
`release_02/run` to go with it. Pruning and new deliveries share release
numbers: give a new delivery a number that no collection for its ticket uses
yet. To list the numbers in use:

```bash
butler query-collections main "DECam/templates/DM-57022/*"
```

## Selection

Templates are selected by tract and band. A tract/band is skipped entirely if
any patch of it already has a template in either of:

- `LSSTCam/templates_prep` (dataset type `template_coadd`), or
- `DECam/templates_prep`, from an earlier DECam release.

A tract/band is therefore in at most one release in `DECam/templates_prep`, so
the order of the chain does not change which template is found.

Both scripts require `--skymap` and only work on templates with that skymap.
Templates with other skymaps are ignored, and the script logs which other
skymaps it found. Each release must hold templates on a single skymap: to
stage templates on two skymaps, use a separate release for each.

## Usage

Set up the LSST Science Pipelines environment, then run the script from the
repository root.

First check the selection with `--dry-run`. It logs whether each tract/band is
kept or skipped and writes nothing to the repo:

```bash
python scripts/template_curation/curate_decam_templates.py main DECam/templates/DM-57022/release_01/run --skymap lsst_cells_v2 --dry-run
```

```
INFO:curate_decam_templates:Found 16 template_coadd_decam datasets in DECam/templates/DM-57022/release_01/run.
INFO:curate_decam_templates:Tract 0 band g (6 patches): skipped, already covered in LSSTCam/templates_prep.
INFO:curate_decam_templates:Tract 0 band r (6 patches): kept.
INFO:curate_decam_templates:Tract 1 band g (4 patches): kept.
INFO:curate_decam_templates:Selected 10 of 16 datasets, 2 of 3 tract/bands.
INFO:curate_decam_templates:Dry run: would tag 10 datasets into DECam/templates/DM-57022/release_01.
```

Then stage the release:

```bash
python scripts/template_curation/curate_decam_templates.py main DECam/templates/DM-57022/release_01/run --skymap lsst_cells_v2
```

### The first release

The script does not create `DECam/templates_prep`. If the chain does not exist
yet, the script still creates the TAGGED collection, then prints the command
that creates the chain from it:

```bash
butler collection-chain main DECam/templates_prep DECam/templates/DM-57022/release_01
```

Later releases are prepended to the chain by the script.

### Options

| Option | Default | Meaning |
|---|---|---|
| `--skymap` | required | Skymap of the templates to work on, e.g. `lsst_cells_v2`. |
| `--dataset-type` | `template_coadd_decam` | Dataset type of the new DECam templates. |
| `--chain` | `DECam/templates_prep` | Chain to prepend the new release to. |
| `--existing-collection` | `LSSTCam/templates_prep` | Collection of existing LSSTCam templates. |
| `--existing-dataset-type` | `template_coadd` | Dataset type of the existing LSSTCam templates. |
| `--dry-run` | off | Report the selection without writing. |

## When the script stops

The script exits with an error and writes nothing if:

- the input collection name does not have the form
  `DECam/templates/<ticket>/<release>/run`;
- the input collection does not exist, is not a RUN, or has no templates
  with the given skymap;
- the TAGGED collection for the release already exists.

The writes (creating the TAGGED collection, tagging the templates, and
prepending to the chain) happen in one transaction, so a failure part way
leaves nothing behind and the script can be run again.

### Replacing a release

Because earlier releases count as coverage, a second release of the same sky
area is skipped entirely. To replace a release, first remove its TAGGED
collection from the chain, then stage the replacement under an unused release
number:

```bash
butler collection-chain main DECam/templates_prep --mode remove DECam/templates/DM-57022/release_01
python scripts/template_curation/curate_decam_templates.py main DECam/templates/DM-57022/release_02/run --skymap lsst_cells_v2
```

## Pruning after new LSSTCam templates

When new LSSTCam templates are added to `LSSTCam/templates_prep`, run
`prune_decam_templates.py` to drop the DECam templates they cover. For each
release in `DECam/templates_prep`, every tract/band with at least one patch in
`LSSTCam/templates_prep` is dropped, the same rule the curation script uses.
A release that loses templates is replaced in the chain, at the same position,
by a new TAGGED collection with the next unused release number. A release that
loses all of its templates is removed from the chain. The old TAGGED
collections are unchanged, so earlier selections stay reproducible.

```bash
python scripts/template_curation/prune_decam_templates.py main --skymap lsst_cells_v2 --dry-run
```

```
INFO:prune_decam_templates:DECam/templates/DM-57100/release_01: dropping tract 1 band i (4 patches).
INFO:prune_decam_templates:DECam/templates/DM-57100/release_01: all tract/bands covered; removed from DECam/templates_prep.
INFO:prune_decam_templates:DECam/templates/DM-57022/release_01: dropping tract 1 band g (4 patches).
INFO:prune_decam_templates:DECam/templates/DM-57022/release_01: replaced by DECam/templates/DM-57022/release_02 with 6 of 10 datasets.
INFO:prune_decam_templates:Dry run: would redefine DECam/templates_prep as ['DECam/templates/DM-57022/release_02'].
```

```bash
python scripts/template_curation/prune_decam_templates.py main --skymap lsst_cells_v2
```

Only releases on the given skymap are pruned; releases on other skymaps are
left unchanged.

The script takes the same `--dataset-type`, `--chain`,
`--existing-collection`, and `--existing-dataset-type` options as the curation
script. It stops without writing if a member of the chain is not a TAGGED
collection named `DECam/templates/<ticket>/release_<number>`, or holds
templates on more than one skymap. Its writes happen in one transaction. Running it again with no new LSSTCam coverage changes
nothing.

## Deployment

Templates in `DECam/templates_prep` in `main` are copied to `DECam/templates` in
`embargo`, where Prompt Processing and Daytime AP use them. Neither script does
that copy, so redo it after curating or pruning.

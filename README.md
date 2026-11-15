# template_tools

Tools and dashboards for visualizing Rubin Observatory Alert Production
template coverage on the sky. 

Note that major portions of this repository are AI-coded.
It contains hard-coded paths, and is not intended to be portable.

There are two independent dashboards, each backed by a
Python data generator and an [Aladin Lite](https://aladin.cds.unistra.fr/AladinLite/doc/)
HTML viewer:

- **Deployed template coverage** (`web/template_coverage.html`) — which
  tracts/patches have `template_coadd` datasets deployed in the Butler for alert production.
- **N-exposure coverage** (`web/nexp_coverage.html`) — Displays observation coverage from consdb using [decasu](https://github.com/erykoff/decasu) 
to determine input exposure depth (nexp) and identify candidate tracts to build templates in.

## Regenerate data

Requires the LSST Science Pipelines environment and USDF Butler and consdb access.  

### Deployed Template Coverage

```bash
python scripts/query_embargo_templates.py          # deployed-template JSON + maps
./deploy/dev_sync.sh         			   # dev version
./deploy/sync.sh        			   # public version
```

### Candidate Template Input Maps

First, generate the bad visits list:

```bash
python scripts/write_bad_visits.py -o config/bad_visits.ecsv
```

Run decasu first:

```bash
export OUTDIR=output_incremental_test
mkdir $OUTDIR
decasu_hpix_mapper.py -c config/decasu_incremental_templates_config.yaml -x config/bad_visits.ecsv -n 8 -i postgresql://usdf@usdf-summitdb-logical-replica-svc.sdf.slac.stanford.edu/exposurelog -o $OUTDIR -m >& $OUTDIR/log_decasu_incremental.txt
```

```bash
python scripts/generate_nexp_dashboard_data.py     # -> web/nexp_dashboard_data.json
./deploy/sync_nexp.sh   			   # nexp dashboard
```

If you want a csv file for analysis:

```bash
python scripts/healpix_to_tracts.py                # -> output/tract_nexp_fractions.csv
```


## Aladin Lite source (CDS vs. mirror)

Both dashboards load the Aladin Lite library and the DSS2 background survey
through `web/aladin_config.js`. Set `ALADIN_SOURCE` there to:

- `'cds'` — the primary CDS host (`aladin.cds.unistra.fr`) and the
  `P/DSS2/color` HiPS ID.
- `'mirror'` — the jsDelivr npm build of Aladin Lite plus the DSS2 color HiPS
  from ESA's mirror; use this when the CDS host is unreachable.

Redeploy with the sync scripts after changing it. For a quick check without
redeploying, append `?aladin=cds` or `?aladin=mirror` to a dashboard URL.

## Layout

- `scripts/` — data generators and shared `common.py`.
- `web/` — the two dashboards (HTML) plus `aladin_config.js`. Generators
  write their JSON here (gitignored); the dashboards `fetch()` it by bare
  filename.
- `deploy/` — production + dev rsync scripts (one pair per dashboard).
- `config/` — the external decasu config that produces the `.hsp` nexp inputs.
- `output/` — generated FITS/PNG/CSV/logs (gitignored).
- `tests/` — unit tests for the pure helpers in `common.py`.

## Tests / lint

```bash
pytest tests/
ruff check scripts/ tests/
```

See `CLAUDE.md` for architecture details, the [decasu](https://github.com/erykoff/decasu) input pipeline, and
design notes.

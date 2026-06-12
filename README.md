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

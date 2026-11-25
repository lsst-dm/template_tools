#!/usr/bin/env python
"""List good visits overlapping a set of tracts.

Reads a tract-list CSV (as written by ``select_visible_tracts.py``), finds the
visits in the ``main`` Butler that overlap those tracts in the requested band,
applies the decasu consdb quality selection, removes known bad visits, and
writes the surviving visit IDs to a CSV with a single ``visit`` column.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from lsst.daf.butler import Butler

from common import get_endpoints, get_bad_visit_lists

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"
DECASU_CONFIG = REPO_ROOT / "config" / "decasu_incremental_templates_config.yaml"

def get_visits_for_tracts(tracts, band, endpoints):

    butler = Butler("main")
    with butler.query() as query:
        data_ids = list(query.data_ids(["visit", "tract"]).where(
            "tract IN (:tracts)",
            band=band,
            instrument="LSSTCam", skymap="lsst_cells_v2",
            bind={"tracts":tracts}))

    # data_ids has one row per (visit, tract) pair, so deduplicate
    butler_visits = sorted({data_id['visit'] for data_id in data_ids})
    print(f'{len(butler_visits)} visits in the Butler in band {band} for {len(tracts)} tracts')

    # get consdb values for these visits, filtered by our selection criteria
    consdb_visits = select_from_consdb(butler_visits, endpoints)
    print(f'{len(consdb_visits)} pass consdb cuts')

    filtered_visits = np.intersect1d(butler_visits, consdb_visits)
    if len(filtered_visits) == 0:
        return []

    # remove anything on the bad visit list
    min_visit_id = min(filtered_visits)
    day_obs_min = visit_id_to_dayobs(min_visit_id)
    max_visit_id = max(filtered_visits)
    day_obs_max = visit_id_to_dayobs(max_visit_id)

    bad_visit_ids = get_bad_visit_lists(endpoints, day_obs_min, day_obs_max)

    good_visit_ids = np.setdiff1d(filtered_visits, bad_visit_ids)

    print(f'{len(good_visit_ids)} visits after excluding bad visits')

    # TODO: check for undithered inputs

    return [int(v) for v in good_visit_ids]

def select_from_consdb(visits, endpoints):

    decasu_where = get_consdb_where()

    visit_list = f"{visits}".replace("[","(").replace("]",")")

    query =  f"""select DISTINCT(v.visit_id) from cdb_lsstcam.visit1 as v
                 left join cdb_lsstcam.ccdvisit1 as cv
                    on cv.visit_id = v.visit_id
                 left join cdb_lsstcam.ccdvisit1_quicklook as cvq
                    on cvq.ccdvisit_id = cv.ccdvisit_id
                WHERE {decasu_where} and v.visit_id in {visit_list}
                """
    return endpoints['consdb_tap'].query(query)['visit_id'].to_list()

def get_consdb_where():
    """Use the same selection as in our decasu plots.
    """

    with open(DECASU_CONFIG) as f:
        data = yaml.safe_load(f)

    return data["lsst_db_additional_selection"]

def visit_id_to_dayobs(visit_id):

    datestr = str(visit_id)[:8]
    return f'{datestr[:4]}-{datestr[4:6]}-{datestr[6:8]}'



def read_tract_list(path, band=None):
    """Return ``(tracts, band)`` from a tract-list CSV.

    The CSV must have a ``tract`` column. If ``band`` is not given it is taken
    from the CSV's ``band`` column, which must then hold a single value.
    """
    df = pd.read_csv(path)
    if "tract" not in df.columns:
        raise ValueError(f"{path} has no 'tract' column")
    tracts = sorted({int(t) for t in df["tract"]})
    if band is None:
        if "band" not in df.columns:
            raise ValueError(f"{path} has no 'band' column; pass --band")
        bands = sorted(set(df["band"]))
        if len(bands) != 1:
            raise ValueError(f"{path} has multiple bands {bands}; pass --band")
        band = bands[0]
    return tracts, band


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "tracts_csv", type=Path, help="CSV with a 'tract' column (from select_visible_tracts.py)"
    )
    parser.add_argument(
        "--band",
        default=None,
        help="Band to query (default: the single value in the CSV's 'band' column)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output CSV of visit IDs (default: output/visits_<band>_<input stem>.csv)",
    )
    args = parser.parse_args()

    tracts, band = read_tract_list(args.tracts_csv, args.band)
    print(f"{len(tracts)} tracts in band {band} from {args.tracts_csv}")
    if args.output is None:
        args.output = OUTPUT_DIR / f"visits_{band}_{args.tracts_csv.stem}.csv"

    endpoints = get_endpoints()
    visits = get_visits_for_tracts(tracts, band, endpoints)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"visit": visits}).to_csv(args.output, index=False)
    print(f"Wrote {args.output} ({len(visits)} visits)")


if __name__ == "__main__":
    main()


import os
import numpy as np
from lsst.daf.butler import Butler
from rubin_nights import connections
from rubin_nights.augment_visits import fetch_excluded_visits
import rubin_nights.dayobs_utils as rn_dayobs

import yaml

def get_visits_for_tracts(tracts, band, endpoints):

    butler = Butler("main")
    with butler.query() as query:
        data_ids = list(query.data_ids(["visit", "tract"]).where(
            "tract IN (:tracts)",
            band=band,
            instrument="LSSTCam", skymap="lsst_cells_v2",
            bind={"tracts":tracts}))

    butler_visits = [data_id['visit'] for data_id in data_ids]
    print(f'{len(butler_visits)} in the Butler in band {band}, tracts {tracts}')

    # get consdb values for these visits, filtered by our selection criteria
    consdb_visits = select_from_consdb(butler_visits, endpoints) 
    print(f'{len(consdb_visits)} pass consdb cuts')

    filtered_visits = np.setdiff1d(butler_visits, consdb_visits)


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

    with open("../config/decasu_incremental_templates_config.yaml") as f:
        data = yaml.safe_load(f)

    return data["lsst_db_additional_selection"]

def visit_id_to_dayobs(visit_id):

    datestr = str(visit_id)[:8]
    return f'{datestr[:4]}-{datestr[4:6]}-{datestr[6:8]}'


def get_bad_visit_lists(endpoints, day_obs_min, day_obs_max):
    # https://rubin-obs.slack.com/archives/C07QKKBUME3/p1780095120669989?thread_ts=1779774837.514619&cid=C07QKKBUME3

    # Pull lsst-dm excluded visit list to flag bad visits
    bad_visit_ids = fetch_excluded_visits("lsstcam")
    # Also pull bad visit lists from exposure log
    all_exp_log_bad_visit_ids = []
    ee = endpoints['exposure_log'].query_log(rn_dayobs.day_obs_to_time(day_obs_min), rn_dayobs.day_obs_to_time(day_obs_max))
    if len(ee) > 0:
        def make_visit_id(x):
            return f"{x.day_obs:d}{x.seq_num:05d}"
        exp_log_bad_visit_ids = ee.query("exposure_flag == 'junk'").apply(make_visit_id, axis=1).values
        if len(exp_log_bad_visit_ids) > 0:
            all_exp_log_bad_visit_ids.extend(exp_log_bad_visit_ids)

    bad_visit_ids.extend(all_exp_log_bad_visit_ids)

    return set(bad_visit_ids)

def get_endpoints():
    # Where is the notebook running? (RSPs are 'special')
    current_location = os.getenv("EXTERNAL_INSTANCE_URL", "")

    # RUBIN_SIM_DATA_DIR at usdf
    if 'usdf' in current_location:
        os.environ["RUBIN_SIM_DATA_DIR"] = "/sdf/data/rubin/shared/rubin_sim_data"

    # TOKEN CONFIGURATION
    if current_location != "":
        # You are on an rsp.
        # You should use the default RSP values, whether summit/base/USDF.
        tokenfile = None
        site = None
    # If you are outside of an RSP? - just use USDF and your own USDF-RSP token
    # See https://rsp.lsst.io/guides/auth/creating-user-tokens.html
    else:
        # Substitute the location of your own tokenfile
        tokenfile = os.getenv("ACCESS_TOKEN_FILE", "")
        site = os.getenv("DATA_SITE", "")
        if tokenfile == "":
            # A very reasonable backup.
            tokenfile = os.path.join(os.path.expanduser("~"), ".lsst/usdf_rsp")
            site = 'usdf'

    return connections.get_clients(tokenfile, site)


if __name__ == "__main__":
    pass

    endpoints = get_endpoints()
    i_visits = get_visits_for_tracts([1448, 1449, 1450, 1321, 1322, 1323],"i", endpoints)
    z_visits = get_visits_for_tracts([1448, 1449, 1450, 1321, 1322, 1323],"z", endpoints)


    print(i_visits)
    print(z_visits)


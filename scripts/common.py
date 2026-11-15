"""Shared Butler / HEALPix / tract helpers for the template-tools generators."""

import warnings
import os

import healpy as hp
import numpy as np

import lsst.daf.butler as dafButler
from lsst.geom import SpherePoint

from rubin_nights import connections
from rubin_nights.augment_visits import fetch_excluded_visits
import rubin_nights.dayobs_utils as rn_dayobs


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
    bad_visit_ids = [int(idi) for idi in bad_visit_ids]

    return list(set(bad_visit_ids))


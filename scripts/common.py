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

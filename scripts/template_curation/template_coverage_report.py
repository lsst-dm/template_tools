#!/usr/bin/env python
# This file is part of template_tools.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.


"""Summarize template coverage by tract and band.

Writes ``template_coverage_report_<band>.csv`` for each band with templates in
any of the given collections. Each file has one row per tract with templates
in that band. Only ``template_coadd`` and ``template_coadd_decam`` datasets on
the skymap given by ``--skymap`` are counted.
"""

import argparse
import csv
import logging
import os
import sys
from collections import Counter, defaultdict, namedtuple
from functools import partial

from lsst.daf.butler import Butler

from curate_decam_templates import check_collection, log_other_skymaps


_log = logging.getLogger("template_coverage_report")

DATASET_TYPES = ("template_coadd", "template_coadd_decam")

_BAND_ORDER = "ugrizy"

_Template = namedtuple("_Template", ["tract", "band", "patch", "member", "ingest_date"])


def _make_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("repo", help="An existing data repository, e.g. 'main'.")
    parser.add_argument(
        "collections",
        nargs="+",
        help="The collections to summarize, e.g. LSSTCam/templates_prep DECam/templates_prep.",
    )
    parser.add_argument(
        "--skymap", required=True, help="The skymap of the templates to report on, e.g. lsst_cells_v2."
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="The directory to write the reports to (default: the current directory).",
    )
    parser.add_argument(
        "--skymap-collection",
        default="skymaps",
        help="The collection holding the skymap definition (default: %(default)s).",
    )
    return parser


def _band_key(band):
    """Sort key putting the standard bands in wavelength order."""
    return (_BAND_ORDER.index(band) if band in _BAND_ORDER else len(_BAND_ORDER), band)


def _format_ranges(numbers):
    """Format integers as a compact list of ranges.

    Parameters
    ----------
    numbers : iterable [`int`]
        The integers to format.

    Returns
    -------
    ranges : `str`
        Runs of consecutive integers separated by semicolons, e.g.
        ``0-3;7;9-10``.
    """
    ranges = []
    for number in sorted(numbers):
        if ranges and number == ranges[-1][1] + 1:
            ranges[-1][1] = number
        else:
            ranges.append([number, number])
    return ";".join(str(start) if start == end else f"{start}-{end}" for start, end in ranges)


def _query_templates(butler, collection, skymap):
    """Return the templates in a collection.

    Parameters
    ----------
    butler : `lsst.daf.butler.Butler`
        The butler to query.
    collection : `str`
        The collection to search. For a chain, the member collection holding
        each template is also reported.
    skymap : `str`
        The skymap of the templates to return.

    Returns
    -------
    templates : `list` [`_Template`]
        One entry per dataset of any type in `DATASET_TYPES`. The ingest date
        is an ISO-format UTC string.
    """
    present = butler.registry.getCollectionSummary(collection).dataset_types.names
    templates = []
    for dataset_type in DATASET_TYPES:
        if dataset_type not in present:
            continue
        with butler.query() as query:
            query = query.join_dataset_search(dataset_type, collections=[collection]).where(skymap=skymap)
            rows = query.general(
                ["skymap", "tract", "patch", "band"],
                dataset_fields={dataset_type: {"collection", "ingest_date"}},
                find_first=False,
            )
            for row in rows:
                templates.append(
                    _Template(
                        tract=row["tract"],
                        band=row["band"],
                        patch=row["patch"],
                        member=row[f"{dataset_type}.collection"],
                        ingest_date=row[f"{dataset_type}.ingest_date"].utc.isot[:19],
                    )
                )
    return templates


def _make_row(tract_info, collections, templates, bands):
    """Summarize the templates of one tract in one band.

    Parameters
    ----------
    tract_info : `lsst.skymap.TractInfo`
        The tract.
    collections : `list` [`str`]
        All collections being summarized, in the order given.
    templates : `dict` [`str`, `list` [`_Template`]]
        The templates in this tract and band, keyed by collection.
    bands : `set` [`str`]
        All bands with templates in this tract.

    Returns
    -------
    row : `dict`
        The report columns.
    """
    patch_sets = {collection: {t.patch for t in templates.get(collection, [])} for collection in collections}
    covering = [collection for collection in collections if patch_sets[collection]]
    patch_counts = Counter(patch for patches in patch_sets.values() for patch in patches)
    covering_templates = [t for collection in covering for t in templates[collection]]
    ingest_dates = [t.ingest_date for t in covering_templates]
    nx, ny = tract_info.getNumPatches()
    center = tract_info.getCtrCoord()

    row = {
        "tract": tract_info.getId(),
        "collections": ";".join(covering),
        "single_collection": len(covering) == 1,
        "n_patches": len(patch_counts),
        "n_patches_total": nx*ny,
        "percent_patches": round(100*len(patch_counts)/(nx*ny), 1),
    }
    for collection in collections:
        row[f"n_patches_{collection}"] = len(patch_sets[collection])
    row["n_patches_multiple"] = sum(1 for count in patch_counts.values() if count > 1)
    row["members"] = ";".join(sorted({t.member for t in covering_templates}))
    row["bands"] = "".join(sorted(bands, key=_band_key))
    row["patches"] = _format_ranges(patch_counts)
    row["ra"] = round(center.getRa().asDegrees(), 4)
    row["dec"] = round(center.getDec().asDegrees(), 4)
    row["first_ingest_utc"] = min(ingest_dates)
    row["last_ingest_utc"] = max(ingest_dates)
    return row


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    args = _make_parser().parse_args()
    collections = list(dict.fromkeys(args.collections))
    butler = Butler(args.repo)

    by_tract_band = defaultdict(partial(defaultdict, list))
    bands_by_tract = defaultdict(set)
    for collection in collections:
        check_collection(butler, collection)
        log_other_skymaps(butler, collection, DATASET_TYPES, args.skymap, _log)
        templates = _query_templates(butler, collection, args.skymap)
        _log.info("Found %d templates with skymap %s in %s.", len(templates), args.skymap, collection)
        for template in templates:
            by_tract_band[(template.tract, template.band)][collection].append(template)
            bands_by_tract[template.tract].add(template.band)

    if not by_tract_band:
        _log.warning(
            "No %s datasets with skymap %s found; no reports written.",
            " or ".join(DATASET_TYPES),
            args.skymap,
        )
        return
    skymap = butler.get("skyMap", skymap=args.skymap, collections=args.skymap_collection)

    os.makedirs(args.output_dir, exist_ok=True)
    for band in sorted({band for _, band in by_tract_band}, key=_band_key):
        tracts = sorted(tract for tract, tract_band in by_tract_band if tract_band == band)
        rows = [
            _make_row(skymap[tract], collections, by_tract_band[(tract, band)], bands_by_tract[tract])
            for tract in tracts
        ]
        path = os.path.join(args.output_dir, f"template_coverage_report_{band}.csv")
        with open(path, "w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        _log.info("Wrote %d tracts to %s.", len(rows), path)


if __name__ == "__main__":
    main()

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


"""Curate template_coadd datasets for LSSTCam.

This script applies quality cuts to template_coadd datasets, records curation
results, and associates accepted template_coadd and template_coadd_n_image
datasets with a TAGGED collection to be used for further manual vetting.
Association can also be resumed from a saved ECSV recovery file.
"""

import argparse
from collections import defaultdict
import logging
import os
import sys
import time

import numpy as np
from astropy.table import Table, vstack

from lsst.daf.butler import Butler, CollectionType


def _make_parser():
    """Construct the command-line argument parser.

    Returns
    -------
    parser : `argparse.ArgumentParser`
        Parser configured for curated template collection creation.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Curate LSSTCam template_coadd datasets or associate previously "
            "curated DatasetRefs."
        )
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    # -------------------------
    # Curate & Associate
    # -------------------------
    curate_parser = subparsers.add_parser(
        "curate",
        help="Curate template_coadd datasets and associate accepted datasets.",
    )

    curate_parser.add_argument(
        "repo",
        help="An existing data repository containing the input collections.",
    )
    curate_parser.add_argument(
        "skymap",
        help="The skymap used for this batch of templates.",
    )
    curate_parser.add_argument(
        "tag",
        help="A Jira ticket number for the new template collection name.",
    )
    curate_parser.add_argument(
        "release_id",
        help="The release ID and/or number (e.g. release_01) for the given tag.",
    )
    curate_parser.add_argument(
        "--collections",
        nargs="+",
        required=True,
        help=(
            "The input collections to search for template_coadd and "
            "template_coadd_depth_table datasets."
        ),
    )
    curate_parser.add_argument(
        "--where",
        default=None,
        help="A string expression to select datasets in the input collections.",
    )
    curate_parser.add_argument(
        "--records_path",
        default="",
        help="Directory in which to save curation records.",
    )
    curate_parser.add_argument(
        "--stat_records",
        help=(
            "Output table containing accepted/rejected template statistics. "
            "Default is {release_id}_stat_records.csv."
        ),
    )
    curate_parser.add_argument(
        "--min_filter",
        nargs="+",
        metavar="COLUMN=NUMBER",
        help=(
            "Minimum-value filters to apply, specified as COLUMN=VALUE. "
            "Multiple filters may be supplied. If omitted, no minimum "
            "filters are applied."
        ),
    )
    curate_parser.add_argument(
        "--max_filter",
        nargs="+",
        metavar="COLUMN=NUMBER",
        help=(
            "Maximum-value filters to apply, specified as COLUMN=VALUE. "
            "Multiple filters may be supplied. If omitted, no maximum "
            "filters are applied."
        ),
    )

    # -------------------------
    # Associate
    # -------------------------
    associate_parser = subparsers.add_parser(
        "associate",
        help="Associate DatasetRefs from a saved ECSV curation record.",
    )

    associate_parser.add_argument(
        "repo",
        help="The Butler repository containing the datasets.",
    )
    associate_parser.add_argument(
        "tag",
        help="Jira ticket number for the template collection name.",
    )
    associate_parser.add_argument(
        "release_id",
        help="The release ID and/or number (e.g. release_01) for the given tag.",
    )
    associate_parser.add_argument(
        "--from-file",
        required=True,
        metavar="FILE",
        help="ECSV file containing DatasetRefs to associate.",
    )

    return parser


def parse_filters(filters):
    """Parse command-line curation filter specifications.

    Parameters
    ----------
    filters : `list` of `str` or `None`
        Filter specifications in ``COLUMN=VALUE`` form. Values are converted
        to floating-point numbers. If `None`, no filters are specified.

    Returns
    -------
    parsed_filters : `dict` [`str`, `float`]
        Mapping of coadd depth table column names to their numeric cutoff
        values. An empty dictionary is returned if ``filters`` is `None`.
    """
    if filters is None:
        return {}

    return {
        key: float(value)
        for key, value in (item.split("=", 1) for item in filters)
    }


def select_ref(refs, tract, patch, band, dtype="template_coadd"):
    """Select a DatasetRef for a tract, patch, and band.

    If multiple references are available, the reference whose run name sorts
    last is selected. If no references are available, a warning is logged and
    `None` is returned.

    Parameters
    ----------
    refs : iterable of `lsst.daf.butler.DatasetRef`
        Dataset references matching the requested tract, patch, and band.
    tract : `int`
        Tract ID of the requested dataset.
    patch : `int`
        Patch ID of the requested dataset.
    band : `str`
        Band of the requested dataset.
    dtype : `str`, optional
        Dataset type name used in warning messages.

    Returns
    -------
    ref : `lsst.daf.butler.DatasetRef` or `None`
        Selected dataset reference, or `None` if no matching reference is
        available.
    """
    if not refs:
        logging.warning(f"No {dtype} found for tract {tract}, patch {patch}, band {band}. Skipping.")
        return None
    if len(refs) > 1:
        return sorted(refs, key=lambda ref: ref.run)[-1]
    return refs[0]


def index_refs(refs):
    """Index DatasetRefs by tract, patch, and band.

    Parameters
    ----------
    refs : iterable of `lsst.daf.butler.DatasetRef`
        Dataset references to index. Each reference must have ``tract``,
        ``patch``, and ``band`` in its data ID.

    Returns
    -------
    index : `collections.defaultdict`
        Mapping from ``(tract, patch, band)`` tuples to lists of DatasetRefs
        with that data ID.
    """
    index = defaultdict(list)
    for ref in refs:
        data_id = (
            ref.dataId["tract"],
            ref.dataId["patch"],
            ref.dataId["band"],
        )
        index[data_id].append(ref)
    return index


def make_threshold_cuts(
    read_butler,
    template_coadd_refs,
    n_image_refs,
    coadd_depth_table_refs,
    min_filters,
    max_filters,
):
    """Select template datasets that satisfy the curation thresholds.

    Parameters
    ----------
    read_butler : Butler
        Butler instance used to fetch the coadd depth table.
    template_coadd_refs : list of DatasetRef
        Candidate template_coadd references to filter.
    n_image_refs : list of DatasetRef
        Candidate template_coadd_n_image references to filter.
    coadd_depth_table_refs : `list` of `lsst.daf.butler.DatasetRef`
        References to the template_coadd_depth_table datasets containing
        the curation metrics.
    min_filters : dict[str, int | float]
        Mapping of column names to minimum cutoff values. A coadd is retained
        only if it meets all thresholds, i.e., for each (column, cutoff),
        ``table[column] >= cutoff``.
    max_filters : dict[str, int | float]
        Mapping of column names to maximum cutoff values. A coadd is retained
        only if it meets all thresholds, i.e., for each (column, cutoff),
        ``table[column] <= cutoff``.

    Returns
    -------
    accepted_coadd_refs : list of DatasetRef
        Template dataset refs that passed the threshold.
    rejected_coadd_refs : list of DatasetRef
        Template dataset refs that did not pass the threshold.
    accepted_n_image_refs : list of DatasetRef
        Corresponding template_coadd_n_image dataset refs for the accepted coadds.

    Raises
    ------
    RuntimeError
        Raised if a requested filter column is not present in a
        template_coadd_depth_table.
    """
    accepted_coadd_refs = []
    accepted_n_image_refs = []
    rejected_coadd_refs = []

    # Index refs.
    coadd_index = index_refs(template_coadd_refs)
    n_image_index = index_refs(n_image_refs)

    for coadd_depth_table_ref in coadd_depth_table_refs:
        tract = coadd_depth_table_ref.dataId["tract"]
        coadd_depth_table = read_butler.get(coadd_depth_table_ref)

        # Verify that this depth table contains every metric requested.
        required_columns = set(min_filters) | set(max_filters)
        missing_columns = required_columns - set(coadd_depth_table.colnames)

        if missing_columns:
            raise RuntimeError(
                f"template_coadd_depth_table for tract {tract} "
                f"from run {coadd_depth_table_ref.run} is missing "
                f"requested filter column(s): {sorted(missing_columns)}. "
                f"Available columns: {coadd_depth_table.colnames}"
            )

        mask = np.ones(len(coadd_depth_table), dtype=bool)

        for filter_by, cutoff in min_filters.items():
            mask &= coadd_depth_table[filter_by] >= cutoff

        for filter_by, cutoff in max_filters.items():
            mask &= coadd_depth_table[filter_by] <= cutoff

        # Handle accepted patches/bands.
        accepted_coadds = coadd_depth_table[mask]
        for patch, band in accepted_coadds["patch", "band"]:
            data_id = (tract, patch, band)

            coadd_ref = select_ref(coadd_index.get(data_id, []), tract, patch, band)
            n_image_ref = select_ref(n_image_index.get(data_id, []),
                                     tract, patch, band,
                                     dtype="template_coadd_n_image")

            # Keep template_coadd and template_coadd_n_image paired.
            if coadd_ref is None or n_image_ref is None:
                continue

            accepted_coadd_refs.append(coadd_ref)
            accepted_n_image_refs.append(n_image_ref)

        # Handle rejected patches/bands.
        rejected_coadds = coadd_depth_table[~mask]
        for patch, band in rejected_coadds["patch", "band"]:
            data_id = (tract, patch, band)

            coadd_ref = select_ref(coadd_index.get(data_id, []), tract, patch, band)

            if coadd_ref is None:
                continue

            rejected_coadd_refs.append(coadd_ref)

    return accepted_coadd_refs, rejected_coadd_refs, accepted_n_image_refs


def run_stats(accepted_coadd_refs, rejected_coadd_refs, tracts, stats_records_file):
    """
    Compute per-tract and per-band accepted/rejected statistics and save to CSV.

    Parameters
    ----------
    accepted_coadd_refs : list of DatasetRef
        Template references that passed curation.
    rejected_coadd_refs : list of DatasetRef
        Template references that failed curation.
    tracts : iterable of int
        List of tract IDs to include in the stats.
    stats_records_file : str
        Path to save the resulting CSV file.
    """

    bands = ["u", "g", "r", "i", "z", "y"]

    # Build accepted table.
    accepted = Table(
        rows=[(int(ref.dataId["tract"]), int(ref.dataId["patch"]), str(ref.dataId["band"]), "accepted")
              for ref in accepted_coadd_refs],
        names=("tract", "patch", "band", "status"),
        dtype=(int, int, str, str),
    )

    # Build rejected table.
    rejected = Table(
        rows=[(int(ref.dataId["tract"]), int(ref.dataId["patch"]), str(ref.dataId["band"]), "rejected")
            for ref in rejected_coadd_refs],
        names=("tract", "patch", "band", "status"),
        dtype=(int, int, str, str),
    )

    # Combine tables.
    all_refs = vstack([accepted, rejected])

    # Group by tract and band.
    grouped = all_refs.group_by(["tract", "band"])

    # Prepare output table.
    stat_table_data = {
        "tract": [],
        "percent_full_tract_band_coverage": [],
    }
    for band in bands:
        stat_table_data[f"{band}_num_accepted"] = []
        stat_table_data[f"{band}_num_rejected"] = []
        stat_table_data[f"{band}_percent_accepted"] = []

    for tract in tracts:
        stat_table_data["tract"].append(tract)
        total = 0

        for band in bands:
            mask = (grouped["tract"] == tract) & (grouped["band"] == band)
            subset = grouped[mask]

            n_total = len(subset)
            n_accepted = (
                (subset["status"] == "accepted").sum() if n_total > 0
                else 0
            )
            n_rejected = (
                (subset["status"] == "rejected").sum() if n_total > 0
                else 0
            )
            percent = (
                n_accepted / n_total * 100 if n_total > 0
                else float("nan")
            )

            total += n_accepted

            stat_table_data[f"{band}_num_accepted"].append(n_accepted)
            stat_table_data[f"{band}_num_rejected"].append(n_rejected)
            stat_table_data[f"{band}_percent_accepted"].append(percent)

        # 100 patches per tract x 6 bands.
        stat_table_data["percent_full_tract_band_coverage"].append(
            total / 600 * 100
        )

    stat_table = Table(stat_table_data)
    stat_table.write(stats_records_file, format="ascii.csv", overwrite=True)


def read_association_refs(butler, filename):
    """Recover DatasetRefs from an association recovery file.

    Each row of the ECSV file identifies an exact dataset by dataset type,
    run, skymap, tract, patch, and band. The corresponding DatasetRef is
    recovered from the Butler repository. Each row must resolve to exactly
    one DatasetRef.

    The recovered ``template_coadd`` and ``template_coadd_n_image`` datasets
    are also validated as pairs: every coadd must have an n-image dataset
    with the same skymap, tract, patch, and band, and vice versa.

    Parameters
    ----------
    butler : `lsst.daf.butler.Butler`
        Butler used to recover DatasetRefs from the repository.
    filename : `str`
        Path to the ECSV association recovery file.

    Returns
    -------
    coadd_refs : `list` of `lsst.daf.butler.DatasetRef`
        Recovered ``template_coadd`` references.
    n_image_refs : `list` of `lsst.daf.butler.DatasetRef`
        Recovered ``template_coadd_n_image`` references.

    Raises
    ------
    RuntimeError
        Raised if a row does not resolve to exactly one DatasetRef, if the
        recovery file contains an unexpected dataset type, or if the
        recovered template coadd and n-image data IDs do not match.
    """
    table = Table.read(filename, format="ascii.ecsv")

    coadd_refs = []
    n_image_refs = []

    for row in table:
        dataset_type = str(row["dataset_type"])
        run = str(row["run"])

        where = (
            f"skymap='{row['skymap']}' AND tract={row['tract']} "
            f"AND patch={row['patch']} AND band='{row['band']}'"
        )

        matches = butler.query_datasets(dataset_type, collections=[run], where=where, limit=None)

        if len(matches) != 1:
            raise RuntimeError(
                f"Expected exactly one {dataset_type} for "
                f"tract={row['tract']}, patch={row['patch']}, "
                f"band={row['band']} in {run}; found {len(matches)}."
            )

        ref = matches[0]

        if dataset_type == "template_coadd":
            coadd_refs.append(ref)
        elif dataset_type == "template_coadd_n_image":
            n_image_refs.append(ref)
        else:
            raise RuntimeError(
                f"Unexpected dataset type '{dataset_type}' in {filename}."
            )

    # Verify that every template_coadd has a corresponding template_coadd_n_image.
    coadd_data_ids = {
        (
            ref.dataId["skymap"],
            ref.dataId["tract"],
            ref.dataId["patch"],
            ref.dataId["band"],
        )
        for ref in coadd_refs
    }
    n_image_data_ids = {
        (
            ref.dataId["skymap"],
            ref.dataId["tract"],
            ref.dataId["patch"],
            ref.dataId["band"],
        )
        for ref in n_image_refs
    }

    missing_n_images = coadd_data_ids - n_image_data_ids
    missing_coadds = n_image_data_ids - coadd_data_ids
    
    if missing_n_images or missing_coadds:
        raise RuntimeError(
            "Association record contains mismatched template_coadd and "
            "template_coadd_n_image data IDs. "
            f"Missing n_images for: {sorted(missing_n_images)}; "
            f"missing coadds for: {sorted(missing_coadds)}."
        )

    return coadd_refs, n_image_refs


def write_association_refs(accepted_coadd_refs, accepted_n_image_refs, filename):
    """Write DatasetRefs needed for association to an ECSV recovery file.

    The recovery file records the dataset type, run, skymap, tract, patch,
    and band for each accepted ``template_coadd`` and
    ``template_coadd_n_image``. These fields provide enough information for
    :func:`read_association_refs` to recover the exact datasets later if
    association with the TAGGED collection must be retried.

    Parameters
    ----------
    accepted_coadd_refs : iterable of `lsst.daf.butler.DatasetRef`
        Accepted ``template_coadd`` references to record.
    accepted_n_image_refs : iterable of `lsst.daf.butler.DatasetRef`
        Corresponding accepted ``template_coadd_n_image`` references to
        record.
    filename : `str`
        Path to the output ECSV recovery file.
    """
    rows = []

    for dataset_type, refs in (
        ("template_coadd", accepted_coadd_refs),
        ("template_coadd_n_image", accepted_n_image_refs),
    ):
        for ref in refs:
            rows.append(
                (
                    dataset_type, ref.run,
                    ref.dataId["skymap"], ref.dataId["tract"],
                    ref.dataId["patch"], ref.dataId["band"],
                )
            )

    table = Table(
        rows=rows,
        names=("dataset_type", "run", "skymap", "tract", "patch", "band"),
    )
    table.write(filename, format="ascii.ecsv", overwrite=True)


def associate_from_file(read_butler, write_butler, filename, tagged_collection):
    """Associate DatasetRefs from an ECSV recovery file.

    Parameters
    ----------
    read_butler : `lsst.daf.butler.Butler`
        Butler used to recover the DatasetRefs.
    write_butler : `lsst.daf.butler.Butler`
        Writeable Butler used to create and modify the tagged collection.
    filename : `str`
        Path to the ECSV recovery file.
    tagged_collection : `str`
        Name of the TAGGED collection to create.

    Raises
    ------
    RuntimeError
        Raised if a DatasetRef cannot be uniquely recovered or if the
        recovery file contains mismatched DatasetRefs.
    """
    logging.info(f"Reading association records from {filename}.")
    coadd_refs, n_image_refs = read_association_refs(
        read_butler,
        filename,
    )

    logging.info(
        f"Recovered {len(coadd_refs)} template_coadd refs and "
        f"{len(n_image_refs)} template_coadd_n_image refs."
    )

    registered = write_butler.collections.register(tagged_collection, type=CollectionType.TAGGED)
    if registered:
        logging.info(f"Created tagged collection {tagged_collection}.")
    else:
        logging.info(
            f"Tagged collection {tagged_collection} already exists; "
            "associating recovered refs with the existing collection."
        )

    logging.info(
        f"Associating {len(coadd_refs)} template_coadds and "
        f"{len(n_image_refs)} template_coadd_n_images to "
        f"{tagged_collection}."
    )

    write_butler.registry.associate(tagged_collection, coadd_refs)
    write_butler.registry.associate(tagged_collection, n_image_refs)

    logging.info(f"Association to {tagged_collection} complete.")


def run_curate(args):
    """Run template curation and associate accepted datasets.

    Candidate ``template_coadd`` datasets are selected using metrics from
    their ``template_coadd_depth_table`` datasets and the minimum and maximum
    filters supplied on the command line. Accepted coadds are retained only
    when a corresponding ``template_coadd_n_image`` is available.

    Curation statistics and an ECSV association recovery file are written
    before the repository is modified. A new user candidate TAGGED collection
    is then created and the accepted ``template_coadd`` and
    ``template_coadd_n_image`` datasets are associated with it.

    Parameters
    ----------
    args : `argparse.Namespace`
        Parsed command-line arguments for the ``curate`` command, including
        the repository, input collections, skymap, collection tag and release
        ID, output paths, query constraints, and curation filters.

    Notes
    -----
    The association recovery file contains the exact DatasetRefs selected by
    curation and can be supplied to the ``associate`` command if repository
    association needs to be retried without rerunning curation.
    """
    # Create tagged collection name.
    username = os.environ.get("USER")
    tagged_collection = (
        f"u/{username}/LSSTCam/templates/candidates/"
        f"{args.tag}/{args.release_id}"
    )

    # Run curation and association.
    read_butler = Butler(args.repo, collections=args.collections)
    write_butler = Butler(args.repo, writeable=True)

    # Create directory for records
    directory = args.records_path
    if directory:
        if not os.path.exists(directory):
            os.makedirs(directory)

    # Set stat_records defaults based on release_id if not provided
    if args.stat_records is None:
        args.stat_records = f"{args.release_id}_stat_records.csv"

    # Parse filters, if any, into a dictionary.
    min_filters = parse_filters(args.min_filter)
    max_filters = parse_filters(args.max_filter)

    # Query datasets.
    logging.info("Collecting coadd_depth_table, template_coadd, and template_coadd_n_image refs.")
    if args.where:
        where = f"{args.where} AND skymap='{args.skymap}'"
    else:
        where = f"skymap='{args.skymap}'"
    coadd_depth_table_refs = read_butler.query_datasets("template_coadd_depth_table", where=where, limit=None)
    if not coadd_depth_table_refs:
        logging.error("No coadd_depth_table datasets found in the given collections.")
        sys.exit(1)

    # Get the relevant tracts.
    tracts = {item.dataId["tract"] for item in coadd_depth_table_refs}

    # Amend the where expression to restrict refs to relevant tracts.
    tracts_str = ",".join(str(t) for t in sorted(tracts))
    tract_restriction = f"tract IN ({tracts_str})"
    where = f"{where} AND {tract_restriction}"

    # Get relevant template_coadd and template_coadd_n_image refs.
    coadd_refs = read_butler.query_datasets("template_coadd", where=where, limit=None)
    if not coadd_refs:
        logging.error("No template_coadd datasets found in the given collections.")
        sys.exit(1)
    n_image_refs = read_butler.query_datasets("template_coadd_n_image", where=where, limit=None)
    if not n_image_refs:
        logging.error("No template_coadd_n_image datasets found in the given collections.")
        sys.exit(1)
    logging.info(f"Found {len(coadd_refs)} template_coadd datasets with coadd_depth_tables "
                 f"in {args.collections}.")

    # Filter out template_coadds that don't meet the cutoff and save them to record.
    logging.info("Starting curation with filters:")
    for key, value in min_filters.items():
        logging.info(f"{key} >= {value}")
    for key, value in max_filters.items():
        logging.info(f"{key} <= {value}")
    start_time = time.perf_counter()
    accepted_coadd_refs, rejected_coadd_refs, accepted_n_image_refs = (
        make_threshold_cuts(
            read_butler,
            coadd_refs,
            n_image_refs,
            coadd_depth_table_refs,
            min_filters,
            max_filters,
        )
    )
    end_time = time.perf_counter()
    logging.info(f"Curation complete. Accepted {len(accepted_coadd_refs)} out of {len(coadd_refs)}"
                 f" template_coadd datasets in {args.collections}."
                 f" Process took {(end_time - start_time) / 60:.2f} minutes.")

    # Run accepted/rejected statistics and save them to record.
    logging.info("Starting stat generation.")
    start_time = time.perf_counter()
    stats_records_file = os.path.join(directory, args.stat_records)
    run_stats(accepted_coadd_refs, rejected_coadd_refs, tracts, stats_records_file)
    end_time = time.perf_counter()
    logging.info("Stat generation complete. Accepted/rejected stat records written to"
                 f" {stats_records_file}. Process took {(end_time - start_time) / 60:.2f} minutes.")

    # Write DatasetRefs to ECSV before modifying the repository.
    association_records_file = os.path.join(directory, f"{args.release_id}_association_refs.ecsv")
    write_association_refs(accepted_coadd_refs, accepted_n_image_refs, association_records_file)

    # Create tagged collection, abort if it already exists.
    logging.info(f"Creating tagged collection {tagged_collection}.")
    registered = write_butler.collections.register(tagged_collection, type=CollectionType.TAGGED)
    if not registered:
        logging.error(f"Collection {tagged_collection} already exists. Aborting.")
        sys.exit(1)

    # Associate accepted template_coadds and template_coadd_n_images to tagged collection.
    logging.info(f"Associating {len(accepted_coadd_refs)} template_coadds and "
                 f"{len(accepted_n_image_refs)} template_coadd_n_images to {tagged_collection}.")
    start_time = time.perf_counter()
    write_butler.registry.associate(tagged_collection, accepted_coadd_refs)
    write_butler.registry.associate(tagged_collection, accepted_n_image_refs)
    end_time = time.perf_counter()
    logging.info(f"Association complete. Process took {(end_time - start_time) / 60:.2f} minutes.")


def run_associate(args):
    """Recover curated DatasetRefs and associate them with a TAGGED collection.

    This command provides the recovery path for a curation run whose
    association step did not complete successfully. DatasetRefs are recovered
    from the saved ECSV association file, validated, and associated with the
    user candidate TAGGED collection for the requested tag and release.

    Parameters
    ----------
    args : `argparse.Namespace`
        Parsed command-line arguments for the ``associate`` command, including
        the repository, collection tag, release ID, and path to the ECSV
        association recovery file.

    Notes
    -----
    If DatasetRef recovery or validation fails, the error is logged and the
    command exits with a nonzero status.
    """
    # Construct tagged collection name.
    username = os.environ.get("USER")
    tagged_collection = (
        f"u/{username}/LSSTCam/templates/candidates/"
        f"{args.tag}/{args.release_id}"
    )
    
    # Associate from file.
    read_butler = Butler(args.repo)
    write_butler = Butler(args.repo, writeable=True)

    try:
        associate_from_file(read_butler, write_butler, args.from_file, tagged_collection)
    except RuntimeError as error:
        logging.error(str(error))
        sys.exit(1)


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    # Hide spurious messages from numexpr by setting the numexpr env var.
    os.environ["NUMEXPR_MAX_THREADS"] = "8"

    args = _make_parser().parse_args()

    if args.command == "associate":
        run_associate(args)
    elif args.command == "curate":
        run_curate(args)

if __name__ == "__main__":
    main()

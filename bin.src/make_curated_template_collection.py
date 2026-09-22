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


"""Make a new template_coadd TAGGED and RUN collections with curated template_coadds.

This script filters and copies a curated set of template_coadd datasets to a new
location in a butler repository, and tags them to a new collection.

The input collections are ideally collections with only curated templates.

The scripts leaves an ecsv file used by butler ingest-files.
"""

import argparse
import logging
import sys
import time

from astropy.table import Table

from lsst.daf.butler import Butler, CollectionType
from lsst.daf.butler.script import ingest_files

# TODO: Update when DECam template types are registered.
TEMPLATE_TYPES = (
    "template_coadd",
)


def _make_parser():
    """Construct the command-line argument parser.

    Returns
    -------
    parser : `argparse.ArgumentParser`
        Parser configured for curated template collection creation.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "src_repo",
        help="An existing data repository containing the input collections.",
    )
    parser.add_argument(
        "tag",
        help="The Jira ticket number associated with the vetted template collection."
        " Will be used to construct the new collection name.",
    )
    parser.add_argument(
        "release_num",
        help="The release number (##) for the given tag.",
    )
    parser.add_argument(
        "--dest_repo",
        default="embargo",
        help="The repository to which to copy the datasets."
        " Default is embargo.",
    )
    parser.add_argument(
        "--collections",
        action="extend",
        nargs="+",
        required=True,
        help="The input collections containing curated template datasets.",
    )
    parser.add_argument(
        "--existing_collection",
        action="extend",
        nargs="+",
        help="The existing template collection. Optional.",
    )
    parser.add_argument(
        "--where",
        default=None,
        help="A string expression to select datasets in the input collections.",
    )
    parser.add_argument(
        "--reject",
        default="",
        help="An input table file listing data IDs to exclude from the final dataset."
        " The table must include 'tract', 'patch', and 'band' columns.",
    )
    parser.add_argument(
        "--records",
        help="An output table file with records of selected template files."
        " The file can be used by butler ingest-files."
        " Default is {tag}_{release_num}_records.ecsv.",
    )
    parser.add_argument(
        "--template_type",
        choices=TEMPLATE_TYPES,
        default="template_coadd",
        help="The dataset type of the new templates.",
    )
    return parser


def make_data_id(ref):
    """Return the data ID for a template.

    Parameters
    ----------
    ref : `lsst.daf.butler.DatasetRef`
        Template coadd dataset reference.

    Returns
    -------
    data_id : `tuple`
        Tuple containing the tract, patch, and band.
    """
    return (
        ref.dataId["tract"],
        ref.dataId["patch"],
        ref.dataId["band"],
    )


def filter_rejected_refs(new_refs, reject_table):
    """Remove manually rejected templates.

    Parameters
    ----------
    new_refs : iterable of `lsst.daf.butler.DatasetRef`
        New template references.
    reject_table : `astropy.table.Table`
        Table containing rejected tract, patch, and band combinations.

    Returns
    -------
    filtered_refs : `list` of `lsst.daf.butler.DatasetRef`
        Template references not present in the rejection table.
    """
    # Validate table columns.
    required_columns = {"tract", "patch", "band"}
    missing_columns = required_columns - set(reject_table.colnames)

    if missing_columns:
        raise RuntimeError(
            "Reject table is missing required column(s): "
            f"{sorted(missing_columns)}. "
            f"Available columns: {reject_table.colnames}"
        )

    # Reject templates that did not pass manual vetting.
    rejected_data_ids = {
        (row["tract"], row["patch"], row["band"])
        for row in reject_table
    }

    return [
        ref
        for ref in new_refs
        if make_data_id(ref) not in rejected_data_ids
    ]


def handle_duplicates(read_butler, existing_collections, new_refs, template_type):
    """Drop new templates whose data IDs already exist in production.

    Existing templates of any supported template dataset type are considered
    duplicates.

    Parameters
    ----------
    read_butler : `lsst.daf.butler.Butler`
        Butler instance pointing at the source repository.
    existing_collections : `str` or `list` of `str`
        Collections to query for existing templates.
    new_refs : iterable of `lsst.daf.butler.DatasetRef`
        New template references to deduplicate.
    template_type : `str`
        The dataset type of the new templates.

    Returns
    -------
    new_ref_list : `list` of `lsst.daf.butler.DatasetRef`
        New template references whose data IDs are not already present.
    """
    # Find existing templates.
    existing_data_ids = set()

    for existing_template_type in TEMPLATE_TYPES:
        existing_refs = read_butler.query_datasets(
            existing_template_type,
            collections=existing_collections,
            find_first=True,
            limit=None,
        )
        existing_data_ids.update(make_data_id(ref) for ref in existing_refs)

    # Check for duplicates within the new templates.
    new_ref_map = {}
    for ref in new_refs:
        data_id = make_data_id(ref)
        if data_id in new_ref_map:
            raise RuntimeError(
                f"Multiple new {template_type} datasets found for "
                f"tract={data_id[0]}, patch={data_id[1]}, band={data_id[2]}."
            )
        new_ref_map[data_id] = ref

    # Find and remove existing templates from new templates.
    duplicate_data_ids = existing_data_ids & set(new_ref_map)

    for data_id in duplicate_data_ids:
        new_ref_map.pop(data_id)

    logging.info(f"Dropped {len(duplicate_data_ids)} duplicates of existing coadds.")

    return list(new_ref_map.values())


def write_ingest_records(read_butler, filtered_refs, records_file):
    """Write an ECSV record of vetted templates for ingestion.

    Parameters
    ----------
    read_butler : `lsst.daf.butler.Butler`
        Butler instance pointing at the source repository.
    filtered_refs : iterable of `lsst.daf.butler.DatasetRef`
        Vetted template references to include in the record.
    records_file : `str`
        Path to the output ECSV file used by ``butler ingest-files``.
    """
    # Generate record of vetted curated templates.
    start_time = time.perf_counter()
    logging.info("Begin generating record of vetted curated templates.")
    columns = ("filename", "band", "skymap", "tract", "patch")
    data = Table(names=columns, dtype=("str", "str", "str", "int", "int"))
    for ref in filtered_refs:
        uri_path = read_butler.getURI(ref).geturl()
        data_id_values = tuple(ref.dataId[col] for col in columns[1:])
        data.add_row((uri_path, *data_id_values))
    data.write(records_file, overwrite=True)
    end_time = time.perf_counter()
    logging.info(f"Intermediate data records written to {records_file}."
                 f" Process took {(end_time - start_time) / 60:.2f} minutes.")


def copy_templates(tagged_collection, dest_repo, records_file, template_type):
    """Copy vetted templates into a new run collection.

    Parameters
    ----------
    tagged_collection : `str`
        Name of the tagged collection associated with this template release.
    dest_repo : `str`
        Destination Butler repository.
    records_file : `str`
        Path to the ECSV file containing the datasets to ingest.
    template_type : `str`
        The dataset type of the new templates.

    Returns
    -------
    run_collection : `str`
        Name of the run collection containing the copied templates.
    """
    # Copy templates to new location.
    run_collection = f"{tagged_collection}/run"
    start_time = time.perf_counter()
    logging.info("Begin copying templates to new location.")
    ingest_files(
        dest_repo,
        template_type,
        run_collection,
        table_file=records_file,
        transfer="copy",
    )
    end_time = time.perf_counter()
    logging.info(f"Copying complete. Process took {(end_time - start_time) / 60:.2f} minutes.")

    return run_collection


def associate_templates(write_butler, run_collection, tagged_collection, template_type, expected_count):
    """Associate newly ingested templates with the tagged collection.

    Parameters
    ----------
    write_butler : `lsst.daf.butler.Butler`
        Writeable Butler instance pointing at the destination repository.
    run_collection : `str`
        Run collection containing the newly ingested templates.
    tagged_collection : `str`
        Tagged collection with which to associate the new templates.
    template_type : `str`
        The dataset type of the new templates.
    expected_count : `int`
        Expected number of templates in the run collection.

    Raises
    ------
    RuntimeError
        Raised if the number of datasets found in the run collection does not
        match ``expected_count``.
    """
    start_time = time.perf_counter()

    new_refs = write_butler.query_datasets(template_type, collections=run_collection, limit=None)

    if len(new_refs) != expected_count:
        raise RuntimeError(
            f"Expected {expected_count} {template_type} datasets in "
            f"{run_collection}, but found {len(new_refs)}."
        )

    logging.info(f"Associating {len(new_refs)} datasets to {tagged_collection}.")
    write_butler.registry.associate(tagged_collection, new_refs)

    end_time = time.perf_counter()
    logging.info(
        f"Association complete. Process took {(end_time - start_time) / 60:.2f} minutes."
    )


def run_make_collection(args):
    """Create a curated template release from vetted templates.

    Parameters
    ----------
    args : `argparse.Namespace`
        Parsed command-line arguments specifying the source and destination
        repositories, input collections, release information, and optional
        rejection and duplicate-filtering inputs.

    Raises
    ------
    RuntimeError
        Raised if no input templates are found, no templates remain after
        filtering, or the output tagged collection already exists.
    """
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    read_butler = Butler(args.src_repo)
    write_butler = Butler(args.dest_repo, writeable=True)

    # Set records default if not provided
    records_file = args.records
    if records_file is None:
        records_file = f"{args.tag}_{args.release_num}_records.ecsv"

    refs = read_butler.query_datasets(
        args.template_type, collections=args.collections, where=args.where, limit=None
    )
    if not refs:
        raise RuntimeError(f"No {args.template_type} datasets found in the input collections.")
    logging.info(f"Found {len(refs)} {args.template_type} datasets in {args.collections}.")

    # Handle rejected refs.
    if args.reject:
        reject_table = Table.read(args.reject)
        filtered_refs = filter_rejected_refs(refs, reject_table)
    else:
        filtered_refs = refs

    # Handle duplicates.
    if args.existing_collection:
        filtered_refs = handle_duplicates(
            read_butler,
            args.existing_collection,
            filtered_refs,
            args.template_type,
        )
    else:
        logging.info("No existing_collection specified; skipping duplicate handling.")

    # Save filtered refs to record.
    if len(filtered_refs) == 0:
        raise RuntimeError(f"No {args.template_type} remain after filtering.")
    write_ingest_records(read_butler, filtered_refs, records_file)

    # Create tagged collection, abort if it already exists, and copy URIs to new collection.
    tagged_collection = f"LSSTCam/templates/{args.tag}/release_{args.release_num}"
    registered = write_butler.collections.register(
        tagged_collection, type=CollectionType.TAGGED
    )
    if not registered:
        raise RuntimeError(f"Collection {tagged_collection} already exists in {args.dest_repo}. Aborting.")
    else:
        logging.info(f"Collection {tagged_collection} registered.")

    # Copy templates to new location.
    run_collection = copy_templates(tagged_collection, args.dest_repo, records_file, args.template_type)
    
    # Associate vetted templates to tagged collection.
    associate_templates(write_butler, run_collection, tagged_collection, args.template_type, len(filtered_refs))


def main():
    args = _make_parser().parse_args()
    run_make_collection(args)

if __name__ == "__main__":
    main()

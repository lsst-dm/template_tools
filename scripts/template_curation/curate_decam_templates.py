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


"""Stage a release of DECam templates for Prompt Processing.

The script selects DECam template coadds from an input RUN collection of the
form ``DECam/templates/<ticket>/<release>/run``, tags them into a new TAGGED
collection ``DECam/templates/<ticket>/<release>``, and prepends that collection
to the ``DECam/templates_prep`` chain.

A tract/band combination is skipped entirely if any patch of it already has a
template in ``LSSTCam/templates_prep``. Otherwise, only the patches that
already have a template in ``DECam/templates_prep`` are skipped. The
templates are tagged, not copied. Only templates on the skymap given by
``--skymap`` are considered; templates on other skymaps are ignored.

The script does not create the chain. If it does not exist yet, the script
still creates the TAGGED collection and prints the command that creates the
chain from it.
"""

import argparse
import logging
import sys
from collections import defaultdict

from lsst.daf.butler import Butler, CollectionType
from lsst.daf.butler.registry import MissingCollectionError


_log = logging.getLogger("curate_decam_templates")


def _make_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("repo", help="An existing data repository, e.g. 'main'.")
    parser.add_argument(
        "input_collection",
        help="The RUN collection holding the new templates, e.g. DECam/templates/DM-57022/release_01/run.",
    )
    parser.add_argument(
        "--skymap", required=True, help="The skymap of the templates to stage, e.g. lsst_cells_v2."
    )
    parser.add_argument(
        "--dataset-type",
        default="template_coadd_decam",
        help="The dataset type of the DECam templates (default: %(default)s).",
    )
    parser.add_argument(
        "--chain",
        default="DECam/templates_prep",
        help="The CHAINED collection to prepend the new templates to (default: %(default)s).",
    )
    parser.add_argument(
        "--existing-collection",
        default="LSSTCam/templates_prep",
        help="The collection of existing LSSTCam templates (default: %(default)s).",
    )
    parser.add_argument(
        "--existing-dataset-type",
        default="template_coadd",
        help="The dataset type of the existing LSSTCam templates (default: %(default)s).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report which tract/bands would be kept or skipped without writing to the repository.",
    )
    return parser


def _get_tagged_name(input_collection):
    """Return the TAGGED collection name for an input RUN collection.

    Parameters
    ----------
    input_collection : `str`
        The input RUN collection, of the form
        ``DECam/templates/<ticket>/<release>/run``.

    Returns
    -------
    tagged_collection : `str`
        The input collection name without the ``/run`` suffix.
    """
    parts = input_collection.split("/")
    if len(parts) != 5 or parts[:2] != ["DECam", "templates"] or parts[4] != "run":
        raise ValueError(
            f"Input collection {input_collection!r} does not have the form "
            "DECam/templates/<ticket>/<release>/run."
        )
    return "/".join(parts[:4])


def check_collection(butler, name, expected=None, required=True):
    """Check that a collection has the expected type.

    Parameters
    ----------
    butler : `lsst.daf.butler.Butler`
        The butler to query.
    name : `str`
        The collection name.
    expected : `lsst.daf.butler.CollectionType`, optional
        The required collection type, if any.
    required : `bool`, optional
        Whether to exit if the collection does not exist.

    Returns
    -------
    exists : `bool`
        Whether the collection exists.
    """
    try:
        info = butler.collections.get_info(name)
    except MissingCollectionError:
        if required:
            _log.error("Collection %s does not exist.", name)
            sys.exit(1)
        return False
    if expected is not None and info.type != expected:
        _log.error("Collection %s is %s, expected %s.", name, info.type.name, expected.name)
        sys.exit(1)
    return True


def log_other_skymaps(butler, collection, dataset_types, skymap, log):
    """Log any skymaps besides the given one used in a collection.

    Parameters
    ----------
    butler : `lsst.daf.butler.Butler`
        The butler to query.
    collection : `str`
        The collection to check.
    dataset_types : iterable [`str`]
        Only check the collection if it holds any of these dataset types.
    skymap : `str`
        The skymap in use.
    log : `logging.Logger`
        The logger to report to.

    Notes
    -----
    The collection summary lists skymaps for all dataset types together, so
    the skymaps reported may come from other dataset types.
    """
    summary = butler.registry.getCollectionSummary(collection)
    if summary.dataset_types.names.isdisjoint(dataset_types):
        return
    other_skymaps = set(summary.governors.get("skymap", set())) - {skymap}
    if other_skymaps:
        log.info(
            "Ignoring datasets in %s with skymap(s) %s.", collection, ", ".join(sorted(other_skymaps))
        )


def get_covered(butler, collection, dataset_type, skymap, tracts, by_patch=False):
    """Return the tract/bands or patches with datasets in a collection.

    Parameters
    ----------
    butler : `lsst.daf.butler.Butler`
        The butler to query.
    collection : `str`
        The collection to search.
    dataset_type : `str`
        The dataset type to search for.
    skymap : `str`
        The skymap of the tracts.
    tracts : `set` [`int`]
        The tracts to search.
    by_patch : `bool`, optional
        Whether to return patches instead of tract/bands.

    Returns
    -------
    covered : `set` [`tuple`]
        The (tract, band) pairs with at least one dataset, or the
        (tract, patch, band) triples with a dataset if ``by_patch`` is set.
    """
    if dataset_type not in butler.registry.getCollectionSummary(collection).dataset_types.names:
        return set()
    refs = butler.query_datasets(
        dataset_type,
        collections=collection,
        find_first=False,
        data_id={"skymap": skymap},
        where="tract IN (:tracts)",
        bind={"tracts": tracts},
        limit=None,
        explain=False,
    )
    if by_patch:
        return {(ref.dataId["tract"], ref.dataId["patch"], ref.dataId["band"]) for ref in refs}
    return {(ref.dataId["tract"], ref.dataId["band"]) for ref in refs}


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    parser = _make_parser()
    args = parser.parse_args()

    try:
        tagged_collection = _get_tagged_name(args.input_collection)
    except ValueError as e:
        parser.error(str(e))
    butler = Butler(args.repo, writeable=not args.dry_run)

    check_collection(butler, args.input_collection, CollectionType.RUN)
    check_collection(butler, args.existing_collection)
    chain_exists = check_collection(butler, args.chain, CollectionType.CHAINED, required=False)
    if not chain_exists:
        _log.warning(
            "Chain %s does not exist; checking coverage in %s only.", args.chain, args.existing_collection
        )
    if check_collection(butler, tagged_collection, required=False):
        _log.error("Collection %s already exists. Aborting.", tagged_collection)
        sys.exit(1)

    skymap = args.skymap
    refs = butler.query_datasets(
        args.dataset_type,
        collections=args.input_collection,
        data_id={"skymap": skymap},
        limit=None,
        explain=False,
    )
    if not refs:
        _log.error("No %s datasets with skymap %s in %s.", args.dataset_type, skymap, args.input_collection)
        sys.exit(1)
    _log.info(
        "Found %d %s datasets with skymap %s in %s.",
        len(refs),
        args.dataset_type,
        skymap,
        args.input_collection,
    )
    checks = [
        (args.input_collection, args.dataset_type),
        (args.existing_collection, args.existing_dataset_type),
    ]
    if chain_exists:
        checks.append((args.chain, args.dataset_type))
    for collection, dataset_type in checks:
        log_other_skymaps(butler, collection, [dataset_type], skymap, _log)

    patches = defaultdict(list)
    for ref in refs:
        patches[(ref.dataId["tract"], ref.dataId["band"])].append(ref)
    tracts = {tract for tract, _ in patches}

    covered_lsstcam = get_covered(
        butler, args.existing_collection, args.existing_dataset_type, skymap, tracts
    )
    if chain_exists:
        covered_decam = get_covered(butler, args.chain, args.dataset_type, skymap, tracts, by_patch=True)
    else:
        covered_decam = set()

    selected = []
    n_kept = 0
    for (tract, band), band_refs in sorted(patches.items()):
        if (tract, band) in covered_lsstcam:
            status = f"skipped, already covered in {args.existing_collection}"
        else:
            new_refs = [ref for ref in band_refs if (tract, ref.dataId["patch"], band) not in covered_decam]
            n_in_chain = len(band_refs) - len(new_refs)
            if not new_refs:
                status = f"skipped, all patches already in {args.chain}"
            elif n_in_chain:
                status = f"kept {len(new_refs)}, {n_in_chain} already in {args.chain}"
            else:
                status = "kept"
            selected.extend(new_refs)
            n_kept += bool(new_refs)
        _log.info("Tract %d band %s (%d patches): %s.", tract, band, len(band_refs), status)
    _log.info(
        "Selected %d of %d datasets, %d of %d tract/bands.", len(selected), len(refs), n_kept, len(patches)
    )

    if not selected:
        _log.warning("No templates selected; nothing to stage.")
        return
    if args.dry_run:
        _log.info("Dry run: would tag %d datasets into %s.", len(selected), tagged_collection)
        return

    # One transaction, so a failure leaves no partial collection to block a
    # rerun.
    with butler.transaction():
        butler.collections.register(tagged_collection, type=CollectionType.TAGGED)
        butler.registry.associate(tagged_collection, selected)
        if chain_exists:
            butler.collections.prepend_chain(args.chain, tagged_collection)
    _log.info("Tagged %d datasets into %s.", len(selected), tagged_collection)
    if chain_exists:
        _log.info("Prepended %s to %s.", tagged_collection, args.chain)
    else:
        _log.warning(
            "%s was not added to %s because the chain does not exist. Create the chain with:\n"
            "    butler collection-chain %s %s %s",
            tagged_collection,
            args.chain,
            args.repo,
            args.chain,
            tagged_collection,
        )


if __name__ == "__main__":
    main()

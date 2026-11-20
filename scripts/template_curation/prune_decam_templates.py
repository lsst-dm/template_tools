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


"""Drop DECam templates that LSSTCam templates now cover.

Run this after new LSSTCam templates are added to ``LSSTCam/templates_prep``.
For each release in the ``DECam/templates_prep`` chain, every tract/band with
at least one patch in ``LSSTCam/templates_prep`` is dropped.

A release that loses templates is replaced in the chain, at the same position,
by a new TAGGED collection with the next unused release number for its ticket:
``DECam/templates/DM-57022/release_01`` becomes
``DECam/templates/DM-57022/release_02``. A release that loses all of its
templates is removed from the chain. The old TAGGED collections are unchanged.

Each release must hold templates on a single skymap. Only releases on the
skymap given by ``--skymap`` are pruned; releases on other skymaps are left
unchanged.
"""

import argparse
import logging
import re
import sys
from collections import defaultdict

from lsst.daf.butler import Butler, CollectionType

from curate_decam_templates import check_collection, get_covered, log_other_skymaps


_log = logging.getLogger("prune_decam_templates")

_RELEASE_PATTERN = re.compile(r"^(DECam/templates/[^/]+)/release_(\d+)$")


def _make_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("repo", help="An existing data repository, e.g. 'main'.")
    parser.add_argument(
        "--skymap", required=True, help="The skymap of the templates to prune, e.g. lsst_cells_v2."
    )
    parser.add_argument(
        "--dataset-type",
        default="template_coadd_decam",
        help="The dataset type of the DECam templates (default: %(default)s).",
    )
    parser.add_argument(
        "--chain",
        default="DECam/templates_prep",
        help="The CHAINED collection of DECam releases to prune (default: %(default)s).",
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
        help="Report which tract/bands would be dropped without writing to the repository.",
    )
    return parser


def _get_next_release_name(butler, release, reserved):
    """Return the next unused release name for a release's ticket.

    Parameters
    ----------
    butler : `lsst.daf.butler.Butler`
        The butler to query.
    release : `str`
        A TAGGED release collection,
        ``DECam/templates/<ticket>/release_<number>``.
    reserved : `set` [`str`]
        Release names already chosen in this run but not yet registered.

    Returns
    -------
    name : `str`
        The release name with a number one above the highest number used by
        any collection for the same ticket, with the same zero padding.
    """
    prefix, number = _RELEASE_PATTERN.match(release).groups()
    used_pattern = re.compile(rf"^{re.escape(prefix)}/release_(\d+)(/|$)")
    used = [int(number)]
    for name in [*butler.collections.query(f"{prefix}/release_*"), *reserved]:
        if match := used_pattern.match(name):
            used.append(int(match.group(1)))
    return f"{prefix}/release_{max(used) + 1:0{len(number)}d}"


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    args = _make_parser().parse_args()
    butler = Butler(args.repo, writeable=not args.dry_run)

    check_collection(butler, args.chain, CollectionType.CHAINED)
    check_collection(butler, args.existing_collection)
    releases = butler.collections.get_info(args.chain).children
    release_refs = {}
    for release in releases:
        check_collection(butler, release, CollectionType.TAGGED)
        if not _RELEASE_PATTERN.match(release):
            _log.error(
                "Chain member %s does not have the form DECam/templates/<ticket>/release_<number>.", release
            )
            sys.exit(1)
        refs = butler.query_datasets(args.dataset_type, collections=release, limit=None, explain=False)
        release_skymaps = {ref.dataId["skymap"] for ref in refs}
        if len(release_skymaps) > 1:
            _log.error(
                "Release %s has templates with more than one skymap: %s.",
                release,
                ", ".join(sorted(release_skymaps)),
            )
            sys.exit(1)
        release_refs[release] = refs

    skymap = args.skymap
    log_other_skymaps(butler, args.existing_collection, [args.existing_dataset_type], skymap, _log)

    new_releases = []
    replacements = {}
    for release, refs in release_refs.items():
        if not refs or refs[0].dataId["skymap"] != skymap:
            _log.info("%s: unchanged, no templates with skymap %s.", release, skymap)
            new_releases.append(release)
            continue
        patches = defaultdict(list)
        for ref in refs:
            patches[(ref.dataId["tract"], ref.dataId["band"])].append(ref)
        tracts = {tract for tract, _ in patches}
        covered = get_covered(butler, args.existing_collection, args.existing_dataset_type, skymap, tracts)
        dropped = covered & patches.keys()
        if not dropped:
            _log.info("%s: unchanged.", release)
            new_releases.append(release)
            continue
        for tract, band in sorted(dropped):
            n_patches = len(patches[(tract, band)])
            _log.info("%s: dropping tract %d band %s (%d patches).", release, tract, band, n_patches)
        kept = [ref for key, band_refs in patches.items() if key not in dropped for ref in band_refs]
        if kept:
            new_release = _get_next_release_name(butler, release, replacements.keys())
            _log.info(
                "%s: replaced by %s with %d of %d datasets.", release, new_release, len(kept), len(refs)
            )
            replacements[new_release] = kept
            new_releases.append(new_release)
        else:
            _log.info("%s: all tract/bands covered; removed from %s.", release, args.chain)

    if new_releases == list(releases):
        _log.info("No DECam templates are newly covered; nothing to prune.")
        return
    if args.dry_run:
        _log.info("Dry run: would redefine %s as %s.", args.chain, new_releases)
        return

    # One transaction, so a failure leaves the chain and the repository as they
    # were.
    with butler.transaction():
        for new_release, kept in replacements.items():
            if not butler.collections.register(new_release, type=CollectionType.TAGGED):
                raise RuntimeError(f"Collection {new_release} already exists.")
            butler.registry.associate(new_release, kept)
        butler.collections.redefine_chain(args.chain, new_releases)
    _log.info("Redefined %s as %s.", args.chain, new_releases)


if __name__ == "__main__":
    main()

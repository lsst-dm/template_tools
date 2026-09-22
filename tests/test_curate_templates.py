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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Tests for bin.src/curate_templates.py."""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from astropy.table import Table

import lsst.utils.tests


_SCRIPT = Path(__file__).parents[1] / "bin.src" / "curate_templates.py"
_SPEC = importlib.util.spec_from_file_location("curate_templates", _SCRIPT)
curate_templates = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(curate_templates)


def make_ref(
    tract,
    patch,
    band,
    *,
    skymap="lsst_cells_v2",
    run="test/run",
):
    """Construct a lightweight mock DatasetRef."""
    ref = MagicMock()
    ref.run = run
    ref.dataId = {
        "skymap": skymap,
        "tract": tract,
        "patch": patch,
        "band": band,
    }
    return ref


class ParserTestCase(lsst.utils.tests.TestCase):
    """Tests for command-line argument parsing."""

    def test_curate(self):
        parser = curate_templates._make_parser()

        args = parser.parse_args(
            [
                "curate",
                "/repo",
                "lsst_cells_v2",
                "DM-12345",
                "release_01",
                "--collections",
                "collection/one",
                "collection/two",
            ]
        )

        self.assertEqual(args.command, "curate")
        self.assertEqual(args.repo, "/repo")
        self.assertEqual(args.skymap, "lsst_cells_v2")
        self.assertEqual(args.tag, "DM-12345")
        self.assertEqual(args.release_id, "release_01")
        self.assertEqual(
            args.collections,
            ["collection/one", "collection/two"],
        )
        self.assertIsNone(args.where)
        self.assertEqual(args.records_path, "")
        self.assertIsNone(args.stat_records)

        # Filters are genuinely optional. Omitting them means no
        # corresponding threshold cut will be applied.
        self.assertIsNone(args.min_filter)
        self.assertIsNone(args.max_filter)

    def test_curate_filters(self):
        parser = curate_templates._make_parser()

        args = parser.parse_args(
            [
                "curate",
                "/repo",
                "lsst_cells_v2",
                "DM-12345",
                "release_01",
                "--collections",
                "collection",
                "--min_filter",
                "depth_above_threshold_3=90",
                "other_minimum=2.5",
                "--max_filter",
                "chip_gap_percent=0.25",
            ]
        )

        self.assertEqual(
            args.min_filter,
            [
                "depth_above_threshold_3=90",
                "other_minimum=2.5",
            ],
        )
        self.assertEqual(
            args.max_filter,
            ["chip_gap_percent=0.25"],
        )

    def test_curate_min_filter_only(self):
        parser = curate_templates._make_parser()

        args = parser.parse_args(
            [
                "curate",
                "/repo",
                "lsst_cells_v2",
                "DM-12345",
                "release_01",
                "--collections",
                "collection",
                "--min_filter",
                "depth_above_threshold_3=80",
            ]
        )

        self.assertEqual(
            args.min_filter,
            ["depth_above_threshold_3=80"],
        )
        self.assertIsNone(args.max_filter)

    def test_curate_max_filter_only(self):
        parser = curate_templates._make_parser()

        args = parser.parse_args(
            [
                "curate",
                "/repo",
                "lsst_cells_v2",
                "DM-12345",
                "release_01",
                "--collections",
                "collection",
                "--max_filter",
                "chip_gap_percent=0.5",
            ]
        )

        self.assertIsNone(args.min_filter)
        self.assertEqual(
            args.max_filter,
            ["chip_gap_percent=0.5"],
        )

    def test_associate(self):
        parser = curate_templates._make_parser()

        args = parser.parse_args(
            [
                "associate",
                "/repo",
                "DM-12345",
                "release_01",
                "--from-file",
                "association_refs.ecsv",
            ]
        )

        self.assertEqual(args.command, "associate")
        self.assertEqual(args.repo, "/repo")
        self.assertEqual(args.tag, "DM-12345")
        self.assertEqual(args.release_id, "release_01")
        self.assertEqual(
            args.from_file,
            "association_refs.ecsv",
        )

        # Arguments belonging only to curate should not leak into
        # the associate namespace.
        self.assertFalse(hasattr(args, "collections"))
        self.assertFalse(hasattr(args, "skymap"))

    def test_subcommand_required(self):
        parser = curate_templates._make_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args([])

    def test_curate_collections_required(self):
        parser = curate_templates._make_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "curate",
                    "/repo",
                    "lsst_cells_v2",
                    "DM-12345",
                    "release_01",
                ]
            )

    def test_associate_file_required(self):
        parser = curate_templates._make_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "associate",
                    "/repo",
                    "DM-12345",
                    "release_01",
                ]
            )


class ParseFiltersTestCase(lsst.utils.tests.TestCase):
    """Tests for parsing threshold filter specifications."""

    def test_none(self):
        self.assertEqual(
            curate_templates.parse_filters(None),
            {},
        )

    def test_empty_list(self):
        self.assertEqual(
            curate_templates.parse_filters([]),
            {},
        )

    def test_single_filter(self):
        self.assertEqual(
            curate_templates.parse_filters(
                ["depth_above_threshold_3=80"]
            ),
            {"depth_above_threshold_3": 80.0},
        )

    def test_multiple_filters(self):
        self.assertEqual(
            curate_templates.parse_filters(
                [
                    "depth_above_threshold_3=80",
                    "another_metric=3.5",
                ]
            ),
            {
                "depth_above_threshold_3": 80.0,
                "another_metric": 3.5,
            },
        )

    def test_integer_value_converted_to_float(self):
        filters = curate_templates.parse_filters(
            ["depth_above_threshold_3=80"]
        )

        self.assertIsInstance(
            filters["depth_above_threshold_3"],
            float,
        )

    def test_invalid_value_raises(self):
        with self.assertRaises(ValueError):
            curate_templates.parse_filters(
                ["depth_above_threshold_3=not-a-number"]
            )


class SelectRefTestCase(lsst.utils.tests.TestCase):
    """Tests for selecting refs from matching DatasetRefs."""

    def test_no_refs(self):
        with self.assertLogs(level="WARNING"):
            result = curate_templates.select_ref(
                [],
                100,
                5,
                "g",
            )

        self.assertIsNone(result)

    def test_single_ref(self):
        ref = make_ref(100, 5, "g")

        result = curate_templates.select_ref(
            [ref],
            100,
            5,
            "g",
        )

        self.assertIs(result, ref)

    def test_latest_run(self):
        old_ref = make_ref(
            100,
            5,
            "g",
            run="templates/20260901T000000Z",
        )
        new_ref = make_ref(
            100,
            5,
            "g",
            run="templates/20260902T000000Z",
        )

        # Deliberately supply the newest ref first to ensure this
        # actually sorts rather than simply selecting the last item.
        result = curate_templates.select_ref(
            [new_ref, old_ref],
            100,
            5,
            "g",
        )

        self.assertIs(result, new_ref)


class IndexRefsTestCase(lsst.utils.tests.TestCase):
    """Tests for indexing DatasetRefs."""

    def test_index_refs(self):
        ref1 = make_ref(100, 5, "g", run="run/1")
        ref2 = make_ref(100, 5, "g", run="run/2")
        ref3 = make_ref(100, 6, "r")

        result = curate_templates.index_refs(
            [ref1, ref2, ref3]
        )

        self.assertEqual(
            result[(100, 5, "g")],
            [ref1, ref2],
        )
        self.assertEqual(
            result[(100, 6, "r")],
            [ref3],
        )


class ThresholdCutsTestCase(lsst.utils.tests.TestCase):
    """Tests for template threshold cuts."""

    def setUp(self):
        self.butler = MagicMock()

        self.depth_ref = MagicMock()
        self.depth_ref.dataId = {"tract": 100}

        self.depth_table = Table(
            {
                "patch": [1, 2, 3, 4],
                "band": ["g", "g", "r", "i"],
                "depth_above_threshold_3": [
                    90.0,
                    70.0,
                    95.0,
                    80.0,
                ],
                "chip_gap_percent": [
                    0.1,
                    0.1,
                    1.0,
                    0.5,
                ],
            }
        )
        self.butler.get.return_value = self.depth_table

        self.coadds = [
            make_ref(100, patch, band)
            for patch, band in [
                (1, "g"),
                (2, "g"),
                (3, "r"),
                (4, "i"),
            ]
        ]
        self.n_images = [
            make_ref(100, patch, band)
            for patch, band in [
                (1, "g"),
                (2, "g"),
                (3, "r"),
                (4, "i"),
            ]
        ]

    def test_threshold_cuts(self):
        accepted, rejected, n_images = (
            curate_templates.make_threshold_cuts(
                self.butler,
                self.coadds,
                self.n_images,
                [self.depth_ref],
                {"depth_above_threshold_3": 80},
                {"chip_gap_percent": 0.5},
            )
        )

        # Patch 1 passes both cuts.
        # Patch 2 fails depth.
        # Patch 3 fails chip gap.
        # Patch 4 lies exactly on both boundaries and passes.
        self.assertEqual(
            accepted,
            [self.coadds[0], self.coadds[3]],
        )
        self.assertEqual(
            rejected,
            [self.coadds[1], self.coadds[2]],
        )
        self.assertEqual(
            n_images,
            [self.n_images[0], self.n_images[3]],
        )

    def test_boundary_values_are_accepted(self):
        accepted, _, _ = (
            curate_templates.make_threshold_cuts(
                self.butler,
                self.coadds,
                self.n_images,
                [self.depth_ref],
                {"depth_above_threshold_3": 80},
                {"chip_gap_percent": 0.5},
            )
        )

        self.assertIn(self.coadds[3], accepted)

    def test_no_min_filter(self):
        # This table intentionally does not contain the usual
        # depth_above_threshold_3 column. Omitting min_filters must
        # therefore avoid accessing that column entirely.
        self.butler.get.return_value = Table(
            {
                "patch": [1, 2],
                "band": ["g", "g"],
                "chip_gap_percent": [0.1, 0.7],
            }
        )

        coadds = [
            make_ref(100, 1, "g"),
            make_ref(100, 2, "g"),
        ]
        n_images = [
            make_ref(100, 1, "g"),
            make_ref(100, 2, "g"),
        ]

        accepted, rejected, accepted_n_images = (
            curate_templates.make_threshold_cuts(
                self.butler,
                coadds,
                n_images,
                [self.depth_ref],
                {},
                {"chip_gap_percent": 0.5},
            )
        )

        self.assertEqual(accepted, [coadds[0]])
        self.assertEqual(rejected, [coadds[1]])
        self.assertEqual(
            accepted_n_images,
            [n_images[0]],
        )

    def test_no_max_filter(self):
        # This table intentionally does not contain the usual
        # chip_gap_percent column. Omitting max_filters must therefore
        # avoid accessing that column entirely.
        self.butler.get.return_value = Table(
            {
                "patch": [1, 2],
                "band": ["g", "g"],
                "depth_above_threshold_3": [90.0, 70.0],
            }
        )

        coadds = [
            make_ref(100, 1, "g"),
            make_ref(100, 2, "g"),
        ]
        n_images = [
            make_ref(100, 1, "g"),
            make_ref(100, 2, "g"),
        ]

        accepted, rejected, accepted_n_images = (
            curate_templates.make_threshold_cuts(
                self.butler,
                coadds,
                n_images,
                [self.depth_ref],
                {"depth_above_threshold_3": 80},
                {},
            )
        )

        self.assertEqual(accepted, [coadds[0]])
        self.assertEqual(rejected, [coadds[1]])
        self.assertEqual(
            accepted_n_images,
            [n_images[0]],
        )

    def test_no_filters(self):
        # A collection may not contain either of the usual metric
        # columns. With no filters, all rows should pass the threshold
        # stage.
        self.butler.get.return_value = Table(
            {
                "patch": [1, 2],
                "band": ["g", "r"],
            }
        )

        coadds = [
            make_ref(100, 1, "g"),
            make_ref(100, 2, "r"),
        ]
        n_images = [
            make_ref(100, 1, "g"),
            make_ref(100, 2, "r"),
        ]

        accepted, rejected, accepted_n_images = (
            curate_templates.make_threshold_cuts(
                self.butler,
                coadds,
                n_images,
                [self.depth_ref],
                {},
                {},
            )
        )

        self.assertEqual(accepted, coadds)
        self.assertEqual(rejected, [])
        self.assertEqual(accepted_n_images, n_images)

    def test_custom_filters(self):
        # Filter names are not restricted to the historical
        # depth/chip-gap metrics.
        self.butler.get.return_value = Table(
            {
                "patch": [1, 2, 3],
                "band": ["g", "g", "g"],
                "custom_min_metric": [5.0, 2.0, 8.0],
                "custom_max_metric": [1.0, 1.0, 10.0],
            }
        )

        coadds = [
            make_ref(100, patch, "g")
            for patch in (1, 2, 3)
        ]
        n_images = [
            make_ref(100, patch, "g")
            for patch in (1, 2, 3)
        ]

        accepted, rejected, accepted_n_images = (
            curate_templates.make_threshold_cuts(
                self.butler,
                coadds,
                n_images,
                [self.depth_ref],
                {"custom_min_metric": 4.0},
                {"custom_max_metric": 5.0},
            )
        )

        self.assertEqual(accepted, [coadds[0]])
        self.assertEqual(
            rejected,
            [coadds[1], coadds[2]],
        )
        self.assertEqual(
            accepted_n_images,
            [n_images[0]],
        )

    def test_missing_n_image_excludes_accepted_coadd(self):
        n_images_missing_patch_1 = self.n_images[1:]
    
        accepted, rejected, n_images = (
            curate_templates.make_threshold_cuts(
                self.butler,
                self.coadds,
                n_images_missing_patch_1,
                [self.depth_ref],
                {"depth_above_threshold_3": 80},
                {"chip_gap_percent": 0.5},
            )
        )
    
        # Patch 1 passes the numerical cuts but has no n_image,
        # so the coadd/n_image pair must not be accepted.
        self.assertNotIn(self.coadds[0], accepted)
        self.assertNotIn(self.coadds[0], rejected)
        self.assertNotIn(self.n_images[0], n_images)

    def test_missing_rejected_coadd_is_skipped(self):
        coadds = [
            self.coadds[0],
            self.coadds[2],
            self.coadds[3],
        ]

        accepted, rejected, _ = (
            curate_templates.make_threshold_cuts(
                self.butler,
                coadds,
                self.n_images,
                [self.depth_ref],
                {"depth_above_threshold_3": 80},
                {"chip_gap_percent": 0.5},
            )
        )

        self.assertEqual(
            accepted,
            [self.coadds[0], self.coadds[3]],
        )
        self.assertEqual(
            rejected,
            [self.coadds[2]],
        )

    def test_depth_table_ref_used_for_get(self):
        curate_templates.make_threshold_cuts(
            self.butler,
            self.coadds,
            self.n_images,
            [self.depth_ref],
            {"depth_above_threshold_3": 80},
            {"chip_gap_percent": 0.5},
        )

        self.butler.get.assert_called_once_with(self.depth_ref)

    def test_missing_filter_column_raises(self):
        self.butler.get.return_value = Table(
            {
                "patch": [1],
                "band": ["g"],
                "depth_above_threshold_3": [90.0],
            }
        )

        with self.assertRaisesRegex(RuntimeError, "chip_gap_percent"):
            curate_templates.make_threshold_cuts(
                self.butler,
                self.coadds,
                self.n_images,
                [self.depth_ref],
                {"depth_above_threshold_3": 80},
                {"chip_gap_percent": 0.5},
            )


class RunStatsTestCase(lsst.utils.tests.TestCase):
    """Tests for curation statistics."""

    def test_stats(self):
        accepted = [
            make_ref(100, 1, "g"),
            make_ref(100, 2, "g"),
            make_ref(100, 3, "r"),
        ]
        rejected = [
            make_ref(100, 4, "g"),
            make_ref(100, 5, "r"),
        ]

        with tempfile.TemporaryDirectory() as directory:
            filename = os.path.join(
                directory,
                "stats.csv",
            )

            curate_templates.run_stats(
                accepted,
                rejected,
                [100],
                filename,
            )

            table = Table.read(
                filename,
                format="ascii.csv",
            )

        self.assertEqual(len(table), 1)

        row = table[0]
        self.assertEqual(row["tract"], 100)

        self.assertEqual(row["g_num_accepted"], 2)
        self.assertEqual(row["g_num_rejected"], 1)
        self.assertAlmostEqual(
            row["g_percent_accepted"],
            2 / 3 * 100,
        )

        self.assertEqual(row["r_num_accepted"], 1)
        self.assertEqual(row["r_num_rejected"], 1)
        self.assertAlmostEqual(
            row["r_percent_accepted"],
            50.0,
        )

        self.assertAlmostEqual(
            row["percent_full_tract_band_coverage"],
            3 / 600 * 100,
        )

    def test_stats_no_rejected(self):
        accepted = [
            make_ref(100, 1, "g"),
            make_ref(100, 2, "g"),
        ]
    
        with tempfile.TemporaryDirectory() as directory:
            filename = os.path.join(directory, "stats.csv")
    
            curate_templates.run_stats(
                accepted,
                [],
                [100],
                filename,
            )
    
            table = Table.read(filename, format="ascii.csv")
    
        row = table[0]
        self.assertEqual(row["g_num_accepted"], 2)
        self.assertEqual(row["g_num_rejected"], 0)
        self.assertEqual(row["g_percent_accepted"], 100.0)


    def test_stats_no_accepted(self):
        rejected = [
            make_ref(100, 1, "g"),
            make_ref(100, 2, "g"),
        ]
    
        with tempfile.TemporaryDirectory() as directory:
            filename = os.path.join(directory, "stats.csv")
    
            curate_templates.run_stats(
                [],
                rejected,
                [100],
                filename,
            )
    
            table = Table.read(filename, format="ascii.csv")
    
        row = table[0]
        self.assertEqual(row["g_num_accepted"], 0)
        self.assertEqual(row["g_num_rejected"], 2)
        self.assertEqual(row["g_percent_accepted"], 0.0)


    def test_stats_no_refs(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = os.path.join(directory, "stats.csv")
    
            curate_templates.run_stats(
                [],
                [],
                [100],
                filename,
            )
    
            table = Table.read(filename, format="ascii.csv")
    
        row = table[0]
        self.assertEqual(row["g_num_accepted"], 0)
        self.assertEqual(row["g_num_rejected"], 0)


class AssociationRecordsTestCase(lsst.utils.tests.TestCase):
    """Tests for association recovery records."""

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)

        self.filename = os.path.join(
            self.temp_directory.name,
            "association_refs.ecsv",
        )

    def _write_table(self, rows):
        table = Table(
            rows=rows,
            names=(
                "dataset_type",
                "run",
                "skymap",
                "tract",
                "patch",
                "band",
            ),
        )
        table.write(
            self.filename,
            format="ascii.ecsv",
            overwrite=True,
        )

    def test_write_association_refs(self):
        coadd = make_ref(
            100,
            5,
            "g",
            run="coadd/run",
        )
        n_image = make_ref(
            100,
            5,
            "g",
            run="n_image/run",
        )

        curate_templates.write_association_refs(
            [coadd],
            [n_image],
            self.filename,
        )

        table = Table.read(
            self.filename,
            format="ascii.ecsv",
        )

        self.assertEqual(len(table), 2)

        self.assertEqual(
            list(table["dataset_type"]),
            [
                "template_coadd",
                "template_coadd_n_image",
            ],
        )
        self.assertEqual(
            list(table["run"]),
            ["coadd/run", "n_image/run"],
        )
        self.assertEqual(
            list(table["tract"]),
            [100, 100],
        )
        self.assertEqual(
            list(table["patch"]),
            [5, 5],
        )
        self.assertEqual(
            list(table["band"]),
            ["g", "g"],
        )

    def test_read_association_refs(self):
        self._write_table(
            [
                (
                    "template_coadd",
                    "coadd/run",
                    "lsst_cells_v2",
                    100,
                    5,
                    "g",
                ),
                (
                    "template_coadd_n_image",
                    "n_image/run",
                    "lsst_cells_v2",
                    100,
                    5,
                    "g",
                ),
            ]
        )

        coadd = make_ref(
            100,
            5,
            "g",
            run="coadd/run",
        )
        n_image = make_ref(
            100,
            5,
            "g",
            run="n_image/run",
        )

        butler = MagicMock()
        butler.query_datasets.side_effect = [
            [coadd],
            [n_image],
        ]

        coadds, n_images = (
            curate_templates.read_association_refs(
                butler,
                self.filename,
            )
        )

        self.assertEqual(coadds, [coadd])
        self.assertEqual(n_images, [n_image])

        expected_where = (
            "skymap='lsst_cells_v2' "
            "AND tract=100 "
            "AND patch=5 "
            "AND band='g'"
        )

        self.assertEqual(
            butler.query_datasets.call_args_list,
            [
                call(
                    "template_coadd",
                    collections=["coadd/run"],
                    where=expected_where,
                    limit=None,
                ),
                call(
                    "template_coadd_n_image",
                    collections=["n_image/run"],
                    where=expected_where,
                    limit=None,
                ),
            ],
        )

    def test_zero_matches_raises(self):
        self._write_table(
            [
                (
                    "template_coadd",
                    "coadd/run",
                    "lsst_cells_v2",
                    100,
                    5,
                    "g",
                ),
            ]
        )

        butler = MagicMock()
        butler.query_datasets.return_value = []

        with self.assertRaisesRegex(
            RuntimeError,
            "Expected exactly one template_coadd",
        ):
            curate_templates.read_association_refs(
                butler,
                self.filename,
            )

    def test_multiple_matches_raises(self):
        self._write_table(
            [
                (
                    "template_coadd",
                    "coadd/run",
                    "lsst_cells_v2",
                    100,
                    5,
                    "g",
                ),
            ]
        )

        butler = MagicMock()
        butler.query_datasets.return_value = [
            make_ref(100, 5, "g"),
            make_ref(100, 5, "g"),
        ]

        with self.assertRaisesRegex(
            RuntimeError,
            r"found 2",
        ):
            curate_templates.read_association_refs(
                butler,
                self.filename,
            )

    def test_unexpected_dataset_type_raises(self):
        self._write_table(
            [
                (
                    "unexpected_type",
                    "test/run",
                    "lsst_cells_v2",
                    100,
                    5,
                    "g",
                ),
            ]
        )

        butler = MagicMock()
        butler.query_datasets.return_value = [
            make_ref(100, 5, "g")
        ]

        with self.assertRaisesRegex(
            RuntimeError,
            "Unexpected dataset type",
        ):
            curate_templates.read_association_refs(
                butler,
                self.filename,
            )

    def test_missing_n_image_raises(self):
        self._write_table(
            [
                (
                    "template_coadd",
                    "coadd/run",
                    "lsst_cells_v2",
                    100,
                    5,
                    "g",
                ),
            ]
        )

        butler = MagicMock()
        butler.query_datasets.return_value = [
            make_ref(100, 5, "g")
        ]

        with self.assertRaisesRegex(
            RuntimeError,
            "Missing n_images",
        ):
            curate_templates.read_association_refs(
                butler,
                self.filename,
            )

    def test_missing_coadd_raises(self):
        self._write_table(
            [
                (
                    "template_coadd_n_image",
                    "n_image/run",
                    "lsst_cells_v2",
                    100,
                    5,
                    "g",
                ),
            ]
        )

        butler = MagicMock()
        butler.query_datasets.return_value = [
            make_ref(100, 5, "g")
        ]

        with self.assertRaisesRegex(
            RuntimeError,
            "missing coadds",
        ):
            curate_templates.read_association_refs(
                butler,
                self.filename,
            )

    def test_mismatched_data_ids_raise(self):
        self._write_table(
            [
                (
                    "template_coadd",
                    "coadd/run",
                    "lsst_cells_v2",
                    100,
                    5,
                    "g",
                ),
                (
                    "template_coadd_n_image",
                    "n_image/run",
                    "lsst_cells_v2",
                    100,
                    6,
                    "g",
                ),
            ]
        )

        butler = MagicMock()
        butler.query_datasets.side_effect = [
            [make_ref(100, 5, "g")],
            [make_ref(100, 6, "g")],
        ]

        with self.assertRaisesRegex(
            RuntimeError,
            "mismatched template_coadd",
        ):
            curate_templates.read_association_refs(
                butler,
                self.filename,
            )


class AssociateFromFileTestCase(lsst.utils.tests.TestCase):
    """Tests for recovery-mode association."""

    def test_new_collection(self):
        coadd = make_ref(100, 5, "g")
        n_image = make_ref(100, 5, "g")

        read_butler = MagicMock()
        write_butler = MagicMock()
        write_butler.collections.register.return_value = True

        with patch.object(
            curate_templates,
            "read_association_refs",
            return_value=([coadd], [n_image]),
        ) as read_mock:
            curate_templates.associate_from_file(
                read_butler,
                write_butler,
                "records.ecsv",
                "u/test/templates",
            )

        read_mock.assert_called_once_with(
            read_butler,
            "records.ecsv",
        )

        write_butler.collections.register.assert_called_once_with(
            "u/test/templates",
            type=curate_templates.CollectionType.TAGGED,
        )

        self.assertEqual(
            write_butler.registry.associate.call_args_list,
            [
                call("u/test/templates", [coadd]),
                call("u/test/templates", [n_image]),
            ],
        )

    def test_existing_collection(self):
        coadd = make_ref(100, 5, "g")
        n_image = make_ref(100, 5, "g")

        read_butler = MagicMock()
        write_butler = MagicMock()

        # Collection registration returns False when the collection
        # already exists. Recovery mode should continue associating.
        write_butler.collections.register.return_value = False

        with patch.object(
            curate_templates,
            "read_association_refs",
            return_value=([coadd], [n_image]),
        ):
            curate_templates.associate_from_file(
                read_butler,
                write_butler,
                "records.ecsv",
                "u/test/templates",
            )

        self.assertEqual(
            write_butler.registry.associate.call_args_list,
            [
                call("u/test/templates", [coadd]),
                call("u/test/templates", [n_image]),
            ],
        )


class RunCurateTestCase(lsst.utils.tests.TestCase):
    """Tests for top-level curation orchestration."""

    def make_args(self):
        """Construct default arguments for run_curate."""
        args = MagicMock()
        args.repo = "/repo"
        args.collections = ["input/collection"]
        args.skymap = "test_skymap"
        args.tag = "DM-12345"
        args.release_id = "release_01"
        args.where = "instrument='LSSTCam'"
        args.records_path = ""
        args.stat_records = "stats.csv"
        args.min_filter = None
        args.max_filter = None
        return args

    @patch.object(curate_templates, "write_association_refs")
    @patch.object(curate_templates, "run_stats")
    @patch.object(curate_templates, "make_threshold_cuts")
    @patch.object(curate_templates, "Butler")
    def test_queries_include_skymap_and_tracts(
        self,
        butler_class,
        make_threshold_cuts_mock,
        run_stats_mock,
        write_association_refs_mock,
    ):
        read_butler = MagicMock()
        write_butler = MagicMock()

        butler_class.side_effect = [
            read_butler,
            write_butler,
        ]

        depth_ref_1 = MagicMock()
        depth_ref_1.dataId = {"tract": 100}
        depth_ref_2 = MagicMock()
        depth_ref_2.dataId = {"tract": 200}

        coadd = make_ref(100, 1, "g")
        n_image = make_ref(100, 1, "g")

        read_butler.query_datasets.side_effect = [
            [depth_ref_1, depth_ref_2],
            [coadd],
            [n_image],
        ]

        make_threshold_cuts_mock.return_value = (
            [coadd],
            [],
            [n_image],
        )

        write_butler.collections.register.return_value = True

        args = self.make_args()

        with patch.dict(
            os.environ,
            {"USER": "testuser"},
        ):
            curate_templates.run_curate(args)

        calls = read_butler.query_datasets.call_args_list

        self.assertEqual(
            calls[0],
            call(
                "template_coadd_depth_table",
                where=(
                    "instrument='LSSTCam' "
                    "AND skymap='test_skymap'"
                ),
                limit=None,
            ),
        )

        expected_where = (
            "instrument='LSSTCam' "
            "AND skymap='test_skymap' "
            "AND tract IN (100,200)"
        )

        self.assertEqual(
            calls[1],
            call(
                "template_coadd",
                where=expected_where,
                limit=None,
            ),
        )
        self.assertEqual(
            calls[2],
            call(
                "template_coadd_n_image",
                where=expected_where,
                limit=None,
            ),
        )

        # No CLI filters were supplied, so run_curate should pass
        # empty filter dictionaries to the curation function.
        make_threshold_cuts_mock.assert_called_once_with(
            read_butler,
            [coadd],
            [n_image],
            [depth_ref_1, depth_ref_2],
            {},
            {},
        )

        write_butler.collections.register.assert_called_once_with(
            (
                "u/testuser/LSSTCam/templates/candidates/"
                "DM-12345/release_01"
            ),
            type=curate_templates.CollectionType.TAGGED,
        )

        self.assertEqual(
            write_butler.registry.associate.call_args_list,
            [
                call(
                    (
                        "u/testuser/LSSTCam/templates/candidates/"
                        "DM-12345/release_01"
                    ),
                    [coadd],
                ),
                call(
                    (
                        "u/testuser/LSSTCam/templates/candidates/"
                        "DM-12345/release_01"
                    ),
                    [n_image],
                ),
            ],
        )

    @patch.object(curate_templates, "write_association_refs")
    @patch.object(curate_templates, "run_stats")
    @patch.object(curate_templates, "make_threshold_cuts")
    @patch.object(curate_templates, "Butler")
    def test_custom_filters_passed_to_threshold_cuts(
        self,
        butler_class,
        make_threshold_cuts_mock,
        run_stats_mock,
        write_association_refs_mock,
    ):
        read_butler = MagicMock()
        write_butler = MagicMock()

        butler_class.side_effect = [
            read_butler,
            write_butler,
        ]

        depth_ref = MagicMock()
        depth_ref.dataId = {"tract": 100}

        coadd = make_ref(100, 1, "g")
        n_image = make_ref(100, 1, "g")

        read_butler.query_datasets.side_effect = [
            [depth_ref],
            [coadd],
            [n_image],
        ]

        make_threshold_cuts_mock.return_value = (
            [coadd],
            [],
            [n_image],
        )

        write_butler.collections.register.return_value = True

        args = self.make_args()
        args.min_filter = [
            "custom_min_metric=5",
            "another_min_metric=2.5",
        ]
        args.max_filter = [
            "custom_max_metric=10",
        ]

        with patch.dict(
            os.environ,
            {"USER": "testuser"},
        ):
            curate_templates.run_curate(args)

        make_threshold_cuts_mock.assert_called_once_with(
            read_butler,
            [coadd],
            [n_image],
            [depth_ref],
            {
                "custom_min_metric": 5.0,
                "another_min_metric": 2.5,
            },
            {
                "custom_max_metric": 10.0,
            },
        )


class MemoryTestCase(lsst.utils.tests.MemoryTestCase):
    """Run file-level memory tests."""

    pass


def setup_module(module):
    """Initialize the LSST test environment."""
    lsst.utils.tests.init()


if __name__ == "__main__":
    lsst.utils.tests.init()
    unittest.main()

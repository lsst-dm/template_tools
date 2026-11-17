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

"""Tests for bin.src/make_curated_template_collection.py."""

import argparse
import importlib.util
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from astropy.table import Table

import lsst.utils.tests
from lsst.daf.butler import CollectionType


_SCRIPT = Path(__file__).parents[1] / "bin.src" / "make_curated_template_collection.py"
_SPEC = importlib.util.spec_from_file_location("make_curated_template_collection", _SCRIPT)
make_collection = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(make_collection)


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


def make_args(**overrides):
    """Construct arguments for ``run_make_collection`` tests."""
    values = {
        "src_repo": "/source/repo",
        "tag": "DM-12345",
        "release_num": "01",
        "dest_repo": "/dest/repo",
        "collections": ["input/collection"],
        "existing_collection": None,
        "where": None,
        "reject": "",
        "records": "/tmp/records.ecsv",
        "template_type": "template_coadd",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class ParserTestCase(lsst.utils.tests.TestCase):
    """Tests for command-line argument parsing."""

    def test_defaults(self):
        parser = make_collection._make_parser()

        args = parser.parse_args(
            [
                "/source/repo",
                "DM-12345",
                "01",
                "--collections",
                "collection/one",
                "collection/two",
            ]
        )

        self.assertEqual(args.src_repo, "/source/repo")
        self.assertEqual(args.tag, "DM-12345")
        self.assertEqual(args.release_num, "01")
        self.assertEqual(args.dest_repo, "embargo")
        self.assertEqual(args.collections, ["collection/one", "collection/two"])
        self.assertIsNone(args.existing_collection)
        self.assertIsNone(args.where)
        self.assertEqual(args.reject, "")
        self.assertIsNone(args.records)
        self.assertEqual(args.template_type, "template_coadd")

    def test_optional_arguments(self):
        parser = make_collection._make_parser()

        args = parser.parse_args(
            [
                "/source/repo",
                "DM-12345",
                "02",
                "--dest_repo",
                "/dest/repo",
                "--collections",
                "collection/new",
                "--existing_collection",
                "LSSTCam/templates/DM-11111/release_01/run",
                "LSSTCam/templates/DM-22222/release_01/run",
                "--where",
                "tract=100",
                "--reject",
                "reject.ecsv",
                "--records",
                "records.ecsv",
                "--template_type",
                "template_coadd",
            ]
        )

        self.assertEqual(args.dest_repo, "/dest/repo")
        self.assertEqual(args.collections, ["collection/new"])
        self.assertEqual(
            args.existing_collection,
            [
                "LSSTCam/templates/DM-11111/release_01/run",
                "LSSTCam/templates/DM-22222/release_01/run",
            ],
        )
        self.assertEqual(args.where, "tract=100")
        self.assertEqual(args.reject, "reject.ecsv")
        self.assertEqual(args.records, "records.ecsv")
        self.assertEqual(args.template_type, "template_coadd")


class MakeDataIdTestCase(lsst.utils.tests.TestCase):
    """Tests for ``make_data_id``."""

    def test_make_data_id(self):
        ref = make_ref(100, 42, "r")

        self.assertEqual(make_collection.make_data_id(ref), (100, 42, "r"))


class FilterRejectedRefsTestCase(lsst.utils.tests.TestCase):
    """Tests for manual rejection filtering."""

    def setUp(self):
        self.refs = [
            make_ref(100, 1, "g"),
            make_ref(100, 2, "g"),
            make_ref(101, 1, "r"),
        ]

    def test_filters_rejected_refs(self):
        reject_table = Table(
            rows=[(100, 2, "g"), (999, 99, "y")],
            names=("tract", "patch", "band"),
        )

        filtered = make_collection.filter_rejected_refs(self.refs, reject_table)

        self.assertEqual(filtered, [self.refs[0], self.refs[2]])

    def test_empty_reject_table(self):
        reject_table = Table(
            names=("tract", "patch", "band"),
            dtype=(int, int, str),
        )

        filtered = make_collection.filter_rejected_refs(self.refs, reject_table)

        self.assertEqual(filtered, self.refs)

    def test_missing_required_column_raises(self):
        reject_table = Table(
            rows=[(100, 1)],
            names=("tract", "patch"),
        )

        with self.assertRaisesRegex(RuntimeError, "missing required column"):
            make_collection.filter_rejected_refs(self.refs, reject_table)


class HandleDuplicatesTestCase(lsst.utils.tests.TestCase):
    """Tests for duplicate template handling."""

    def test_drops_existing_data_ids(self):
        read_butler = MagicMock()
        existing_ref = make_ref(100, 1, "g")
        read_butler.query_datasets.return_value = [existing_ref]
        duplicate = make_ref(100, 1, "g", run="new/run")
        unique = make_ref(100, 2, "g", run="new/run")

        result = make_collection.handle_duplicates(
            read_butler,
            ["existing/collection"],
            [duplicate, unique],
            "template_coadd",
        )

        self.assertEqual(result, [unique])
        read_butler.query_datasets.assert_called_once_with(
            "template_coadd",
            collections=["existing/collection"],
            find_first=True,
            limit=None,
        )

    def test_no_existing_duplicates(self):
        read_butler = MagicMock()
        read_butler.query_datasets.return_value = []
        refs = [make_ref(100, 1, "g"), make_ref(100, 2, "g")]

        result = make_collection.handle_duplicates(
            read_butler,
            ["existing/collection"],
            refs,
            "template_coadd",
        )

        self.assertEqual(result, refs)

    def test_duplicate_within_new_refs_raises(self):
        read_butler = MagicMock()
        read_butler.query_datasets.return_value = []
        refs = [
            make_ref(100, 1, "g", run="new/run/one"),
            make_ref(100, 1, "g", run="new/run/two"),
        ]

        with self.assertRaisesRegex(
            RuntimeError,
            r"Multiple new template_coadd datasets found for tract=100, patch=1, band=g",
        ):
            make_collection.handle_duplicates(
                read_butler,
                ["existing/collection"],
                refs,
                "template_coadd",
            )

    def test_checks_all_supported_template_types(self):
        """A data ID in either supported template type is a duplicate."""
        read_butler = MagicMock()
        existing_lsst = make_ref(100, 1, "g", run="existing/lsst")
        existing_decam = make_ref(100, 2, "r", run="existing/decam")
        read_butler.query_datasets.side_effect = [
            [existing_lsst],
            [existing_decam],
        ]
        duplicate_lsst = make_ref(100, 1, "g", run="new/run")
        duplicate_decam = make_ref(100, 2, "r", run="new/run")
        unique = make_ref(100, 3, "i", run="new/run")

        with patch.object(
            make_collection,
            "TEMPLATE_TYPES",
            ("template_coadd", "template_coadd_decam"),
        ):
            result = make_collection.handle_duplicates(
                read_butler,
                ["existing/collection"],
                [duplicate_lsst, duplicate_decam, unique],
                "template_coadd",
            )

        self.assertEqual(result, [unique])
        self.assertEqual(
            read_butler.query_datasets.call_args_list,
            [
                call(
                    "template_coadd",
                    collections=["existing/collection"],
                    find_first=True,
                    limit=None,
                ),
                call(
                    "template_coadd_decam",
                    collections=["existing/collection"],
                    find_first=True,
                    limit=None,
                ),
            ],
        )


class WriteIngestRecordsTestCase(lsst.utils.tests.TestCase):
    """Tests for creation of the ingest-files ECSV."""

    def test_write_ingest_records(self):
        read_butler = MagicMock()
        refs = [
            make_ref(100, 1, "g"),
            make_ref(101, 2, "r"),
        ]
        uri_one = MagicMock()
        uri_one.geturl.return_value = "file:///templates/one.fits"
        uri_two = MagicMock()
        uri_two.geturl.return_value = "file:///templates/two.fits"
        read_butler.getURI.side_effect = [uri_one, uri_two]

        with tempfile.TemporaryDirectory() as tmpdir:
            records_file = Path(tmpdir) / "records.ecsv"

            make_collection.write_ingest_records(
                read_butler,
                refs,
                str(records_file),
            )

            data = Table.read(records_file)

        self.assertEqual(data.colnames, ["filename", "band", "skymap", "tract", "patch"])
        self.assertEqual(len(data), 2)
        self.assertEqual(str(data[0]["filename"]), "file:///templates/one.fits")
        self.assertEqual(str(data[0]["band"]), "g")
        self.assertEqual(str(data[0]["skymap"]), "lsst_cells_v2")
        self.assertEqual(int(data[0]["tract"]), 100)
        self.assertEqual(int(data[0]["patch"]), 1)
        self.assertEqual(str(data[1]["filename"]), "file:///templates/two.fits")
        self.assertEqual(int(data[1]["tract"]), 101)
        self.assertEqual(int(data[1]["patch"]), 2)
        self.assertEqual(read_butler.getURI.call_args_list, [call(refs[0]), call(refs[1])])


class CopyTemplatesTestCase(lsst.utils.tests.TestCase):
    """Tests for copying templates with ``ingest_files``."""

    @patch.object(make_collection, "ingest_files")
    def test_copy_templates(self, ingest_files_mock):
        run_collection = make_collection.copy_templates(
            "LSSTCam/templates/DM-12345/release_01",
            "/dest/repo",
            "records.ecsv",
            "template_coadd",
        )

        self.assertEqual(
            run_collection,
            "LSSTCam/templates/DM-12345/release_01/run",
        )
        ingest_files_mock.assert_called_once_with(
            "/dest/repo",
            "template_coadd",
            "LSSTCam/templates/DM-12345/release_01/run",
            table_file="records.ecsv",
            transfer="copy",
        )


class AssociateTemplatesTestCase(lsst.utils.tests.TestCase):
    """Tests for associating copied templates with the tagged collection."""

    def test_associate_templates(self):
        write_butler = MagicMock()
        refs = [make_ref(100, 1, "g"), make_ref(100, 2, "r")]
        write_butler.query_datasets.return_value = refs

        make_collection.associate_templates(
            write_butler,
            "LSSTCam/templates/DM-12345/release_01/run",
            "LSSTCam/templates/DM-12345/release_01",
            "template_coadd",
            2,
        )

        write_butler.query_datasets.assert_called_once_with(
            "template_coadd",
            collections="LSSTCam/templates/DM-12345/release_01/run",
            limit=None,
        )
        write_butler.registry.associate.assert_called_once_with(
            "LSSTCam/templates/DM-12345/release_01",
            refs,
        )

    def test_count_mismatch_raises_before_association(self):
        write_butler = MagicMock()
        write_butler.query_datasets.return_value = [make_ref(100, 1, "g")]

        with self.assertRaisesRegex(
            RuntimeError,
            r"Expected 2 template_coadd datasets.*but found 1",
        ):
            make_collection.associate_templates(
                write_butler,
                "LSSTCam/templates/DM-12345/release_01/run",
                "LSSTCam/templates/DM-12345/release_01",
                "template_coadd",
                2,
            )

        write_butler.registry.associate.assert_not_called()


class RunMakeCollectionTestCase(lsst.utils.tests.TestCase):
    """Tests for the top-level collection creation workflow."""

    def setUp(self):
        self.read_butler = MagicMock()
        self.write_butler = MagicMock()
        self.refs = [
            make_ref(100, 1, "g"),
            make_ref(100, 2, "r"),
        ]
        self.read_butler.query_datasets.return_value = self.refs
        self.write_butler.collections.register.return_value = True

    def _butler_side_effect(self, repo, writeable=False):
        if writeable:
            self.assertEqual(repo, "/dest/repo")
            return self.write_butler
        self.assertEqual(repo, "/source/repo")
        return self.read_butler

    @patch.object(make_collection, "associate_templates")
    @patch.object(make_collection, "copy_templates")
    @patch.object(make_collection, "write_ingest_records")
    @patch.object(make_collection, "Butler")
    def test_run_make_collection(
        self,
        butler_mock,
        write_ingest_records_mock,
        copy_templates_mock,
        associate_templates_mock,
    ):
        butler_mock.side_effect = self._butler_side_effect
        copy_templates_mock.return_value = "LSSTCam/templates/DM-12345/release_01/run"
        args = make_args()

        make_collection.run_make_collection(args)

        self.read_butler.query_datasets.assert_called_once_with(
            "template_coadd",
            collections=["input/collection"],
            where=None,
            limit=None,
        )
        write_ingest_records_mock.assert_called_once_with(
            self.read_butler,
            self.refs,
            "/tmp/records.ecsv",
        )
        self.write_butler.collections.register.assert_called_once_with(
            "LSSTCam/templates/DM-12345/release_01",
            type=CollectionType.TAGGED,
        )
        copy_templates_mock.assert_called_once_with(
            "LSSTCam/templates/DM-12345/release_01",
            "/dest/repo",
            "/tmp/records.ecsv",
            "template_coadd",
        )
        associate_templates_mock.assert_called_once_with(
            self.write_butler,
            "LSSTCam/templates/DM-12345/release_01/run",
            "LSSTCam/templates/DM-12345/release_01",
            "template_coadd",
            2,
        )

    @patch.object(make_collection, "associate_templates")
    @patch.object(make_collection, "copy_templates")
    @patch.object(make_collection, "write_ingest_records")
    @patch.object(make_collection, "handle_duplicates")
    @patch.object(make_collection, "filter_rejected_refs")
    @patch.object(make_collection.Table, "read")
    @patch.object(make_collection, "Butler")
    def test_rejection_and_duplicate_filters_are_applied(
        self,
        butler_mock,
        table_read_mock,
        filter_rejected_refs_mock,
        handle_duplicates_mock,
        write_ingest_records_mock,
        copy_templates_mock,
        associate_templates_mock,
    ):
        butler_mock.side_effect = self._butler_side_effect
        reject_table = MagicMock()
        table_read_mock.return_value = reject_table
        after_rejection = [self.refs[0]]
        final_refs = [self.refs[0]]
        filter_rejected_refs_mock.return_value = after_rejection
        handle_duplicates_mock.return_value = final_refs
        copy_templates_mock.return_value = "LSSTCam/templates/DM-12345/release_01/run"
        args = make_args(
            reject="reject.ecsv",
            existing_collection=["LSSTCam/templates"],
        )

        make_collection.run_make_collection(args)

        table_read_mock.assert_called_once_with("reject.ecsv")
        filter_rejected_refs_mock.assert_called_once_with(self.refs, reject_table)
        handle_duplicates_mock.assert_called_once_with(
            self.read_butler,
            ["LSSTCam/templates"],
            after_rejection,
            "template_coadd",
        )
        write_ingest_records_mock.assert_called_once_with(
            self.read_butler,
            final_refs,
            "/tmp/records.ecsv",
        )
        associate_templates_mock.assert_called_once_with(
            self.write_butler,
            "LSSTCam/templates/DM-12345/release_01/run",
            "LSSTCam/templates/DM-12345/release_01",
            "template_coadd",
            1,
        )

    @patch.object(make_collection, "Butler")
    def test_no_input_refs_raises(self, butler_mock):
        butler_mock.side_effect = self._butler_side_effect
        self.read_butler.query_datasets.return_value = []

        with self.assertRaisesRegex(
            RuntimeError,
            "No template_coadd datasets found in the input collections",
        ):
            make_collection.run_make_collection(make_args())

        self.write_butler.collections.register.assert_not_called()

    @patch.object(make_collection, "write_ingest_records")
    @patch.object(make_collection, "filter_rejected_refs")
    @patch.object(make_collection.Table, "read")
    @patch.object(make_collection, "Butler")
    def test_no_refs_after_filtering_raises(
        self,
        butler_mock,
        table_read_mock,
        filter_rejected_refs_mock,
        write_ingest_records_mock,
    ):
        butler_mock.side_effect = self._butler_side_effect
        table_read_mock.return_value = MagicMock()
        filter_rejected_refs_mock.return_value = []

        with self.assertRaisesRegex(
            RuntimeError,
            "No template_coadd remain after filtering",
        ):
            make_collection.run_make_collection(make_args(reject="reject.ecsv"))

        write_ingest_records_mock.assert_not_called()
        self.write_butler.collections.register.assert_not_called()

    @patch.object(make_collection, "associate_templates")
    @patch.object(make_collection, "copy_templates")
    @patch.object(make_collection, "write_ingest_records")
    @patch.object(make_collection, "Butler")
    def test_existing_output_collection_raises(
        self,
        butler_mock,
        write_ingest_records_mock,
        copy_templates_mock,
        associate_templates_mock,
    ):
        butler_mock.side_effect = self._butler_side_effect
        self.write_butler.collections.register.return_value = False

        with self.assertRaisesRegex(
            RuntimeError,
            r"Collection LSSTCam/templates/DM-12345/release_01 already exists",
        ):
            make_collection.run_make_collection(make_args())

        # The records file is intentionally produced before the destination
        # collection is registered.
        write_ingest_records_mock.assert_called_once_with(
            self.read_butler,
            self.refs,
            "/tmp/records.ecsv",
        )
        copy_templates_mock.assert_not_called()
        associate_templates_mock.assert_not_called()

    @patch.object(make_collection, "associate_templates")
    @patch.object(make_collection, "copy_templates")
    @patch.object(make_collection, "write_ingest_records")
    @patch.object(make_collection, "Butler")
    def test_default_records_filename(
        self,
        butler_mock,
        write_ingest_records_mock,
        copy_templates_mock,
        associate_templates_mock,
    ):
        butler_mock.side_effect = self._butler_side_effect
        copy_templates_mock.return_value = "LSSTCam/templates/DM-12345/release_01/run"

        make_collection.run_make_collection(make_args(records=None))

        write_ingest_records_mock.assert_called_once_with(
            self.read_butler,
            self.refs,
            "DM-12345_01_records.ecsv",
        )
        copy_templates_mock.assert_called_once_with(
            "LSSTCam/templates/DM-12345/release_01",
            "/dest/repo",
            "DM-12345_01_records.ecsv",
            "template_coadd",
        )


class MemoryTestCase(lsst.utils.tests.MemoryTestCase):
    """Check for file descriptor and memory leaks."""


if __name__ == "__main__":
    lsst.utils.tests.init()
    import unittest

    unittest.main()

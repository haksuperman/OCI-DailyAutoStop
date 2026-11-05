from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.compartments import load_exception_entries, list_subtree_compartments, resolve_exception_compartments
from app.config import (
    AppSettings,
    ExecutionSettings,
    LoggingSettings,
    OciSettings,
    RetrySettings,
    ScopeSettings,
)


def _settings(exception_file: Path) -> AppSettings:
    return AppSettings(
        oci=OciSettings(Path("/tmp/config"), "DEFAULT", None, [], []),
        scope=ScopeSettings("prod", None, False, exception_file),
        execution=ExecutionSettings(True, 1, 0, 1, 30, 5),
        retry=RetrySettings(1, 1.0, 1.0),
        logging=LoggingSettings(Path("/tmp/logs"), "INFO", Path("/tmp/logs/summary"), 1),
    )


class LoadExceptionEntriesTest(unittest.TestCase):
    def test_comments_and_blank_lines_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "exceptions.txt"
            path.write_text(
                "\n".join(
                    [
                        "# comment",
                        "",
                        "finance-shared",
                        "  ",
                        "example-compartment-ocid",
                    ]
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                load_exception_entries(path),
                ["finance-shared", "example-compartment-ocid"],
            )


class ListSubtreeCompartmentsTest(unittest.TestCase):
    @patch("app.compartments.list_call_get_all_results")
    def test_non_tenancy_root_is_walked_recursively(self, list_call_get_all_results_mock) -> None:
        list_call_get_all_results_mock.side_effect = [
            SimpleNamespace(
                data=[
                    SimpleNamespace(id="child-a", name="child-a", compartment_id="root-compartment"),
                    SimpleNamespace(id="child-b", name="child-b", compartment_id="root-compartment"),
                ]
            ),
            SimpleNamespace(
                data=[
                    SimpleNamespace(id="grandchild-a1", name="grandchild-a1", compartment_id="child-a"),
                ]
            ),
            SimpleNamespace(data=[]),
            SimpleNamespace(data=[]),
        ]

        result = list_subtree_compartments(
            identity_client=SimpleNamespace(list_compartments=object()),
            root_id="root-compartment",
            tenancy_ocid="tenancy-ocid",
            retry_settings=RetrySettings(1, 1.0, 1.0),
            logger=SimpleNamespace(warning=lambda *args, **kwargs: None),
        )

        self.assertEqual(
            [(item.id, item.parent_id) for item in result],
            [
                ("child-a", "root-compartment"),
                ("child-b", "root-compartment"),
                ("grandchild-a1", "child-a"),
            ],
        )

    @patch("app.compartments.list_call_get_all_results")
    def test_tenancy_root_uses_subtree_query(self, list_call_get_all_results_mock) -> None:
        list_call_get_all_results_mock.return_value = SimpleNamespace(
            data=[
                SimpleNamespace(id="tenancy-ocid", name="root", compartment_id=None),
                SimpleNamespace(id="child-a", name="child-a", compartment_id="tenancy-ocid"),
            ]
        )

        result = list_subtree_compartments(
            identity_client=SimpleNamespace(list_compartments=object()),
            root_id="tenancy-ocid",
            tenancy_ocid="tenancy-ocid",
            retry_settings=RetrySettings(1, 1.0, 1.0),
            logger=SimpleNamespace(warning=lambda *args, **kwargs: None),
        )

        self.assertEqual([(item.id, item.parent_id) for item in result], [("child-a", "tenancy-ocid")])
        _, kwargs = list_call_get_all_results_mock.call_args
        self.assertTrue(kwargs["compartment_id_in_subtree"])


class ResolveExceptionCompartmentsTest(unittest.TestCase):
    deleted_ocid = "ocid1.compartment.oc1..deleted"
    unknown_ocid = "ocid1.compartment.oc1..unknown"

    def _exception_file(self, temp_dir: str, entry: str) -> Path:
        path = Path(temp_dir) / "exceptions.txt"
        path.write_text(entry, encoding="utf-8")
        return path

    @patch("app.compartments.list_subtree_compartments")
    @patch("app.compartments.list_call_get_all_results")
    def test_deleted_ocid_is_warned_and_skipped(self, list_all_mock, list_subtree_mock) -> None:
        list_all_mock.return_value = SimpleNamespace(
            data=[SimpleNamespace(id=self.deleted_ocid)]
        )
        identity_client = SimpleNamespace(list_compartments=object(), get_compartment=MagicMock())

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertLogs("test.compartments", logging.WARNING) as captured:
                result = resolve_exception_compartments(
                    identity_client,
                    "tenancy-ocid",
                    _settings(self._exception_file(temp_dir, self.deleted_ocid)),
                    logging.getLogger("test.compartments"),
                    {},
                )

        self.assertEqual(result, set())
        self.assertIn(self.deleted_ocid, captured.output[0])
        identity_client.get_compartment.assert_not_called()
        list_subtree_mock.assert_not_called()
        self.assertEqual(list_all_mock.call_args.kwargs["lifecycle_state"], "DELETED")

    @patch("app.compartments.list_call_get_all_results")
    def test_deleted_lookup_error_fails_closed(self, list_all_mock) -> None:
        list_all_mock.side_effect = PermissionError("not authorized")

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(PermissionError, "not authorized"):
                resolve_exception_compartments(
                    SimpleNamespace(list_compartments=object()),
                    "tenancy-ocid",
                    _settings(self._exception_file(temp_dir, self.unknown_ocid)),
                    logging.getLogger("test.compartments"),
                    {},
                )

    @patch("app.compartments.list_call_get_all_results")
    def test_unknown_ocid_still_uses_existing_resolution_and_fails(self, list_all_mock) -> None:
        list_all_mock.return_value = SimpleNamespace(data=[])
        expected = LookupError("not authorized or not found")
        identity_client = SimpleNamespace(
            list_compartments=object(),
            get_compartment=MagicMock(side_effect=expected),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(LookupError, "not authorized or not found"):
                resolve_exception_compartments(
                    identity_client,
                    "tenancy-ocid",
                    _settings(self._exception_file(temp_dir, self.unknown_ocid)),
                    logging.getLogger("test.compartments"),
                    {},
                )

    @patch("app.compartments.list_call_get_all_results")
    def test_deleting_ocid_fails_closed(self, list_all_mock) -> None:
        list_all_mock.return_value = SimpleNamespace(data=[])
        identity_client = SimpleNamespace(
            list_compartments=object(),
            get_compartment=MagicMock(
                return_value=SimpleNamespace(
                    data=SimpleNamespace(
                        id=self.unknown_ocid,
                        name="being-deleted",
                        compartment_id="tenancy-ocid",
                        lifecycle_state="DELETING",
                    )
                )
            ),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "lifecycle_state=DELETING"):
                resolve_exception_compartments(
                    identity_client,
                    "tenancy-ocid",
                    _settings(self._exception_file(temp_dir, self.unknown_ocid)),
                    logging.getLogger("test.compartments"),
                    {},
                )

    @patch("app.compartments.list_subtree_compartments", return_value=[])
    @patch("app.compartments.list_call_get_all_results")
    def test_active_ocid_outside_current_scope_is_still_excluded(self, list_all_mock, _list_subtree_mock) -> None:
        list_all_mock.return_value = SimpleNamespace(data=[])
        identity_client = SimpleNamespace(
            list_compartments=object(),
            get_compartment=MagicMock(
                return_value=SimpleNamespace(
                    data=SimpleNamespace(
                        id=self.unknown_ocid,
                        name="active",
                        compartment_id="tenancy-ocid",
                        lifecycle_state="ACTIVE",
                    )
                )
            ),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            result = resolve_exception_compartments(
                identity_client,
                "tenancy-ocid",
                _settings(self._exception_file(temp_dir, self.unknown_ocid)),
                logging.getLogger("test.compartments"),
                {},
            )

        self.assertEqual(result, {self.unknown_ocid})


if __name__ == "__main__":
    unittest.main()


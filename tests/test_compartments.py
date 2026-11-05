from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.compartments import load_exception_entries, list_subtree_compartments, resolve_exception_compartments
from app.config import (
    AppSettings,
    ExecutionSettings,
    LoggingSettings,
    OciSettings,
    RetrySettings,
    ScopeSettings,
)
from app.models import CompartmentInfo


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
    active_ocid = "ocid1.compartment.oc1..active"
    missing_ocid = "ocid1.compartment.oc1..missing"

    def _exception_file(self, temp_dir: str, entry: str) -> Path:
        path = Path(temp_dir) / "exceptions.txt"
        path.write_text(entry, encoding="utf-8")
        return path

    def test_missing_ocid_is_warned_and_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertLogs("test.compartments", logging.WARNING) as captured:
                result = resolve_exception_compartments(
                    object(),
                    "tenancy-ocid",
                    _settings(self._exception_file(temp_dir, self.missing_ocid)),
                    logging.getLogger("test.compartments"),
                    {},
                )

        self.assertEqual(result, set())
        self.assertIn(self.missing_ocid, captured.output[0])

    def test_active_ocid_and_descendants_are_excluded_from_current_scope(self) -> None:
        child_ocid = "ocid1.compartment.oc1..child"
        grandchild_ocid = "ocid1.compartment.oc1..grandchild"
        current_scope = {
            self.active_ocid: CompartmentInfo(self.active_ocid, "active", "tenancy-ocid"),
            child_ocid: CompartmentInfo(child_ocid, "child", self.active_ocid),
            grandchild_ocid: CompartmentInfo(grandchild_ocid, "grandchild", child_ocid),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            result = resolve_exception_compartments(
                object(),
                "tenancy-ocid",
                _settings(self._exception_file(temp_dir, self.active_ocid)),
                logging.getLogger("test.compartments"),
                current_scope,
            )

        self.assertEqual(result, {self.active_ocid, child_ocid, grandchild_ocid})

    def test_unique_name_is_resolved_from_current_scope(self) -> None:
        current_scope = {
            self.active_ocid: CompartmentInfo(self.active_ocid, "finance", "tenancy-ocid")
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            result = resolve_exception_compartments(
                object(),
                "tenancy-ocid",
                _settings(self._exception_file(temp_dir, "finance")),
                logging.getLogger("test.compartments"),
                current_scope,
            )

        self.assertEqual(result, {self.active_ocid})

    def test_missing_name_is_warned_and_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertLogs("test.compartments", logging.WARNING) as captured:
                result = resolve_exception_compartments(
                    object(),
                    "tenancy-ocid",
                    _settings(self._exception_file(temp_dir, "missing-name")),
                    logging.getLogger("test.compartments"),
                    {},
                )

        self.assertEqual(result, set())
        self.assertIn("missing-name", captured.output[0])

    def test_ambiguous_name_still_fails_closed(self) -> None:
        current_scope = {
            "compartment-a": CompartmentInfo("compartment-a", "shared", "tenancy-ocid"),
            "compartment-b": CompartmentInfo("compartment-b", "shared", "tenancy-ocid"),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                resolve_exception_compartments(
                    object(),
                    "tenancy-ocid",
                    _settings(self._exception_file(temp_dir, "shared")),
                    logging.getLogger("test.compartments"),
                    current_scope,
                )


if __name__ == "__main__":
    unittest.main()


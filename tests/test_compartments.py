from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.compartments import load_exception_entries, list_subtree_compartments
from app.config import RetrySettings


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


if __name__ == "__main__":
    unittest.main()

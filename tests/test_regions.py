from __future__ import annotations

import logging
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.config import AppSettings, ExecutionSettings, LoggingSettings, OciSettings, RetrySettings, ScopeSettings
from app.oci_clients import resolve_execution_regions


def _settings(mode: str, regions: list[str], excluded_regions: list[str] | None = None) -> AppSettings:
    return AppSettings(
        oci=OciSettings(
            config_file=Path("/tmp/config"),
            profile="DEFAULT",
            tenancy_ocid=None,
            regions=regions,
            excluded_regions=excluded_regions or [],
        ),
        scope=ScopeSettings(
            mode=mode,
            dev_base_compartment_name_or_ocid="dev-base",
            include_root_resources=False,
            exception_file=Path("/tmp/exceptions.txt"),
        ),
        execution=ExecutionSettings(
            default_dry_run=True,
            max_workers=4,
            post_check_delay_seconds=10,
            post_check_max_workers=4,
            stop_wait_timeout_seconds=900,
            stop_wait_interval_seconds=20,
        ),
        retry=RetrySettings(
            max_attempts=4,
            base_delay_seconds=1.0,
            max_delay_seconds=16.0,
        ),
        logging=LoggingSettings(
            directory=Path("/tmp/logs"),
            level="INFO",
            summary_directory=Path("/tmp/logs/summary"),
            backup_count=30,
        ),
    )


def _logger() -> logging.Logger:
    logger = logging.getLogger("test.regions")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


class ResolveExecutionRegionsTest(unittest.TestCase):
    def test_dev_uses_configured_regions_after_exclusions(self) -> None:
        settings = _settings("dev", ["ap-seoul-1", "ap-tokyo-1"], ["ap-tokyo-1"])

        resolution = resolve_execution_regions(settings, {"region": "ap-seoul-1"}, "ocid1.tenancy.oc1..example", _logger())

        self.assertEqual(resolution.regions, ["ap-seoul-1"])
        self.assertIn("region source: configured", resolution.notes)
        self.assertIn("excluded regions: ap-tokyo-1", resolution.notes)

    @patch("app.oci_clients.list_subscribed_regions")
    @patch("app.oci_clients.build_clients")
    def test_prod_uses_subscribed_regions_after_exclusions(self, build_clients_mock, list_subscribed_regions_mock) -> None:
        settings = _settings("prod", ["ap-seoul-1"], ["us-ashburn-1"])
        build_clients_mock.return_value = SimpleNamespace(identity=object())
        list_subscribed_regions_mock.return_value = ["ap-seoul-1", "us-ashburn-1", "uk-london-1"]

        resolution = resolve_execution_regions(settings, {"region": "ap-seoul-1"}, "ocid1.tenancy.oc1..example", _logger())

        self.assertEqual(resolution.regions, ["ap-seoul-1", "uk-london-1"])
        self.assertIn("region source: subscribed", resolution.notes)
        self.assertIn("excluded regions: us-ashburn-1", resolution.notes)

    @patch("app.oci_clients.list_subscribed_regions")
    @patch("app.oci_clients.build_clients")
    def test_prod_falls_back_to_configured_regions_when_discovery_fails(self, build_clients_mock, list_subscribed_regions_mock) -> None:
        settings = _settings("prod", ["ap-seoul-1", "ap-tokyo-1"], ["ap-tokyo-1"])
        build_clients_mock.return_value = SimpleNamespace(identity=object())
        list_subscribed_regions_mock.side_effect = RuntimeError("permission denied")

        resolution = resolve_execution_regions(settings, {"region": "ap-seoul-1"}, "ocid1.tenancy.oc1..example", _logger())

        self.assertEqual(resolution.regions, ["ap-seoul-1"])
        self.assertTrue(resolution.notes[0].startswith("prod region auto-discovery failed; fallback configured regions used:"))
        self.assertIn("region source: fallback_configured", resolution.notes)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import logging
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.config import AppSettings, ExecutionSettings, LoggingSettings, OciSettings, RetrySettings, ScopeSettings
from app.models import CompartmentInfo
from app.resources import handle_mysql_heatwave_db_systems


def _settings() -> AppSettings:
    return AppSettings(
        oci=OciSettings(
            config_file=Path("/tmp/config"),
            profile="DEFAULT",
            tenancy_ocid=None,
            regions=["ap-seoul-1"],
            excluded_regions=[],
        ),
        scope=ScopeSettings(
            mode="prod",
            dev_base_compartment_name_or_ocid=None,
            include_root_resources=False,
            exception_file=Path("/tmp/exceptions.txt"),
        ),
        execution=ExecutionSettings(
            default_dry_run=True,
            max_workers=1,
            post_check_delay_seconds=10,
            post_check_max_workers=1,
            stop_wait_timeout_seconds=900,
            stop_wait_interval_seconds=20,
        ),
        retry=RetrySettings(
            max_attempts=1,
            base_delay_seconds=1.0,
            max_delay_seconds=1.0,
        ),
        logging=LoggingSettings(
            directory=Path("/tmp/logs"),
            level="INFO",
            summary_directory=Path("/tmp/logs/summary"),
            backup_count=30,
        ),
    )


def _mysql_db_system(resource_id: str, display_name: str, lifecycle_state: str) -> SimpleNamespace:
    return SimpleNamespace(id=resource_id, display_name=display_name, lifecycle_state=lifecycle_state)


class MySqlHeatWaveResourceTest(unittest.TestCase):
    @patch("app.resources.list_call_get_all_results")
    def test_mysql_statuses_are_bucketed_consistently(self, list_call_get_all_results_mock) -> None:
        clients = SimpleNamespace(mysql=SimpleNamespace(list_db_systems=object(), stop_db_system=MagicMock()))
        compartment = CompartmentInfo(id="comp-a", name="alpha", parent_id="root")
        list_call_get_all_results_mock.return_value = SimpleNamespace(
            data=[
                _mysql_db_system("mysql-active", "mysql-active", "ACTIVE"),
                _mysql_db_system("mysql-inactive", "mysql-inactive", "INACTIVE"),
                _mysql_db_system("mysql-creating", "mysql-creating", "CREATING"),
                _mysql_db_system("mysql-updating", "mysql-updating", "UPDATING"),
                _mysql_db_system("mysql-deleting", "mysql-deleting", "DELETING"),
                _mysql_db_system("mysql-deleted", "mysql-deleted", "DELETED"),
                _mysql_db_system("mysql-failed", "mysql-failed", "FAILED"),
            ]
        )

        results = handle_mysql_heatwave_db_systems(
            clients,
            "ap-seoul-1",
            compartment,
            _settings(),
            True,
            logging.getLogger("test.resources.mysql"),
        )

        self.assertEqual(
            [(result.resource.resource_name, result.status) for result in results],
            [
                ("mysql-active", "dry_run"),
                ("mysql-inactive", "already_stopped"),
                ("mysql-creating", "transition"),
                ("mysql-updating", "transition"),
                ("mysql-deleting", "transition"),
                ("mysql-failed", "already_stopped"),
            ],
        )

    @patch("app.resources.list_call_get_all_results")
    def test_mysql_active_stop_uses_fast_shutdown(self, list_call_get_all_results_mock) -> None:
        stop_db_system_mock = MagicMock()
        clients = SimpleNamespace(mysql=SimpleNamespace(list_db_systems=object(), stop_db_system=stop_db_system_mock))
        compartment = CompartmentInfo(id="comp-a", name="alpha", parent_id="root")
        list_call_get_all_results_mock.return_value = SimpleNamespace(
            data=[_mysql_db_system("mysql-active", "mysql-active", "ACTIVE")]
        )

        results = handle_mysql_heatwave_db_systems(
            clients,
            "ap-seoul-1",
            compartment,
            _settings(),
            False,
            logging.getLogger("test.resources.mysql"),
        )

        self.assertEqual(results[0].status, "requested")
        stop_db_system_mock.assert_called_once()
        resource_id, stop_details = stop_db_system_mock.call_args.args
        self.assertEqual(resource_id, "mysql-active")
        self.assertEqual(stop_details.shutdown_type, "FAST")


if __name__ == "__main__":
    unittest.main()

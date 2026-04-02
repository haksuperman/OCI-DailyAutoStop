from __future__ import annotations

import logging
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.config import AppSettings, ExecutionSettings, LoggingSettings, OciSettings, RetrySettings, ScopeSettings
from app.models import ActionResult, CompartmentInfo, ResourceRecord, Summary
from app.service import BufferedLogRecord, RegionJobResult, _run_compartment_job, run_autostop


def _settings(max_workers: int = 4) -> AppSettings:
    return AppSettings(
        oci=OciSettings(
            config_file=Path("/tmp/config"),
            profile="DEFAULT",
            tenancy_ocid=None,
            regions=["ap-seoul-1", "ap-tokyo-1"],
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
            max_workers=max_workers,
            post_check_delay_seconds=10,
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


def _resource(region: str) -> ResourceRecord:
    return ResourceRecord(
        resource_type="compute",
        region=region,
        compartment_id="ocid1.compartment.oc1..example",
        compartment_name="alpha",
        resource_id=f"ocid1.instance.oc1..{region}",
        resource_name=f"vm-{region}",
        lifecycle_state="RUNNING",
    )


class ServiceTest(unittest.TestCase):
    @patch("app.service.ThreadPoolExecutor")
    @patch("app.service._run_region_job")
    def test_run_compartment_job_uses_configured_max_workers(self, run_region_job_mock, executor_cls_mock) -> None:
        settings = _settings(max_workers=2)
        compartment = CompartmentInfo(id="comp-a", name="alpha", parent_id="root")

        future_seoul = MagicMock()
        future_seoul.result.return_value = RegionJobResult(region="ap-seoul-1")
        future_tokyo = MagicMock()
        future_tokyo.result.return_value = RegionJobResult(region="ap-tokyo-1")
        executor_mock = MagicMock()
        executor_mock.submit.side_effect = [future_seoul, future_tokyo]
        executor_cls_mock.return_value.__enter__.return_value = executor_mock

        results = _run_compartment_job(
            {"region": "ap-seoul-1"},
            ["ap-seoul-1", "ap-tokyo-1"],
            compartment,
            settings,
            True,
        )

        executor_cls_mock.assert_called_once_with(max_workers=2)
        self.assertEqual([result.region for result in results], ["ap-seoul-1", "ap-tokyo-1"])

    @patch("app.service.build_summary_lines", return_value=["Summary Details"])
    @patch("app.service.build_completion_lines", return_value=["============================================================", "Done"])
    @patch("app.service._verify_requested_stops")
    @patch("app.service._run_compartment_job")
    @patch("app.service.build_target_compartments")
    @patch("app.service.build_clients")
    def test_run_autostop_keeps_logs_grouped_by_compartment(
        self,
        build_clients_mock,
        build_target_compartments_mock,
        run_compartment_job_mock,
        verify_requested_stops_mock,
        build_completion_lines_mock,
        build_summary_lines_mock,
    ) -> None:
        settings = _settings(max_workers=4)
        compartments = [
            CompartmentInfo(id="comp-a", name="alpha", parent_id="root"),
            CompartmentInfo(id="comp-b", name="beta", parent_id="root"),
        ]
        build_target_compartments_mock.return_value = compartments
        build_clients_mock.return_value = object()
        run_compartment_job_mock.side_effect = [
            [
                RegionJobResult(
                    region="ap-seoul-1",
                    logs=[BufferedLogRecord(logging.WARNING, "alpha warning")],
                    results=[ActionResult(_resource("ap-seoul-1"), "already_stopped", "Already stopped: STOPPED")],
                )
            ],
            [
                RegionJobResult(
                    region="ap-tokyo-1",
                    logs=[BufferedLogRecord(logging.WARNING, "beta warning")],
                    results=[ActionResult(_resource("ap-tokyo-1"), "already_stopped", "Already stopped: STOPPED")],
                )
            ],
        ]

        logger = logging.getLogger("app.service")
        logger.handlers.clear()
        logger.propagate = False
        handler = _ListHandler()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        run_autostop(settings, {"region": "ap-seoul-1"}, "ocid1.tenancy.oc1..example", True, ["ap-seoul-1"])
        verify_requested_stops_mock.assert_not_called()

        messages = [record.getMessage() for record in handler.records]
        self.assertLess(messages.index("-> Compartment: alpha"), messages.index("alpha warning"))
        self.assertLess(messages.index("alpha warning"), messages.index("  [Instance] vm-ap-seoul-1 (ap-seoul-1) -> Already stopped (no action)"))
        self.assertLess(messages.index("  [Instance] vm-ap-seoul-1 (ap-seoul-1) -> Already stopped (no action)"), messages.index("-> Compartment: beta"))
        self.assertLess(messages.index("-> Compartment: beta"), messages.index("beta warning"))

    @patch("app.service.time.sleep")
    @patch("app.service.build_clients")
    def test_verify_requested_stops_updates_summary_with_final_status(self, build_clients_mock, sleep_mock) -> None:
        from types import SimpleNamespace

        from app.service import _verify_requested_stops

        settings = _settings(max_workers=1)
        summary = Summary()
        requested = ActionResult(_resource("ap-seoul-1"), "requested", "Stop request sent")
        summary.register(requested)
        build_clients_mock.return_value = SimpleNamespace(
            compute=SimpleNamespace(get_instance=lambda resource_id: SimpleNamespace(data=SimpleNamespace(lifecycle_state="STOPPED"))),
            database=SimpleNamespace(),
        )

        _verify_requested_stops(summary, [requested], settings, {"region": "ap-seoul-1"}, logging.getLogger("test.verify"))

        sleep_mock.assert_called_once_with(10)
        self.assertEqual(summary.verification["compute"].requested, 1)
        self.assertEqual(summary.verification["compute"].confirmed_stopped, 1)
        self.assertEqual(summary.success, 1)


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


if __name__ == "__main__":
    unittest.main()

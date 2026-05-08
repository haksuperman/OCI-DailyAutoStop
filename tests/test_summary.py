from __future__ import annotations

import unittest
from datetime import datetime

from app.models import ActionResult, ResourceRecord, Summary
from app.reporting import build_completion_lines, build_summary_lines


def _resource() -> ResourceRecord:
    return ResourceRecord(
        resource_type="instance",
        region="ap-seoul-1",
        compartment_id="example-compartment-ocid",
        compartment_name="dev-base",
        resource_id="example-instance-ocid",
        resource_name="vm-a",
        lifecycle_state="RUNNING",
    )


class SummaryTest(unittest.TestCase):
    def test_summary_counts_match_expected_buckets(self) -> None:
        summary = Summary()
        summary.register(ActionResult(_resource(), "already_stopped", "stopped"))
        summary.register(ActionResult(_resource(), "transition", "transition"))
        summary.register(ActionResult(_resource(), "dry_run", "dry-run"))
        summary.register(ActionResult(_resource(), "requested", "stopped"))
        summary.register(ActionResult(_resource(), "failed", "error"))

        self.assertEqual(summary.scanned, 5)
        self.assertEqual(summary.already_stopped, 1)
        self.assertEqual(summary.transition, 1)
        self.assertEqual(summary.stop_requested, 2)
        self.assertEqual(summary.success, 0)
        self.assertEqual(summary.dry_run, 1)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.verification["instance"].requested, 1)

        summary.register_verification("instance", True)
        self.assertEqual(summary.success, 1)

    def test_summary_render_includes_notes(self) -> None:
        summary = Summary()
        summary.add_note("region source: subscribed")

        rendered = summary.render()

        self.assertIn("- notes:", rendered)
        self.assertIn("region source: subscribed", rendered)

    def test_build_summary_lines_renders_readable_report(self) -> None:
        summary = Summary(
            started_at=datetime(2026, 3, 31, 15, 0, 0),
            completed_at=datetime(2026, 3, 31, 15, 5, 33),
            target_compartment_count=4,
            target_region_count=2,
        )
        summary.add_note("region source: configured")
        summary.register(ActionResult(_resource(), "already_stopped", "Already stopped: STOPPED"))
        summary.register(ActionResult(_resource(), "dry_run", "Dry-run stop request prepared"))

        rendered = "\n".join(
            build_summary_lines(
                "dev",
                summary,
                [
                    ActionResult(_resource(), "already_stopped", "Already stopped: STOPPED"),
                    ActionResult(_resource(), "dry_run", "Dry-run stop request prepared"),
                ],
                True,
                ["ap-seoul-1", "ap-tokyo-1"],
            )
        )

        self.assertNotIn("OCI Daily AutoStop Summary", rendered)
        self.assertNotIn(" - Target             : 4 compartment(s), 2 region(s)", rendered)
        self.assertIn("Summary Details", rendered)
        self.assertIn(" Instance(s) scanned : 2", rendered)
        self.assertIn("  ├─ Already stopped : 1", rendered)
        self.assertIn("  └─ Stop targets (Dry-run) : 1", rendered)
        self.assertIn("Dry-run completed (total duration: 5m 33s)", rendered)

    def test_build_summary_lines_uses_verified_stop_counts(self) -> None:
        summary = Summary(
            started_at=datetime(2026, 3, 31, 15, 0, 0),
            completed_at=datetime(2026, 3, 31, 15, 0, 5),
        )
        requested = ActionResult(_resource(), "requested", "Stop request sent")
        summary.register(requested)
        summary.register_verification("instance", True)

        rendered = "\n".join(build_summary_lines("prod", summary, [requested], False, ["ap-seoul-1"]))

        self.assertIn("  └─ Stop by AutoStop : 1 → 1 successful", rendered)

    def test_build_completion_lines_renders_stop_request_counts(self) -> None:
        rendered = "\n".join(
            build_completion_lines(
                [
                    ActionResult(_resource(), "requested", "Stop confirmed: STOPPED"),
                    ActionResult(_resource(), "failed", "error"),
                ],
                False,
            )
        )

        self.assertIn("============================================================", rendered)
        self.assertIn("Stop requests completed (1 Instance(s), 0 Oracle Base DB Node(s), 0 ADB(s), 0 MySQL HeatWave DB System(s)).", rendered)

    def test_build_completion_lines_renders_dry_run_counts(self) -> None:
        rendered = "\n".join(
            build_completion_lines(
                [
                    ActionResult(_resource(), "dry_run", "Dry-run stop request prepared"),
                    ActionResult(_resource(), "already_stopped", "Already stopped: STOPPED"),
                ],
                True,
            )
        )

        self.assertIn("Dry-run analysis completed (1 Instance(s), 0 Oracle Base DB Node(s), 0 ADB(s), 0 MySQL HeatWave DB System(s) matched).", rendered)


if __name__ == "__main__":
    unittest.main()

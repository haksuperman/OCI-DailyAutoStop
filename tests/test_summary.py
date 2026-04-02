from __future__ import annotations

import unittest

from app.models import ActionResult, ResourceRecord, Summary


def _resource() -> ResourceRecord:
    return ResourceRecord(
        resource_type="compute",
        region="ap-seoul-1",
        compartment_id="ocid1.compartment.oc1..example",
        compartment_name="dev-base",
        resource_id="ocid1.instance.oc1..example",
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
        self.assertEqual(summary.success, 1)
        self.assertEqual(summary.dry_run, 1)
        self.assertEqual(summary.failed, 1)


if __name__ == "__main__":
    unittest.main()

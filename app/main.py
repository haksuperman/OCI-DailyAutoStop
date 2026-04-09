from __future__ import annotations

import argparse
import logging
import sys

from app.config import load_settings
from app.logging_utils import configure_logging
from app.oci_clients import load_oci_config, resolve_execution_regions, validate_tenancy
from app.service import run_autostop


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OCI resource AutoStop application")
    parser.add_argument("--config", required=True, help="Path to settings YAML")
    parser.add_argument("--dry-run", action="store_true", help="Override settings and run without stop actions")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        settings = load_settings(args.config)
        log_file = configure_logging(settings.logging)
        logger = logging.getLogger("app.main")
        dry_run = args.dry_run or settings.execution.default_dry_run

        oci_config = load_oci_config(settings)
        tenancy_ocid = validate_tenancy(oci_config, logger)
        region_resolution = resolve_execution_regions(settings, oci_config, tenancy_ocid, logger)

        summary, results = run_autostop(settings, oci_config, tenancy_ocid, dry_run, region_resolution.regions)
        for note in region_resolution.notes:
            summary.add_note(note)
        logger.info("Execution log file %s", log_file)
        return 0
    except Exception as exc:
        logging.getLogger("app.main").exception("Application failed")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

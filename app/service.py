from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.compartments import build_target_compartments
from app.config import AppSettings
from app.models import ActionResult, Summary
from app.oci_clients import build_clients
from app.resources import process_compartment_resources


def run_autostop(settings: AppSettings, oci_config: dict[str, str], tenancy_ocid: str, dry_run: bool) -> tuple[Summary, list[ActionResult]]:
    logger = logging.getLogger("app.service")
    home_region = oci_config.get("region") or settings.oci.regions[0]
    scope_clients = build_clients(oci_config, home_region)

    compartments = build_target_compartments(scope_clients, tenancy_ocid, settings, logger)
    summary = Summary()
    results: list[ActionResult] = []

    with ThreadPoolExecutor(max_workers=settings.execution.max_workers) as executor:
        futures = []
        for region in settings.oci.regions:
            for compartment in compartments:
                futures.append(
                    executor.submit(
                        _run_compartment_job,
                        oci_config,
                        region,
                        compartment,
                        settings,
                        dry_run,
                    )
                )

        for future in as_completed(futures):
            try:
                batch = future.result()
            except Exception as exc:  # pragma: no cover
                logger.exception("Worker failed")
                summary.add_error(str(exc))
                continue
            for result in batch:
                results.append(result)
                summary.register(result)

    return summary, results


def _run_compartment_job(
    oci_config: dict[str, str],
    region: str,
    compartment,
    settings: AppSettings,
    dry_run: bool,
) -> list[ActionResult]:
    regional_clients = build_clients(oci_config, region)
    return process_compartment_resources(
        regional_clients,
        region,
        compartment,
        settings,
        dry_run,
        logging.getLogger(f"app.region.{region}"),
    )

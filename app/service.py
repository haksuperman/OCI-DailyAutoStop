from __future__ import annotations

from datetime import datetime
import logging

from app.compartments import build_target_compartments
from app.config import AppSettings
from app.models import ActionResult, Summary
from app.oci_clients import build_clients
from app.resources import process_compartment_resources
from app.reporting import build_summary_lines


def run_autostop(
    settings: AppSettings,
    oci_config: dict[str, str],
    tenancy_ocid: str,
    dry_run: bool,
    regions: list[str],
) -> tuple[Summary, list[ActionResult]]:
    logger = logging.getLogger("app.service")
    home_region = oci_config.get("region") or regions[0]
    scope_clients = build_clients(oci_config, home_region)

    compartments = build_target_compartments(scope_clients, tenancy_ocid, settings, logger)
    summary = Summary()
    summary.started_at = datetime.now()
    summary.target_compartment_count = len(compartments)
    summary.target_region_count = len(regions)
    results: list[ActionResult] = []

    for line in _build_start_banner(settings.scope.mode, dry_run, summary.target_compartment_count, len(regions), regions):
        _log_multiline(logger, line)
    logger.info("OCI Daily AutoStop starting...")

    for compartment in compartments:
        logger.info("-> Compartment: %s", compartment.name)
        compartment_started_at = datetime.now()
        try:
            batch = _run_compartment_job(
                oci_config,
                regions,
                compartment,
                settings,
                dry_run,
            )
        except Exception as exc:  # pragma: no cover
            logger.exception("Compartment job failed. compartment=%s", compartment.name)
            summary.add_error(f"{compartment.name}: {exc}")
            continue

        for result in batch:
            logger.info("  %s", _format_action_result(result, dry_run))
            results.append(result)
            summary.register(result)
        logger.info("  Completed in %s", _format_elapsed(compartment_started_at, datetime.now()))

    summary.completed_at = datetime.now()
    logger.info(_build_phase_completion_line(dry_run))
    for line in build_summary_lines(settings.scope.mode, summary, results, dry_run, regions):
        _log_multiline(logger, line)
    return summary, results


def _run_compartment_job(
    oci_config: dict[str, str],
    regions: list[str],
    compartment,
    settings: AppSettings,
    dry_run: bool,
) -> list[ActionResult]:
    batch: list[ActionResult] = []
    for region in regions:
        regional_clients = build_clients(oci_config, region)
        batch.extend(
            process_compartment_resources(
                regional_clients,
                region,
                compartment,
                settings,
                dry_run,
                logging.getLogger("app.service"),
            )
        )
    return batch


def _build_start_banner(
    mode: str,
    dry_run: bool,
    compartment_count: int,
    region_count: int,
    regions: list[str],
) -> list[str]:
    return [
        "=" * 60,
        "OCI Daily AutoStop (Instance, DB Node, ADB)",
        f" - Date               : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f" - Mode               : {mode}",
        f" - Dry Run            : {str(dry_run).lower()}",
        f" - Target             : {compartment_count} compartment(s), {region_count} region(s)",
        f" - Regions            : {', '.join(regions)}",
        "=" * 60,
    ]


def _log_multiline(logger: logging.Logger, message: str) -> None:
    for line in message.splitlines() or [""]:
        logger.info(line)


def _format_action_result(result: ActionResult, dry_run: bool) -> str:
    resource_labels = {
        "compute": "Instance",
        "db_node": "DB Node",
        "adb": "ADB",
    }
    status_messages = {
        "already_stopped": "Already stopped (no action)",
        "transition": "In transition",
        "dry_run": "Stop target (dry-run)",
        "requested": "Stop request sent",
        "stopped": "Stop completed",
        "failed": f"Failed: {result.message}",
    }
    message = status_messages.get(result.status, result.message)
    if result.status == "transition" and result.message:
        message = f"In transition ({result.message.removeprefix('Transition state: ')})"
    return f"[{resource_labels[result.resource.resource_type]}] {result.resource.resource_name} ({result.resource.region}) -> {message}"


def _format_elapsed(started_at: datetime, completed_at: datetime) -> str:
    total_seconds = max(0, int((completed_at - started_at).total_seconds()))
    minutes, seconds = divmod(total_seconds, 60)
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _build_phase_completion_line(dry_run: bool) -> str:
    if dry_run:
        return "Dry-run target analysis completed."
    return "Stop requests completed."

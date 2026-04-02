from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
import logging
import traceback

from app.compartments import build_target_compartments
from app.config import AppSettings
from app.models import ActionResult, Summary
from app.oci_clients import build_clients
from app.resources import process_compartment_resources
from app.reporting import build_completion_lines, build_summary_lines


@dataclass
class BufferedLogRecord:
    level: int
    message: str


@dataclass
class RegionJobResult:
    region: str
    results: list[ActionResult] = field(default_factory=list)
    logs: list[BufferedLogRecord] = field(default_factory=list)
    error: str | None = None


class BufferedWorkerLogger:
    def __init__(self) -> None:
        self.records: list[BufferedLogRecord] = []

    def info(self, message: str, *args, **kwargs) -> None:
        self._append(logging.INFO, message, *args)

    def warning(self, message: str, *args, **kwargs) -> None:
        self._append(logging.WARNING, message, *args)

    def error(self, message: str, *args, **kwargs) -> None:
        self._append(logging.ERROR, message, *args)

    def exception(self, message: str, *args, exc_info=True, **kwargs) -> None:
        self._append(logging.ERROR, message, *args)
        if exc_info:
            trace = traceback.format_exc().strip()
            if trace and trace != "NoneType: None":
                for line in trace.splitlines():
                    self.records.append(BufferedLogRecord(logging.ERROR, line))

    def _append(self, level: int, message: str, *args) -> None:
        if args:
            try:
                rendered = message % args
            except Exception:
                rendered = f"{message} {' '.join(str(arg) for arg in args)}".strip()
        else:
            rendered = message
        self.records.append(BufferedLogRecord(level, rendered))


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
        try:
            region_jobs = _run_compartment_job(
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

        for job in region_jobs:
            _flush_buffered_logs(logger, job.logs)
            if job.error:
                logger.error("  Region job failed. compartment=%s region=%s error=%s", compartment.name, job.region, job.error)
                summary.add_error(f"{compartment.name}/{job.region}: {job.error}")
                continue
            for result in job.results:
                logger.info("  %s", _format_action_result(result, dry_run))
                results.append(result)
                summary.register(result)

    summary.completed_at = datetime.now()
    for line in build_completion_lines(results, dry_run):
        _log_multiline(logger, line)
    for line in build_summary_lines(settings.scope.mode, summary, results, dry_run, regions):
        _log_multiline(logger, line)
    return summary, results


def _run_compartment_job(
    oci_config: dict[str, str],
    regions: list[str],
    compartment,
    settings: AppSettings,
    dry_run: bool,
) -> list[RegionJobResult]:
    if len(regions) <= 1 or settings.execution.max_workers <= 1:
        return [_run_region_job(oci_config, region, compartment, settings, dry_run) for region in regions]

    max_workers = min(settings.execution.max_workers, len(regions))
    futures = {}
    ordered_results: dict[str, RegionJobResult] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for region in regions:
            futures[region] = executor.submit(_run_region_job, oci_config, region, compartment, settings, dry_run)
        for region, future in futures.items():
            ordered_results[region] = future.result()
    return [ordered_results[region] for region in regions]


def _run_region_job(
    oci_config: dict[str, str],
    region: str,
    compartment,
    settings: AppSettings,
    dry_run: bool,
) -> RegionJobResult:
    worker_logger = BufferedWorkerLogger()
    try:
        regional_clients = build_clients(oci_config, region)
        results = process_compartment_resources(
            regional_clients,
            region,
            compartment,
            settings,
            dry_run,
            worker_logger,
        )
        return RegionJobResult(region=region, results=results, logs=worker_logger.records)
    except Exception as exc:  # pragma: no cover
        worker_logger.exception(
            "Region execution failed. compartment=%s region=%s",
            compartment.name,
            region,
        )
        return RegionJobResult(region=region, logs=worker_logger.records, error=str(exc))


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


def _flush_buffered_logs(logger: logging.Logger, records: list[BufferedLogRecord]) -> None:
    for record in records:
        logger.log(record.level, record.message)


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

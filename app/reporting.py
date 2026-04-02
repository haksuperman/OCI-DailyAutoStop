from __future__ import annotations

from collections import Counter
from datetime import datetime
from app.models import ActionResult, ResourceType, Summary

def build_completion_lines(
    results: list[ActionResult],
    dry_run: bool,
) -> list[str]:
    counts = _build_type_counts(results)
    if dry_run:
        message = (
            "Dry-run analysis completed "
            f"({counts['compute']['dry_run']} Instance(s), "
            f"{counts['db_node']['dry_run']} DB Node(s), "
            f"{counts['adb']['dry_run']} ADB(s) matched)."
        )
    else:
        message = (
            "Stop requests completed "
            f"({counts['compute']['requested']} Instance(s), "
            f"{counts['db_node']['requested']} DB Node(s), "
            f"{counts['adb']['requested']} ADB(s))."
        )
    return [
        "=" * 60,
        message,
    ]


def build_summary_lines(
    mode: str,
    summary: Summary,
    results: list[ActionResult],
    dry_run: bool,
    regions: list[str],
) -> list[str]:
    type_counts = _build_type_counts(results)
    duration = _format_duration(summary.started_at, summary.completed_at)

    lines = [
        "=" * 60,
        "Summary Details",
    ]
    lines.extend(_render_type_section_lines("Instances", "compute", type_counts["compute"], summary, dry_run))
    lines.extend(_render_type_section_lines("DB Nodes", "db_node", type_counts["db_node"], summary, dry_run))
    lines.extend(_render_type_section_lines("ADBs", "adb", type_counts["adb"], summary, dry_run))
    if summary.notes:
        lines.extend(
            [
                "",
                "Notes",
                *[f" - {note}" for note in summary.notes],
            ]
        )
    if summary.errors:
        lines.extend(
            [
                "",
                "Errors",
                *[f" - {error}" for error in summary.errors],
            ]
        )
    lines.extend(
        [
            "",
            _build_completion_line(dry_run, duration),
            "=" * 60,
        ]
    )
    return lines


def _build_type_counts(results: list[ActionResult]) -> dict[ResourceType, Counter[str]]:
    counts: dict[ResourceType, Counter[str]] = {
        "compute": Counter(),
        "db_node": Counter(),
        "adb": Counter(),
    }
    for result in results:
        counts[result.resource.resource_type][result.status] += 1
    return counts


def _render_type_section_lines(
    title: str,
    resource_type: ResourceType,
    counts: Counter[str],
    summary: Summary,
    dry_run: bool,
) -> list[str]:
    lines = [
        f" {title} scanned : {sum(counts.values())}",
        f"  ├─ Already stopped : {counts['already_stopped']}",
        f"  ├─ In transition   : {counts['transition']}",
    ]
    if dry_run:
        lines.append(f"  └─ Stop targets (Dry-run) : {counts['dry_run']}")
    else:
        lines.append(f"  └─ Stop by AutoStop : {render_verified_stop_line(summary, resource_type)}")
    if counts["failed"]:
        lines.append(f"    Failed : {counts['failed']}")
    return lines


def render_verified_stop_line(summary: Summary, resource_type: ResourceType) -> str:
    verification = summary.verification[resource_type]
    return f"{verification.requested} → {verification.confirmed_stopped} successful"


def _format_duration(started_at: datetime | None, completed_at: datetime | None) -> str:
    if not started_at or not completed_at:
        return "unknown"
    total_seconds = max(0, int((completed_at - started_at).total_seconds()))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{total_seconds}s"


def _build_completion_line(dry_run: bool, duration: str) -> str:
    if dry_run:
        return f"Dry-run completed (total duration: {duration})"
    return f"AutoStop completed (total duration: {duration})"

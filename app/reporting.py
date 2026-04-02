from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.config import AppSettings
from app.models import ActionResult, Summary


def write_summary(
    settings: AppSettings,
    summary: Summary,
    results: list[ActionResult],
    dry_run: bool,
) -> Path:
    settings.logging.summary_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = settings.logging.summary_directory / f"summary_{timestamp}.txt"

    lines = [
        summary.render(),
        "",
        f"mode: {settings.scope.mode}",
        f"dry_run: {dry_run}",
        f"regions: {', '.join(settings.oci.regions)}",
        "",
        "Detailed Results",
    ]
    for result in results:
        lines.append(
            " | ".join(
                [
                    result.status,
                    result.resource.resource_type,
                    result.resource.region,
                    result.resource.compartment_name,
                    result.resource.resource_name,
                    result.resource.lifecycle_state,
                    result.message,
                ]
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

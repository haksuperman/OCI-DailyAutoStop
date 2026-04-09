from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


ResourceType = Literal["compute", "db_node", "adb"]
ActionStatus = Literal["stopped", "already_stopped", "transition", "requested", "failed", "dry_run"]


@dataclass(frozen=True)
class CompartmentInfo:
    id: str
    name: str
    parent_id: str | None


@dataclass(frozen=True)
class ResourceRecord:
    resource_type: ResourceType
    region: str
    compartment_id: str
    compartment_name: str
    resource_id: str
    resource_name: str
    lifecycle_state: str


@dataclass
class ActionResult:
    resource: ResourceRecord
    status: ActionStatus
    message: str


@dataclass
class VerificationSummary:
    requested: int = 0
    confirmed_stopped: int = 0
    still_running: int = 0


@dataclass
class Summary:
    scanned: int = 0
    already_stopped: int = 0
    transition: int = 0
    stop_requested: int = 0
    success: int = 0
    failed: int = 0
    dry_run: int = 0
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    verification: dict[ResourceType, VerificationSummary] = field(
        default_factory=lambda: {
            "compute": VerificationSummary(),
            "db_node": VerificationSummary(),
            "adb": VerificationSummary(),
        }
    )
    started_at: datetime | None = None
    completed_at: datetime | None = None
    target_compartment_count: int = 0
    target_region_count: int = 0

    def register(self, result: ActionResult) -> None:
        self.scanned += 1
        if result.status == "already_stopped":
            self.already_stopped += 1
        elif result.status == "transition":
            self.transition += 1
        elif result.status == "requested":
            self.stop_requested += 1
            self.verification[result.resource.resource_type].requested += 1
        elif result.status == "stopped":
            self.success += 1
        elif result.status == "dry_run":
            self.stop_requested += 1
            self.dry_run += 1
        elif result.status == "failed":
            self.failed += 1

    def add_note(self, message: str) -> None:
        self.notes.append(message)

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def register_verification(self, resource_type: ResourceType, confirmed_stopped: bool) -> None:
        summary = self.verification[resource_type]
        if confirmed_stopped:
            summary.confirmed_stopped += 1
            self.success += 1
        else:
            summary.still_running += 1

    def render(self) -> str:
        lines = [
            "OCI AutoStop Summary",
            f"- scanned: {self.scanned}",
            f"- already_stopped: {self.already_stopped}",
            f"- transition: {self.transition}",
            f"- stop_requested: {self.stop_requested}",
            f"- actual_success: {self.success}",
            f"- dry_run: {self.dry_run}",
            f"- failed: {self.failed}",
        ]
        if self.notes:
            lines.append("- notes:")
            lines.extend(f"  * {note}" for note in self.notes)
        if self.errors:
            lines.append("- errors:")
            lines.extend(f"  * {error}" for error in self.errors)
        return "\n".join(lines)

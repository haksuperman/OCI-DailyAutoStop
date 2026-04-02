from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RetrySettings:
    max_attempts: int
    base_delay_seconds: float
    max_delay_seconds: float


@dataclass(frozen=True)
class ExecutionSettings:
    default_dry_run: bool
    max_workers: int
    stop_wait_timeout_seconds: int
    stop_wait_interval_seconds: int


@dataclass(frozen=True)
class LoggingSettings:
    directory: Path
    level: str
    summary_directory: Path


@dataclass(frozen=True)
class OciSettings:
    config_file: Path
    profile: str
    tenancy_ocid: str | None
    regions: list[str]


@dataclass(frozen=True)
class ScopeSettings:
    mode: str
    dev_base_compartment_name_or_ocid: str | None
    include_root_resources: bool
    exception_file: Path


@dataclass(frozen=True)
class AppSettings:
    oci: OciSettings
    scope: ScopeSettings
    execution: ExecutionSettings
    retry: RetrySettings
    logging: LoggingSettings


def load_settings(config_path: str | Path) -> AppSettings:
    config_file = Path(config_path).expanduser().resolve()
    with config_file.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    base_dir = config_file.parent.parent if config_file.parent.name == "config" else config_file.parent

    oci = _require_dict(raw, "oci")
    scope = _require_dict(raw, "scope")
    execution = _require_dict(raw, "execution")
    retry = _require_dict(raw, "retry")
    logging_cfg = _require_dict(raw, "logging")

    regions = list(oci.get("regions") or [])
    if not regions:
        raise ValueError("settings.oci.regions must not be empty")

    mode = str(scope.get("mode", "")).strip().lower()
    if mode not in {"dev", "prod"}:
        raise ValueError("settings.scope.mode must be 'dev' or 'prod'")

    dev_base = scope.get("dev_base_compartment_name_or_ocid")
    if mode == "dev" and not dev_base:
        raise ValueError("settings.scope.dev_base_compartment_name_or_ocid is required in dev mode")

    return AppSettings(
        oci=OciSettings(
            config_file=_resolve_path(base_dir, str(oci.get("config_file", "~/.oci/config"))),
            profile=str(oci.get("profile", "DEFAULT")),
            tenancy_ocid=_optional_str(oci.get("tenancy_ocid")),
            regions=regions,
        ),
        scope=ScopeSettings(
            mode=mode,
            dev_base_compartment_name_or_ocid=_optional_str(dev_base),
            include_root_resources=bool(scope.get("include_root_resources", False)),
            exception_file=_resolve_path(
                base_dir,
                str(scope.get("exception_file", "config/autostop_compartment_exception.txt")),
            ),
        ),
        execution=ExecutionSettings(
            default_dry_run=bool(execution.get("default_dry_run", True)),
            max_workers=max(1, int(execution.get("max_workers", 4))),
            stop_wait_timeout_seconds=max(30, int(execution.get("stop_wait_timeout_seconds", 900))),
            stop_wait_interval_seconds=max(5, int(execution.get("stop_wait_interval_seconds", 20))),
        ),
        retry=RetrySettings(
            max_attempts=max(1, int(retry.get("max_attempts", 4))),
            base_delay_seconds=max(0.1, float(retry.get("base_delay_seconds", 1.0))),
            max_delay_seconds=max(0.5, float(retry.get("max_delay_seconds", 16.0))),
        ),
        logging=LoggingSettings(
            directory=_resolve_path(base_dir, str(logging_cfg.get("directory", "logs"))),
            level=str(logging_cfg.get("level", "INFO")).upper(),
            summary_directory=_resolve_path(base_dir, str(logging_cfg.get("summary_directory", "logs/summary"))),
        ),
    )


def _require_dict(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"settings.{key} must be an object")
    return value


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

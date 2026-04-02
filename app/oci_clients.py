from __future__ import annotations

from dataclasses import dataclass
import logging

import oci
from oci.pagination import list_call_get_all_results

from app.config import AppSettings
from app.retry import call_with_retry


@dataclass
class ClientBundle:
    identity: oci.identity.IdentityClient
    compute: oci.core.ComputeClient
    database: oci.database.DatabaseClient
    retry_strategy: oci.retry.NoneRetryStrategy


@dataclass(frozen=True)
class RegionResolution:
    regions: list[str]
    notes: list[str]


def load_oci_config(settings: AppSettings) -> dict[str, str]:
    config = oci.config.from_file(
        file_location=str(settings.oci.config_file),
        profile_name=settings.oci.profile,
    )
    if settings.oci.tenancy_ocid:
        config["tenancy"] = settings.oci.tenancy_ocid
    return config


def build_clients(config: dict[str, str], region: str) -> ClientBundle:
    regional_config = dict(config)
    regional_config["region"] = region
    retry_strategy = oci.retry.NoneRetryStrategy()

    return ClientBundle(
        identity=oci.identity.IdentityClient(regional_config, retry_strategy=retry_strategy),
        compute=oci.core.ComputeClient(regional_config, retry_strategy=retry_strategy),
        database=oci.database.DatabaseClient(regional_config, retry_strategy=retry_strategy),
        retry_strategy=retry_strategy,
    )


def validate_tenancy(config: dict[str, str], logger: logging.Logger) -> str:
    tenancy = config.get("tenancy")
    if not tenancy:
        raise ValueError("OCI config missing tenancy value")
    return tenancy


def resolve_execution_regions(
    settings: AppSettings,
    oci_config: dict[str, str],
    tenancy_ocid: str,
    logger: logging.Logger,
) -> RegionResolution:
    configured_regions = settings.oci.regions
    excluded_regions = set(settings.oci.excluded_regions)

    if settings.scope.mode == "dev":
        regions = [region for region in configured_regions if region not in excluded_regions]
        if not regions:
            raise ValueError("No execution regions left after applying settings.oci.excluded_regions in dev mode")
        return RegionResolution(
            regions=regions,
            notes=_build_region_notes("configured", regions, excluded_regions, configured_regions),
        )

    home_region = oci_config.get("region") or (configured_regions[0] if configured_regions else None)
    if not home_region:
        raise ValueError("Unable to determine home region for prod region discovery")

    identity_client = build_clients(oci_config, home_region).identity
    try:
        subscribed_regions = list_subscribed_regions(identity_client, tenancy_ocid, settings, logger)
        regions = [region for region in subscribed_regions if region not in excluded_regions]
        if not regions:
            raise ValueError("No execution regions left after applying settings.oci.excluded_regions in prod mode")
        return RegionResolution(
            regions=regions,
            notes=_build_region_notes("subscribed", regions, excluded_regions, subscribed_regions),
        )
    except Exception as exc:
        fallback_regions = [region for region in configured_regions if region not in excluded_regions]
        if not fallback_regions:
            raise ValueError(
                "Prod region discovery failed and no fallback regions remain in settings.oci.regions after exclusions"
            ) from exc
        logger.exception("PROD region discovery failed. Falling back to configured regions")
        notes = _build_region_notes("fallback_configured", fallback_regions, excluded_regions, configured_regions)
        notes.insert(0, f"prod region auto-discovery failed; fallback configured regions used: {exc}")
        return RegionResolution(regions=fallback_regions, notes=notes)


def list_subscribed_regions(identity_client, tenancy_ocid: str, settings: AppSettings, logger: logging.Logger) -> list[str]:
    response = call_with_retry(
        lambda: list_call_get_all_results(identity_client.list_region_subscriptions, tenancy_id=tenancy_ocid),
        settings.retry,
        logger,
        f"list_region_subscriptions:{tenancy_ocid}",
    )
    regions = sorted(
        {
            item.region_name
            for item in response.data
            if getattr(item, "region_name", None) and getattr(item, "status", "READY") == "READY"
        }
    )
    if not regions:
        raise ValueError("No subscribed regions were returned for the tenancy")
    return regions


def _build_region_notes(
    region_source: str,
    effective_regions: list[str],
    excluded_regions: set[str],
    source_regions: list[str],
) -> list[str]:
    notes = [
        f"region source: {region_source}",
        f"execution regions: {', '.join(effective_regions)}",
    ]
    applied_exclusions = [region for region in source_regions if region in excluded_regions]
    if applied_exclusions:
        notes.append(f"excluded regions: {', '.join(sorted(set(applied_exclusions)))}")
    return notes

from __future__ import annotations

from dataclasses import dataclass
import logging

import oci

from app.config import AppSettings


@dataclass
class ClientBundle:
    identity: oci.identity.IdentityClient
    compute: oci.core.ComputeClient
    database: oci.database.DatabaseClient
    retry_strategy: oci.retry.NoneRetryStrategy


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
    logger.info("Loaded OCI configuration for tenancy %s", tenancy)
    return tenancy

from __future__ import annotations

import logging
from pathlib import Path

from oci.pagination import list_call_get_all_results

from app.config import AppSettings
from app.models import CompartmentInfo
from app.retry import call_with_retry


def load_exception_entries(path: Path) -> list[str]:
    if not path.exists():
        return []
    entries: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(line)
    return entries


def build_target_compartments(
    clients,
    tenancy_ocid: str,
    settings: AppSettings,
    logger: logging.Logger,
) -> list[CompartmentInfo]:
    if settings.scope.mode == "dev":
        base = resolve_dev_base_compartment(
            clients.identity,
            tenancy_ocid,
            settings.scope.dev_base_compartment_name_or_ocid or "",
            settings.retry,
            logger,
        )
        compartments = list_subtree_compartments(clients.identity, base.id, tenancy_ocid, settings.retry, logger)
        compartments.insert(0, base)
    else:
        compartments = list_subtree_compartments(clients.identity, tenancy_ocid, tenancy_ocid, settings.retry, logger)

    unique = {comp.id: comp for comp in compartments}
    if settings.scope.mode == "prod" and settings.scope.include_root_resources:
        unique[tenancy_ocid] = CompartmentInfo(id=tenancy_ocid, name="root", parent_id=None)

    exceptions = resolve_exception_compartments(
        clients.identity,
        tenancy_ocid,
        settings,
        logger,
        unique,
    )

    filtered = [comp for comp in unique.values() if comp.id not in exceptions]
    filtered.sort(key=lambda item: (item.name.lower(), item.id))
    return filtered


def list_subtree_compartments(
    identity_client,
    root_id: str,
    tenancy_ocid: str,
    retry_settings,
    logger: logging.Logger,
) -> list[CompartmentInfo]:
    if root_id == tenancy_ocid:
        response = call_with_retry(
            lambda: list_call_get_all_results(
                identity_client.list_compartments,
                compartment_id=root_id,
                compartment_id_in_subtree=True,
                access_level="ANY",
                lifecycle_state="ACTIVE",
            ),
            retry_settings,
            logger,
            f"list_compartments:{root_id}",
        )
        result: list[CompartmentInfo] = []
        for item in response.data:
            if item.id == root_id:
                continue
            result.append(CompartmentInfo(id=item.id, name=item.name, parent_id=item.compartment_id))
        return result

    result: list[CompartmentInfo] = []
    pending = [root_id]
    seen: set[str] = set()

    while pending:
        parent_id = pending.pop()
        if parent_id in seen:
            continue
        seen.add(parent_id)

        response = call_with_retry(
            lambda parent_id=parent_id: list_call_get_all_results(
                identity_client.list_compartments,
                compartment_id=parent_id,
                compartment_id_in_subtree=False,
                access_level="ANY",
                lifecycle_state="ACTIVE",
            ),
            retry_settings,
            logger,
            f"list_compartments_children:{parent_id}",
        )
        for item in response.data:
            compartment = CompartmentInfo(id=item.id, name=item.name, parent_id=item.compartment_id)
            result.append(compartment)
            pending.append(item.id)

    return result


def resolve_dev_base_compartment(identity_client, tenancy_ocid: str, key: str, retry_settings, logger: logging.Logger) -> CompartmentInfo:
    if key.startswith("ocid1.compartment"):
        response = call_with_retry(
            lambda: identity_client.get_compartment(key),
            retry_settings,
            logger,
            f"get_compartment:{key}",
        )
        data = response.data
        return CompartmentInfo(id=data.id, name=data.name, parent_id=data.compartment_id)

    direct_children = call_with_retry(
        lambda: list_call_get_all_results(
            identity_client.list_compartments,
            compartment_id=tenancy_ocid,
            access_level="ANY",
            compartment_id_in_subtree=False,
            lifecycle_state="ACTIVE",
        ),
        retry_settings,
        logger,
        "list_root_children",
    )
    matches = [item for item in direct_children.data if item.name == key]
    if len(matches) != 1:
        raise ValueError(
            "DEV base compartment must match exactly one direct child of root. "
            f"name={key!r}, matches={len(matches)}"
        )
    item = matches[0]
    return CompartmentInfo(id=item.id, name=item.name, parent_id=item.compartment_id)


def resolve_exception_compartments(
    identity_client,
    tenancy_ocid: str,
    settings: AppSettings,
    logger: logging.Logger,
    current_scope: dict[str, CompartmentInfo],
) -> set[str]:
    entries = load_exception_entries(settings.scope.exception_file)
    if settings.scope.mode == "dev" and not entries:
        return set()
    if settings.scope.mode == "prod" and not settings.scope.exception_file.exists():
        raise FileNotFoundError(f"Exception file not found: {settings.scope.exception_file}")

    excluded: set[str] = set()
    for entry in entries:
        compartment = resolve_compartment_entry(identity_client, tenancy_ocid, entry, settings.retry, logger, current_scope)
        excluded.add(compartment.id)
        for child in list_subtree_compartments(identity_client, compartment.id, tenancy_ocid, settings.retry, logger):
            excluded.add(child.id)
    return excluded


def resolve_compartment_entry(
    identity_client,
    tenancy_ocid: str,
    entry: str,
    retry_settings,
    logger: logging.Logger,
    current_scope: dict[str, CompartmentInfo],
) -> CompartmentInfo:
    if entry in current_scope:
        return current_scope[entry]
    if entry.startswith("ocid1.compartment"):
        response = call_with_retry(
            lambda: identity_client.get_compartment(entry),
            retry_settings,
            logger,
            f"get_exception_compartment:{entry}",
        )
        data = response.data
        return CompartmentInfo(id=data.id, name=data.name, parent_id=data.compartment_id)

    matches = [item for item in current_scope.values() if item.name == entry]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Exception compartment name is ambiguous: {entry}")

    response = call_with_retry(
        lambda: list_call_get_all_results(
            identity_client.list_compartments,
            compartment_id=tenancy_ocid,
            compartment_id_in_subtree=True,
            access_level="ANY",
            lifecycle_state="ACTIVE",
        ),
        retry_settings,
        logger,
        f"search_exception_compartment:{entry}",
    )
    all_matches = [item for item in response.data if item.name == entry]
    if len(all_matches) != 1:
        raise ValueError(f"Exception compartment entry must resolve to exactly one compartment: {entry}")
    item = all_matches[0]
    return CompartmentInfo(id=item.id, name=item.name, parent_id=item.compartment_id)

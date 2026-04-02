from __future__ import annotations

from collections.abc import Callable
import logging
import time

from oci.pagination import list_call_get_all_results

from app.config import AppSettings
from app.models import ActionResult, CompartmentInfo, ResourceRecord
from app.retry import call_with_retry


COMPUTE_TRANSITION_STATES = {"STOPPING", "STARTING", "PROVISIONING"}
DB_NODE_TRANSITION_STATES = {"STOPPING", "STARTING", "PROVISIONING"}
ADB_TRANSITION_STATES = {"STOPPING", "STARTING", "PROVISIONING", "SCALING"}


def process_compartment_resources(
    clients,
    region: str,
    compartment: CompartmentInfo,
    settings: AppSettings,
    dry_run: bool,
    logger: logging.Logger,
) -> list[ActionResult]:
    results: list[ActionResult] = []
    results.extend(handle_compute_instances(clients, region, compartment, settings, dry_run, logger))
    results.extend(handle_db_nodes(clients, region, compartment, settings, dry_run, logger))
    results.extend(handle_adbs(clients, region, compartment, settings, dry_run, logger))
    return results


def handle_compute_instances(clients, region: str, compartment: CompartmentInfo, settings: AppSettings, dry_run: bool, logger: logging.Logger) -> list[ActionResult]:
    response = call_with_retry(
        lambda: list_call_get_all_results(
            clients.compute.list_instances,
            compartment_id=compartment.id,
        ),
        settings.retry,
        logger,
        f"list_instances:{region}:{compartment.id}",
    )
    results: list[ActionResult] = []
    for item in response.data:
        if item.lifecycle_state == "TERMINATED":
            continue
        record = ResourceRecord(
            resource_type="compute",
            region=region,
            compartment_id=compartment.id,
            compartment_name=compartment.name,
            resource_id=item.id,
            resource_name=item.display_name or item.id,
            lifecycle_state=item.lifecycle_state,
        )
        results.append(
            _stop_or_skip(
                record=record,
                current_state=item.lifecycle_state,
                running_state="RUNNING",
                stopped_states={"STOPPED"},
                transition_states=COMPUTE_TRANSITION_STATES,
                dry_run=dry_run,
                logger=logger,
                stop_func=lambda: call_with_retry(
                    lambda: clients.compute.instance_action(record.resource_id, "STOP"),
                    settings.retry,
                    logger,
                    f"stop_instance:{record.resource_id}",
                ),
                state_fetcher=lambda: call_with_retry(
                    lambda: clients.compute.get_instance(record.resource_id).data.lifecycle_state,
                    settings.retry,
                    logger,
                    f"get_instance:{record.resource_id}",
                ),
                settings=settings,
            )
        )
    return results


def handle_db_nodes(clients, region: str, compartment: CompartmentInfo, settings: AppSettings, dry_run: bool, logger: logging.Logger) -> list[ActionResult]:
    db_systems = call_with_retry(
        lambda: list_call_get_all_results(
            clients.database.list_db_systems,
            compartment_id=compartment.id,
        ),
        settings.retry,
        logger,
        f"list_db_systems:{region}:{compartment.id}",
    )
    results: list[ActionResult] = []
    for db_system in db_systems.data:
        if db_system.lifecycle_state == "TERMINATED":
            continue
        db_nodes = call_with_retry(
            lambda: list_call_get_all_results(
                clients.database.list_db_nodes,
                compartment_id=compartment.id,
                db_system_id=db_system.id,
            ),
            settings.retry,
            logger,
            f"list_db_nodes:{region}:{db_system.id}",
        )
        for item in db_nodes.data:
            record = ResourceRecord(
                resource_type="db_node",
                region=region,
                compartment_id=compartment.id,
                compartment_name=compartment.name,
                resource_id=item.id,
                resource_name=getattr(item, "hostname", None) or getattr(item, "display_name", None) or item.id,
                lifecycle_state=item.lifecycle_state,
            )
            results.append(
                _stop_or_skip(
                    record=record,
                    current_state=item.lifecycle_state,
                    running_state="AVAILABLE",
                    stopped_states={"STOPPED"},
                    transition_states=DB_NODE_TRANSITION_STATES,
                    dry_run=dry_run,
                    logger=logger,
                    stop_func=lambda resource_id=item.id: call_with_retry(
                        lambda: clients.database.db_node_action(resource_id, "STOP"),
                        settings.retry,
                        logger,
                        f"stop_db_node:{resource_id}",
                    ),
                    state_fetcher=lambda resource_id=item.id: call_with_retry(
                        lambda: clients.database.get_db_node(resource_id).data.lifecycle_state,
                        settings.retry,
                        logger,
                        f"get_db_node:{resource_id}",
                    ),
                    settings=settings,
                )
            )
    return results


def handle_adbs(clients, region: str, compartment: CompartmentInfo, settings: AppSettings, dry_run: bool, logger: logging.Logger) -> list[ActionResult]:
    response = call_with_retry(
        lambda: list_call_get_all_results(
            clients.database.list_autonomous_databases,
            compartment_id=compartment.id,
        ),
        settings.retry,
        logger,
        f"list_adb:{region}:{compartment.id}",
    )
    results: list[ActionResult] = []
    for item in response.data:
        if item.lifecycle_state == "TERMINATED":
            continue
        record = ResourceRecord(
            resource_type="adb",
            region=region,
            compartment_id=compartment.id,
            compartment_name=compartment.name,
            resource_id=item.id,
            resource_name=item.display_name or item.db_name or item.id,
            lifecycle_state=item.lifecycle_state,
        )
        results.append(
            _stop_or_skip(
                record=record,
                current_state=item.lifecycle_state,
                running_state="AVAILABLE",
                stopped_states={"STOPPED", "UNAVAILABLE"},
                transition_states=ADB_TRANSITION_STATES,
                dry_run=dry_run,
                logger=logger,
                stop_func=lambda: call_with_retry(
                    lambda: clients.database.stop_autonomous_database(record.resource_id),
                    settings.retry,
                    logger,
                    f"stop_adb:{record.resource_id}",
                ),
                state_fetcher=lambda: call_with_retry(
                    lambda: clients.database.get_autonomous_database(record.resource_id).data.lifecycle_state,
                    settings.retry,
                    logger,
                    f"get_adb:{record.resource_id}",
                ),
                settings=settings,
            )
        )
    return results


def _stop_or_skip(
    record: ResourceRecord,
    current_state: str,
    running_state: str,
    stopped_states: set[str],
    transition_states: set[str],
    dry_run: bool,
    logger: logging.Logger,
    stop_func: Callable[[], object],
    state_fetcher: Callable[[], str],
    settings: AppSettings,
) -> ActionResult:
    state = (current_state or "").upper()

    if state in stopped_states:
        return ActionResult(record, "already_stopped", f"Already stopped: {state}")

    if state in transition_states:
        return ActionResult(record, "transition", f"Transition state: {state}")

    if state != running_state:
        return ActionResult(record, "already_stopped", f"Non-target state: {state}")

    if dry_run:
        return ActionResult(record, "dry_run", "Dry-run stop request prepared")

    try:
        stop_func()
        final_state = _wait_for_stop(state_fetcher, settings, logger, record)
        return ActionResult(record, "requested", f"Stop confirmed: {final_state}")
    except Exception as exc:  # pragma: no cover
        return ActionResult(record, "failed", str(exc))


def _wait_for_stop(
    state_fetcher: Callable[[], str],
    settings: AppSettings,
    logger: logging.Logger,
    record: ResourceRecord,
) -> str:
    deadline = time.time() + settings.execution.stop_wait_timeout_seconds
    last_state = "UNKNOWN"
    while time.time() < deadline:
        last_state = (state_fetcher() or "").upper()
        if last_state in {"STOPPED", "UNAVAILABLE"}:
            return last_state
        if last_state not in {"STOPPING", "STARTING", "PROVISIONING", "SCALING", "AVAILABLE", "RUNNING"}:
            logger.warning(
                "Resource reached unexpected post-stop state. resource_id=%s state=%s",
                record.resource_id,
                last_state,
            )
        time.sleep(settings.execution.stop_wait_interval_seconds)
    raise TimeoutError(
        f"Timed out waiting for stop confirmation. resource_id={record.resource_id}, last_state={last_state}"
    )

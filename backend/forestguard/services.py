"""Monitoring workflows coordinating repositories and database transactions."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from forestguard import alert_repository, notification_repository, repositories, risk_repository
from forestguard.config import Settings, get_settings
from forestguard.database import connect
from forestguard.risk_engine import (
    RISK_STATE_RANK,
    ConnectivityState,
    RiskObservation,
    RiskState,
    assess_connectivity,
    assess_risk,
)
from forestguard.risk_profile import DEMO_RISK_PROFILE
from forestguard.schemas import (
    NodeCreate,
    NodeUpdate,
    ReadingCreate,
    utc_iso,
    utc_now,
    validate_coordinate_pair,
)


class NodeNotFound(Exception):
    """Raised when a station identifier has no registered station."""


class DuplicateNode(Exception):
    """Raised when a station identifier is already registered."""


class InvalidNodeUpdate(Exception):
    """Raised when a partial station update would leave invalid coordinates."""


class AlertNotFound(Exception):
    """Raised when an alert identifier is not present."""


class AlertAlreadyResolved(Exception):
    """Raised when a resolved alert cannot be acknowledged again."""


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _observation(record: dict[str, Any]) -> RiskObservation:
    return RiskObservation(
        timestamp=_parse_utc(record["timestamp"]),
        temperature_c=record.get("temperature_c"),
        humidity_percent=record.get("humidity_percent"),
        smoke_value=record.get("smoke_value"),
        gas_value=record.get("gas_value"),
        is_simulated=bool(record["is_simulated"]),
    )


def _assessment_values(assessment: Any) -> dict[str, Any]:
    values = assessment.as_dict()
    values["reasons_json"] = json.dumps(values["reasons"], separators=(",", ":"))
    values["signals_json"] = json.dumps(values["signals"], separators=(",", ":"))
    return values


def _node_with_connectivity(node: dict[str, Any]) -> dict[str, Any]:
    last_seen = node["last_seen_at"]
    node["connectivity_state"] = (
        assess_connectivity(_parse_utc(last_seen)).value
        if last_seen is not None
        else ConnectivityState.OFFLINE.value
    )
    return node


def _reconcile_alert(
    connection: sqlite3.Connection,
    *,
    node_id: str,
    reading_id: int,
    is_simulated: bool,
    assessment_values: dict[str, Any],
    settings: Settings,
) -> None:
    state = RiskState(assessment_values["risk_state"])
    active = alert_repository.get_open_alert(connection, node_id, is_simulated)
    if state is RiskState.NORMAL:
        if active is not None:
            normal_count = risk_repository.consecutive_normal_assessments(
                connection,
                node_id=node_id,
                measured_at=assessment_values["reading_timestamp"],
                reading_id=reading_id,
                is_simulated=is_simulated,
                limit=DEMO_RISK_PROFILE.normal_readings_to_resolve,
            )
            if normal_count >= DEMO_RISK_PROFILE.normal_readings_to_resolve:
                alert_repository.resolve_alert(
                    connection,
                    active["alert_id"],
                    assessment_values["timestamp"],
                    f"Risk returned to NORMAL for {normal_count} consecutive readings.",
                )
        return

    values = {
        "alert_id": uuid.uuid4().hex,
        "node_id": node_id,
        "severity": state.value,
        "risk_score": assessment_values["risk_score"],
        "reasons_json": assessment_values["reasons_json"],
        "timestamp": assessment_values["timestamp"],
        "is_simulated": is_simulated,
        "reading_id": reading_id,
    }
    if active is None:
        created = alert_repository.create_alert(connection, values)
        notification_repository.enqueue_alert_event(
            connection,
            created,
            event_type="CREATED",
            reading_id=reading_id,
            settings=settings,
        )
        return

    previous_state = RiskState(active["severity"])
    severity_escalated = RISK_STATE_RANK[state] > RISK_STATE_RANK[previous_state]
    evidence_changed = (
        active["severity"] != state.value
        or active["risk_score"] != values["risk_score"]
        or active["reasons"] != assessment_values["reasons"]
    )
    if evidence_changed:
        updated = alert_repository.update_open_alert(
            connection,
            active["alert_id"],
            values,
            reactivate=active["status"] == "ACKNOWLEDGED" and severity_escalated,
        )
        if severity_escalated and updated is not None:
            notification_repository.enqueue_alert_event(
                connection,
                updated,
                event_type="ESCALATED",
                reading_id=reading_id,
                settings=settings,
            )


def create_node(database_path: Path, node: NodeCreate) -> dict[str, Any]:
    now = utc_iso(utc_now())
    try:
        with connect(database_path) as connection:
            return _node_with_connectivity(repositories.create_node(connection, node, now))
    except sqlite3.IntegrityError as error:
        if "nodes.node_id" in str(error):
            raise DuplicateNode(node.node_id) from error
        raise


def list_nodes(database_path: Path, limit: int, offset: int) -> list[dict[str, Any]]:
    with connect(database_path) as connection:
        return [
            _node_with_connectivity(node)
            for node in repositories.list_nodes(connection, limit, offset)
        ]


def get_node(database_path: Path, node_id: str) -> dict[str, Any]:
    with connect(database_path) as connection:
        node = repositories.get_node(connection, node_id)
    if node is None:
        raise NodeNotFound(node_id)
    return _node_with_connectivity(node)


def update_node(
    database_path: Path,
    node_id: str,
    update: NodeUpdate,
) -> dict[str, Any]:
    changes = update.model_dump(exclude_unset=True)
    with connect(database_path) as connection:
        current = repositories.get_node(connection, node_id)
        if current is None:
            raise NodeNotFound(node_id)
        if "name" in changes and changes["name"] is None:
            raise InvalidNodeUpdate("name cannot be null")
        latitude = changes.get("latitude", current["latitude"])
        longitude = changes.get("longitude", current["longitude"])
        try:
            validate_coordinate_pair(latitude, longitude)
        except ValueError as error:
            raise InvalidNodeUpdate(str(error)) from error
        updated = repositories.update_node(
            connection,
            node_id,
            changes,
            utc_iso(utc_now()),
        )
    if updated is None:
        raise NodeNotFound(node_id)
    return _node_with_connectivity(updated)


def ingest_reading(
    database_path: Path,
    reading: ReadingCreate,
    settings: Settings | None = None,
) -> dict[str, Any]:
    received_at = utc_iso(utc_now())
    measured_at = utc_iso(reading.timestamp)
    runtime_settings = settings or get_settings()
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        previous_node = repositories.get_node(connection, reading.node_id)
        previous_latest = previous_node["latest_reading_at"] if previous_node else None
        repositories.upsert_reading_station(connection, reading, received_at)
        record = repositories.insert_reading(connection, reading, received_at)
        repositories.update_latest_node_reading(connection, reading)
        history_records = risk_repository.recent_history(
            connection,
            node_id=reading.node_id,
            measured_at=measured_at,
            reading_id=record["id"],
            is_simulated=reading.is_simulated,
            limit=5,
        )
        assessment = assess_risk(
            _observation(record),
            [_observation(item) for item in history_records],
            assessed_at=utc_now(),
            connectivity_at=_parse_utc(received_at),
        )
        assessment_values = _assessment_values(assessment)
        assessment_values["reading_timestamp"] = measured_at
        risk_repository.save_reading_assessment(connection, record["id"], assessment_values)
        is_latest = previous_latest is None or measured_at >= previous_latest
        if is_latest:
            risk_repository.save_node_assessment(
                connection,
                reading.node_id,
                assessment_values,
            )
            _reconcile_alert(
                connection,
                node_id=reading.node_id,
                reading_id=record["id"],
                is_simulated=reading.is_simulated,
                assessment_values=assessment_values,
                settings=runtime_settings,
            )
        saved = repositories.get_reading(connection, record["id"])
    if saved is None:
        raise RuntimeError("Persisted reading could not be retrieved")
    return saved


def list_readings(
    database_path: Path,
    *,
    node_id: str | None,
    is_simulated: bool | None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    with connect(database_path) as connection:
        return repositories.list_readings(
            connection,
            node_id=node_id,
            is_simulated=is_simulated,
            limit=limit,
            offset=offset,
        )


def list_node_readings(
    database_path: Path,
    node_id: str,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    with connect(database_path) as connection:
        if repositories.get_node(connection, node_id) is None:
            raise NodeNotFound(node_id)
        return repositories.list_node_readings(connection, node_id, limit, offset)


def list_node_series(
    database_path: Path,
    node_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    with connect(database_path) as connection:
        if repositories.get_node(connection, node_id) is None:
            raise NodeNotFound(node_id)
        return repositories.list_node_series(connection, node_id, limit)


def list_alerts(
    database_path: Path,
    *,
    node_id: str | None,
    severity: str | None,
    status: str | None,
    is_simulated: bool | None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    with connect(database_path) as connection:
        return alert_repository.list_alerts(
            connection,
            node_id=node_id,
            severity=severity,
            status=status,
            is_simulated=is_simulated,
            limit=limit,
            offset=offset,
        )


def get_alert_summary(database_path: Path) -> dict[str, Any]:
    with connect(database_path) as connection:
        return alert_repository.alert_summary(connection)


def acknowledge_alert(database_path: Path, alert_id: str) -> dict[str, Any]:
    acknowledged_at = utc_iso(utc_now())
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = alert_repository.get_alert(connection, alert_id)
        if current is None:
            raise AlertNotFound(alert_id)
        if current["status"] == "RESOLVED":
            raise AlertAlreadyResolved(alert_id)
        if current["status"] == "ACTIVE":
            updated = alert_repository.acknowledge_alert(
                connection,
                alert_id,
                acknowledged_at,
            )
        else:
            updated = current
    if updated is None:
        raise AlertNotFound(alert_id)
    return updated

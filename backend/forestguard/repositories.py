"""SQLite data-access helpers for station and sensor-reading records."""

import json
import sqlite3
from typing import Any

from forestguard.schemas import NodeCreate, ReadingCreate, utc_iso


def _node_record(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    record = dict(row)
    record["latest_is_simulated"] = bool(record["latest_is_simulated"])
    for key in (
        "latest_temperature_available",
        "latest_humidity_available",
        "latest_smoke_available",
    ):
        record[key] = bool(record[key])
    if record["current_risk_reasons"] is not None:
        record["current_risk_reasons"] = json.loads(record["current_risk_reasons"])
    return record


def _reading_record(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    record = dict(row)
    record["is_simulated"] = bool(record["is_simulated"])
    for key in ("temperature_available", "humidity_available", "smoke_available"):
        record[key] = bool(record[key])
    for key in ("risk_reasons", "risk_signals"):
        if record[key] is not None:
            record[key] = json.loads(record[key])
    return record


def create_node(connection: sqlite3.Connection, node: NodeCreate, now: str) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO nodes (
            node_id, name, latitude, longitude, location, created_at, updated_at,
            latest_temperature_available, latest_humidity_available, latest_smoke_available
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
        """,
        (node.node_id, node.name, node.latitude, node.longitude, node.location, now, now),
    )
    record = get_node(connection, node.node_id)
    if record is None:
        raise RuntimeError("Inserted node could not be retrieved")
    return record


def get_node(connection: sqlite3.Connection, node_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM nodes WHERE node_id = ?",
        (node_id,),
    ).fetchone()
    return _node_record(row)


def list_nodes(connection: sqlite3.Connection, limit: int, offset: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM nodes ORDER BY updated_at DESC, node_id LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [_node_record(row) for row in rows if row is not None]


def update_node(
    connection: sqlite3.Connection,
    node_id: str,
    changes: dict[str, Any],
    updated_at: str,
) -> dict[str, Any] | None:
    allowed = {"name", "latitude", "longitude", "location"}
    assignments = [f"{column} = ?" for column in changes if column in allowed]
    values = [changes[column] for column in changes if column in allowed]
    if not assignments:
        return get_node(connection, node_id)
    assignments.append("updated_at = ?")
    values.extend((updated_at, node_id))
    connection.execute(
        f"UPDATE nodes SET {', '.join(assignments)} WHERE node_id = ?",
        values,
    )
    return get_node(connection, node_id)


def upsert_reading_station(
    connection: sqlite3.Connection,
    reading: ReadingCreate,
    received_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO nodes (
            node_id, name, latitude, longitude, created_at, updated_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(node_id) DO UPDATE SET
            latitude = COALESCE(excluded.latitude, nodes.latitude),
            longitude = COALESCE(excluded.longitude, nodes.longitude),
            last_seen_at = excluded.last_seen_at
        """,
        (
            reading.node_id,
            reading.node_id,
            reading.latitude,
            reading.longitude,
            received_at,
            received_at,
            received_at,
        ),
    )


def insert_reading(
    connection: sqlite3.Connection,
    reading: ReadingCreate,
    received_at: str,
) -> dict[str, Any]:
    cursor = connection.execute(
        """
        INSERT INTO readings (
            node_id, temperature_c, humidity_percent, smoke_value, gas_value,
            latitude, longitude, battery_percent, measured_at, received_at, is_simulated,
            temperature_available, humidity_available, smoke_available
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            reading.node_id,
            reading.temperature_c if reading.temperature_c is not None else 0,
            reading.humidity_percent if reading.humidity_percent is not None else 0,
            reading.smoke_value if reading.smoke_value is not None else 0,
            reading.gas_value,
            reading.latitude,
            reading.longitude,
            reading.battery_percent,
            utc_iso(reading.timestamp),
            received_at,
            int(reading.is_simulated),
            int(reading.temperature_c is not None),
            int(reading.humidity_percent is not None),
            int(reading.smoke_value is not None),
        ),
    )
    record = get_reading(connection, cursor.lastrowid)
    if record is None:
        raise RuntimeError("Inserted reading could not be retrieved")
    return record


def update_latest_node_reading(
    connection: sqlite3.Connection,
    reading: ReadingCreate,
) -> None:
    measured_at = utc_iso(reading.timestamp)
    connection.execute(
        """
        UPDATE nodes SET
            latest_reading_at = ?,
            latest_temperature_c = ?,
            latest_humidity_percent = ?,
            latest_smoke_value = ?,
            latest_gas_value = ?,
            battery_percent = ?,
            latest_is_simulated = ?,
            latest_temperature_available = ?,
            latest_humidity_available = ?,
            latest_smoke_available = ?
        WHERE node_id = ?
          AND (latest_reading_at IS NULL OR latest_reading_at <= ?)
        """,
        (
            measured_at,
            reading.temperature_c,
            reading.humidity_percent,
            reading.smoke_value,
            reading.gas_value,
            reading.battery_percent,
            int(reading.is_simulated),
            int(reading.temperature_c is not None),
            int(reading.humidity_percent is not None),
            int(reading.smoke_value is not None),
            reading.node_id,
            measured_at,
        ),
    )


def get_reading(connection: sqlite3.Connection, reading_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT id, node_id,
               CASE WHEN temperature_available THEN temperature_c END AS temperature_c,
               CASE WHEN humidity_available THEN humidity_percent END AS humidity_percent,
               CASE WHEN smoke_available THEN smoke_value END AS smoke_value,
               gas_value, temperature_available, humidity_available, smoke_available,
               latitude, longitude, battery_percent, measured_at AS timestamp,
               received_at, is_simulated, risk_state, risk_score, risk_reasons,
               risk_signals, risk_profile_version, assessment_timestamp, connectivity_state
        FROM readings WHERE id = ?
        """,
        (reading_id,),
    ).fetchone()
    return _reading_record(row)


def list_readings(
    connection: sqlite3.Connection,
    *,
    node_id: str | None,
    is_simulated: bool | None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    conditions: list[str] = []
    values: list[Any] = []
    if node_id is not None:
        conditions.append("node_id = ?")
        values.append(node_id)
    if is_simulated is not None:
        conditions.append("is_simulated = ?")
        values.append(int(is_simulated))
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = connection.execute(
        f"""
        SELECT id, node_id,
               CASE WHEN temperature_available THEN temperature_c END AS temperature_c,
               CASE WHEN humidity_available THEN humidity_percent END AS humidity_percent,
               CASE WHEN smoke_available THEN smoke_value END AS smoke_value,
               gas_value, temperature_available, humidity_available, smoke_available,
               latitude, longitude, battery_percent, measured_at AS timestamp,
               received_at, is_simulated, risk_state, risk_score, risk_reasons,
               risk_signals, risk_profile_version, assessment_timestamp, connectivity_state
        FROM readings {where}
        ORDER BY measured_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (*values, limit, offset),
    ).fetchall()
    return [_reading_record(row) for row in rows if row is not None]


def list_node_readings(
    connection: sqlite3.Connection,
    node_id: str,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    return list_readings(
        connection,
        node_id=node_id,
        is_simulated=None,
        limit=limit,
        offset=offset,
    )


def list_node_series(
    connection: sqlite3.Connection,
    node_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    newest_first = list_node_readings(connection, node_id, limit, 0)
    return list(reversed(newest_first))

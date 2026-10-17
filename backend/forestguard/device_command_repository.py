"""Parameterized SQLite access for device-command records and immutable audit events."""

import json
import sqlite3
import uuid
from typing import Any


def record_event(
    connection: sqlite3.Connection,
    *,
    event_id: str,
    command_id: str | None,
    node_id: str | None,
    event_type: str,
    actor: str,
    event_at: str,
    details: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO device_command_events (
            event_id, command_id, node_id, event_type, actor, event_at, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            command_id,
            node_id,
            event_type,
            actor,
            event_at,
            json.dumps(details, separators=(",", ":")),
        ),
    )


def add_command(connection: sqlite3.Connection, command: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO device_commands (
            command_id, node_id, command_type, reason, created_at, expires_at, status,
            is_simulated, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
        """,
        (
            command["command_id"],
            command["node_id"],
            command["command_type"],
            command["reason"],
            command["created_at"],
            command["expires_at"],
            int(command["is_simulated"]),
            command["created_by"],
        ),
    )


def _record(row: sqlite3.Row | None, events: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    if row is None:
        return None
    record = dict(row)
    record["is_simulated"] = bool(record["is_simulated"])
    record["events"] = events or []
    return record


def get_command(connection: sqlite3.Connection, command_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM device_commands WHERE command_id = ?", (command_id,)
    ).fetchone()
    if row is None:
        return None
    events = connection.execute(
        "SELECT * FROM device_command_events WHERE command_id = ? ORDER BY event_at, event_id",
        (command_id,),
    ).fetchall()
    event_records = []
    for event in events:
        item = dict(event)
        item["details"] = json.loads(item.pop("details_json"))
        event_records.append(item)
    return _record(row, event_records)


def list_commands(
    connection: sqlite3.Connection,
    *,
    node_id: str | None,
    status: str | None,
    is_simulated: bool | None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    parameters: list[Any] = []
    for column, value in (
        ("node_id", node_id),
        ("status", status),
        ("is_simulated", None if is_simulated is None else int(is_simulated)),
    ):
        if value is not None:
            clauses.append(f"{column} = ?")
            parameters.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(
        f"SELECT * FROM device_commands {where} ORDER BY created_at DESC, command_id LIMIT ? OFFSET ?",
        (*parameters, limit, offset),
    ).fetchall()
    commands = []
    for row in rows:
        command = _record(row)
        command["events"] = get_command(connection, command["command_id"])["events"]
        commands.append(command)
    return commands


def duplicate_pending(
    connection: sqlite3.Connection,
    *,
    node_id: str,
    command_type: str,
    is_simulated: bool,
) -> bool:
    return connection.execute(
        """SELECT 1 FROM device_commands WHERE node_id = ? AND command_type = ?
           AND is_simulated = ? AND status = 'PENDING' LIMIT 1""",
        (node_id, command_type, int(is_simulated)),
    ).fetchone() is not None


def rate_count(
    connection: sqlite3.Connection, operator_id: str, cutoff: str
) -> int:
    return int(
        connection.execute(
            """SELECT COUNT(*) FROM device_command_events
               WHERE actor = ? AND event_type IN ('CREATED', 'REJECTED') AND event_at >= ?""",
            (operator_id, cutoff),
        ).fetchone()[0]
    )


def expire_due(
    connection: sqlite3.Connection,
    *,
    now: str,
    actor: str,
    node_id: str | None = None,
) -> int:
    clauses = ["status = 'PENDING'", "expires_at <= ?"]
    parameters: list[Any] = [now]
    if node_id is not None:
        clauses.append("node_id = ?")
        parameters.append(node_id)
    rows = connection.execute(
        f"SELECT command_id, node_id FROM device_commands WHERE {' AND '.join(clauses)}",
        parameters,
    ).fetchall()
    for row in rows:
        connection.execute(
            "UPDATE device_commands SET status = 'EXPIRED' WHERE command_id = ? AND status = 'PENDING'",
            (row["command_id"],),
        )
        record_event(
            connection,
            event_id=uuid.uuid4().hex,
            command_id=row["command_id"],
            node_id=row["node_id"],
            event_type="EXPIRED",
            actor=actor,
            event_at=now,
            details={"reason": "command_expiry_elapsed"},
        )
    return len(rows)


def update_status(
    connection: sqlite3.Connection,
    *,
    command_id: str,
    status: str,
    now: str,
    result_summary: str | None,
) -> None:
    if status == "ACKNOWLEDGED":
        connection.execute(
            "UPDATE device_commands SET status = ?, acknowledged_at = ? WHERE command_id = ?",
            (status, now, command_id),
        )
    else:
        connection.execute(
            """UPDATE device_commands SET status = ?, finished_at = ?, result_summary = ?
               WHERE command_id = ?""",
            (status, now, result_summary, command_id),
        )

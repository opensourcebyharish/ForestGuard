"""SQLite data access for alert incidents and their lifecycle."""

import json
import sqlite3
from typing import Any


def _record(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    record = dict(row)
    record["is_simulated"] = bool(record["is_simulated"])
    record["reasons"] = json.loads(record["reasons"])
    return record


def get_open_alert(
    connection: sqlite3.Connection,
    node_id: str,
    is_simulated: bool,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT * FROM alerts
        WHERE node_id = ? AND is_simulated = ? AND status IN ('ACTIVE', 'ACKNOWLEDGED')
        ORDER BY created_at DESC LIMIT 1
        """,
        (node_id, int(is_simulated)),
    ).fetchone()
    return _record(row)


def create_alert(connection: sqlite3.Connection, values: dict[str, Any]) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO alerts (
            alert_id, node_id, severity, risk_score, reasons, created_at, updated_at,
            status, is_simulated, last_reading_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
        """,
        (
            values["alert_id"],
            values["node_id"],
            values["severity"],
            values["risk_score"],
            values["reasons_json"],
            values["timestamp"],
            values["timestamp"],
            int(values["is_simulated"]),
            values["reading_id"],
        ),
    )
    record = get_alert(connection, values["alert_id"])
    if record is None:
        raise RuntimeError("Inserted alert could not be retrieved")
    return record


def get_alert(connection: sqlite3.Connection, alert_id: str) -> dict[str, Any] | None:
    return _record(
        connection.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()
    )


def update_open_alert(
    connection: sqlite3.Connection,
    alert_id: str,
    values: dict[str, Any],
    *,
    reactivate: bool,
) -> dict[str, Any] | None:
    connection.execute(
        """
        UPDATE alerts SET severity = ?, risk_score = ?, reasons = ?, updated_at = ?,
            last_reading_id = ?,
            status = CASE WHEN ? THEN 'ACTIVE' ELSE status END,
            acknowledged_at = CASE WHEN ? THEN NULL ELSE acknowledged_at END
        WHERE alert_id = ? AND status IN ('ACTIVE', 'ACKNOWLEDGED')
        """,
        (
            values["severity"],
            values["risk_score"],
            values["reasons_json"],
            values["timestamp"],
            values["reading_id"],
            int(reactivate),
            int(reactivate),
            alert_id,
        ),
    )
    return get_alert(connection, alert_id)


def acknowledge_alert(
    connection: sqlite3.Connection,
    alert_id: str,
    acknowledged_at: str,
) -> dict[str, Any] | None:
    connection.execute(
        """
        UPDATE alerts SET status = 'ACKNOWLEDGED', updated_at = ?, acknowledged_at = ?
        WHERE alert_id = ? AND status = 'ACTIVE'
        """,
        (acknowledged_at, acknowledged_at, alert_id),
    )
    return get_alert(connection, alert_id)


def resolve_alert(
    connection: sqlite3.Connection,
    alert_id: str,
    resolved_at: str,
    reason: str,
) -> dict[str, Any] | None:
    connection.execute(
        """
        UPDATE alerts SET status = 'RESOLVED', updated_at = ?, resolved_at = ?,
            resolution_reason = ?
        WHERE alert_id = ? AND status IN ('ACTIVE', 'ACKNOWLEDGED')
        """,
        (resolved_at, resolved_at, reason, alert_id),
    )
    return get_alert(connection, alert_id)


def list_alerts(
    connection: sqlite3.Connection,
    *,
    node_id: str | None,
    severity: str | None,
    status: str | None,
    is_simulated: bool | None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    conditions: list[str] = []
    values: list[Any] = []
    for column, value in (
        ("node_id", node_id),
        ("severity", severity),
        ("status", status),
        ("is_simulated", None if is_simulated is None else int(is_simulated)),
    ):
        if value is not None:
            conditions.append(f"{column} = ?")
            values.append(value)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = connection.execute(
        f"SELECT * FROM alerts {where} ORDER BY created_at DESC, alert_id LIMIT ? OFFSET ?",
        (*values, limit, offset),
    ).fetchall()
    return [_record(row) for row in rows if row is not None]


def alert_summary(connection: sqlite3.Connection) -> dict[str, Any]:
    statuses = {
        row["status"]: row["count"]
        for row in connection.execute(
            "SELECT status, COUNT(*) AS count FROM alerts GROUP BY status"
        )
    }
    severities = {
        row["severity"]: row["count"]
        for row in connection.execute(
            """
            SELECT severity, COUNT(*) AS count FROM alerts
            WHERE status IN ('ACTIVE', 'ACKNOWLEDGED') GROUP BY severity
            """
        )
    }
    return {
        "active": statuses.get("ACTIVE", 0),
        "acknowledged": statuses.get("ACKNOWLEDGED", 0),
        "resolved": statuses.get("RESOLVED", 0),
        "by_severity": {
            severity: severities.get(severity, 0) for severity in ("WATCH", "WARNING", "CRITICAL")
        },
    }

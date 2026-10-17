"""SQLite persistence for reading assessments and current station risk state."""

import sqlite3
from typing import Any


def recent_history(
    connection: sqlite3.Connection,
    *,
    node_id: str,
    measured_at: str,
    reading_id: int,
    is_simulated: bool,
    limit: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, measured_at AS timestamp,
               CASE WHEN temperature_available THEN temperature_c END AS temperature_c,
               CASE WHEN humidity_available THEN humidity_percent END AS humidity_percent,
               CASE WHEN smoke_available THEN smoke_value END AS smoke_value,
               gas_value, is_simulated
        FROM readings
        WHERE node_id = ? AND is_simulated = ?
          AND (measured_at < ? OR (measured_at = ? AND id < ?))
        ORDER BY measured_at DESC, id DESC
        LIMIT ?
        """,
        (node_id, int(is_simulated), measured_at, measured_at, reading_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def save_reading_assessment(
    connection: sqlite3.Connection,
    reading_id: int,
    assessment: dict[str, Any],
) -> None:
    connection.execute(
        """
        UPDATE readings SET
            risk_state = ?, risk_score = ?, risk_reasons = ?, risk_signals = ?,
            risk_profile_version = ?, assessment_timestamp = ?, connectivity_state = ?
        WHERE id = ?
        """,
        (
            assessment["risk_state"],
            assessment["risk_score"],
            assessment["reasons_json"],
            assessment["signals_json"],
            assessment["profile_version"],
            assessment["timestamp"],
            assessment["connectivity_state"],
            reading_id,
        ),
    )


def save_node_assessment(
    connection: sqlite3.Connection,
    node_id: str,
    assessment: dict[str, Any],
) -> None:
    connection.execute(
        """
        UPDATE nodes SET current_risk_state = ?, current_risk_score = ?,
            current_risk_reasons = ?, current_risk_profile_version = ?, risk_assessed_at = ?
        WHERE node_id = ?
        """,
        (
            assessment["risk_state"],
            assessment["risk_score"],
            assessment["reasons_json"],
            assessment["profile_version"],
            assessment["timestamp"],
            node_id,
        ),
    )


def consecutive_normal_assessments(
    connection: sqlite3.Connection,
    *,
    node_id: str,
    measured_at: str,
    reading_id: int,
    is_simulated: bool,
    limit: int,
) -> int:
    rows = connection.execute(
        """
        SELECT risk_state FROM readings
        WHERE node_id = ? AND is_simulated = ? AND risk_state IS NOT NULL
          AND (measured_at < ? OR (measured_at = ? AND id <= ?))
        ORDER BY measured_at DESC, id DESC
        LIMIT ?
        """,
        (node_id, int(is_simulated), measured_at, measured_at, reading_id, limit),
    ).fetchall()
    count = 0
    for row in rows:
        if row["risk_state"] != "NORMAL":
            break
        count += 1
    return count

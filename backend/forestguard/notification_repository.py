"""Persistence helpers for Telegram notification outbox events."""

import html
import sqlite3
import uuid
from typing import Any

from forestguard.config import Settings

SEVERITY_RANK = {"WATCH": 1, "WARNING": 2, "CRITICAL": 3}


def _safe_text(value: Any, *, limit: int = 500, multiline: bool = False) -> str:
    text = str(value)
    text = "".join(character for character in text if character in "\n\t" or ord(character) >= 32)
    if not multiline:
        text = " ".join(text.split())
    return html.escape(text[:limit])


def format_alert_message(
    alert: dict[str, Any], station: dict[str, Any] | None, event_type: str
) -> str:
    """Build an escaped Telegram HTML message from an alert snapshot."""
    is_simulated = bool(alert["is_simulated"])
    node_id = _safe_text(alert["node_id"])
    location = ""
    if station is not None:
        location_value = station.get("location")
        if not location_value and station.get("latitude") is not None:
            location_value = f"{station['latitude']}, {station['longitude']} (demo coordinates)"
        if location_value:
            location = f"\nLocation: {_safe_text(location_value)}"
    reasons = alert.get("reasons", [])[:8]
    reason_lines = "\n".join(f"• {_safe_text(reason, limit=300, multiline=True)}" for reason in reasons)
    event_label = "New alert" if event_type == "CREATED" else "Severity escalation"
    simulation_label = "[SIMULATION — NOT A REAL FIRE]\n" if is_simulated else ""
    return (
        f"{simulation_label}<b>ForestGuard {event_label}</b>\n"
        f"Station: {node_id}{location}\n"
        f"Severity: <b>{_safe_text(alert['severity'])}</b> | Risk score: {int(alert['risk_score'])}/100\n"
        f"Created: {_safe_text(alert['created_at'])}\n"
        f"Reasons:\n{reason_lines}\n\n"
        "This is an estimated risk assessment, not confirmation of a fire."
    )


def enqueue_alert_event(
    connection: sqlite3.Connection,
    alert: dict[str, Any],
    *,
    event_type: str,
    reading_id: int,
    settings: Settings,
) -> bool:
    """Add one durable event snapshot; return whether severity meets its threshold."""
    if SEVERITY_RANK[alert["severity"]] < SEVERITY_RANK[settings.telegram_min_severity]:
        return False
    station_row = connection.execute(
        "SELECT name, location, latitude, longitude FROM nodes WHERE node_id = ?",
        (alert["node_id"],),
    ).fetchone()
    station = dict(station_row) if station_row else None
    event_key = (
        f"{alert['alert_id']}:created"
        if event_type == "CREATED"
        else f"{alert['alert_id']}:escalated:{reading_id}"
    )
    if not settings.telegram_enabled:
        status, reason = "SKIPPED", "Telegram notifications are disabled."
    elif not settings.telegram_bot_token or not settings.telegram_chat_id:
        status, reason = "SKIPPED", "Telegram is enabled but credentials are incomplete."
    else:
        status, reason = "PENDING", None
    message = format_alert_message(alert, station, event_type)
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO notification_log (
            notification_id, event_key, alert_id, event_type, severity, risk_score,
            is_simulated, message_text, status, attempts, created_at, updated_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            event_key,
            alert["alert_id"],
            event_type,
            alert["severity"],
            alert["risk_score"],
            int(alert["is_simulated"]),
            message,
            status,
            alert["created_at"] if event_type == "CREATED" else alert["updated_at"],
            alert["created_at"] if event_type == "CREATED" else alert["updated_at"],
            reason,
        ),
    )
    return cursor.rowcount == 1


def claim_next(
    connection: sqlite3.Connection, now: str, stale_before: str
) -> dict[str, Any] | None:
    """Atomically claim one due event so competing workers cannot dispatch it twice."""
    connection.execute("BEGIN IMMEDIATE")
    connection.execute(
        """
        UPDATE notification_log SET status = 'FAILED', updated_at = ?,
            sending_started_at = NULL,
            last_error = 'Delivery attempt expired without a recorded outcome.'
        WHERE status = 'SENDING' AND sending_started_at < ?
        """,
        (now, stale_before),
    )
    row = connection.execute(
        """
        SELECT * FROM notification_log
        WHERE status = 'PENDING' AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
        ORDER BY created_at, notification_id LIMIT 1
        """,
        (now,),
    ).fetchone()
    if row is None:
        return None
    changed = connection.execute(
        """
        UPDATE notification_log
        SET status = 'SENDING', attempts = attempts + 1, updated_at = ?, sending_started_at = ?
        WHERE notification_id = ? AND status = 'PENDING'
        """,
        (now, now, row["notification_id"]),
    ).rowcount
    if changed != 1:
        return None
    result = dict(row)
    result["attempts"] += 1
    return result


def finish_attempt(
    connection: sqlite3.Connection,
    notification_id: str,
    *,
    sent: bool,
    now: str,
    error: str | None,
) -> None:
    connection.execute(
        """
        UPDATE notification_log SET status = ?, updated_at = ?, sent_at = ?,
            sending_started_at = NULL, next_attempt_at = NULL, last_error = ?
        WHERE notification_id = ? AND status = 'SENDING'
        """,
        (
            "SENT" if sent else "FAILED",
            now,
            now if sent else None,
            error[:300] if error else None,
            notification_id,
        ),
    )


def skip_pending(connection: sqlite3.Connection, now: str, reason: str) -> int:
    """Close queued work as skipped when this process cannot deliver notifications."""
    return connection.execute(
        """
        UPDATE notification_log SET status = 'SKIPPED', updated_at = ?, last_error = ?
        WHERE status = 'PENDING'
        """,
        (now, reason),
    ).rowcount


def list_notification_log(connection: sqlite3.Connection, alert_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM notification_log WHERE alert_id = ? ORDER BY created_at, notification_id",
        (alert_id,),
    ).fetchall()
    return [dict(row) for row in rows]

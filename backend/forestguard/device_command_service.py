"""Transactional command lifecycle and server-authored audit workflows."""

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from forestguard import device_command_repository as repository
from forestguard.config import Settings
from forestguard.database import connect
from forestguard.schemas import DeviceCommandAcknowledgement, DeviceCommandCreate, utc_iso, utc_now


class DeviceCommandError(Exception):
    """Base error for command lifecycle conflicts."""


class CommandNodeNotFound(DeviceCommandError):
    pass


class CommandNotFound(DeviceCommandError):
    pass


class CommandsDisabled(DeviceCommandError):
    pass


class CommandTooLong(DeviceCommandError):
    pass


class DuplicatePendingCommand(DeviceCommandError):
    pass


class CommandRateLimitExceeded(DeviceCommandError):
    pass


class CommandStateConflict(DeviceCommandError):
    pass


def _event(
    connection: sqlite3.Connection,
    *,
    command_id: str | None,
    node_id: str | None,
    event_type: str,
    actor: str,
    now: str,
    details: dict[str, Any],
) -> None:
    repository.record_event(
        connection,
        event_id=uuid.uuid4().hex,
        command_id=command_id,
        node_id=node_id,
        event_type=event_type,
        actor=actor,
        event_at=now,
        details=details,
    )


def record_unauthorized_attempt(database_path: Path, node_id: str | None) -> None:
    """Audit failed bearer authorization without storing caller input or credentials."""
    now = utc_iso(utc_now())
    with connect(database_path) as connection:
        _event(
            connection,
            command_id=None,
            node_id=node_id,
            event_type="REJECTED",
            actor="unauthorized",
            now=now,
            details={"reason": "authorization_failed"},
        )


def create_command(
    database_path: Path,
    node_id: str,
    payload: DeviceCommandCreate,
    *,
    operator_id: str,
    settings: Settings,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or utc_now()).astimezone(timezone.utc)
    created_at = utc_iso(current)
    expires_at = utc_iso(current + timedelta(seconds=payload.expires_in_seconds))
    command_id = uuid.uuid4().hex
    error: DeviceCommandError | None = None
    result: dict[str, Any] | None = None
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        repository.expire_due(
            connection, now=created_at, actor=operator_id, node_id=node_id
        )
        if not payload.is_simulated and not settings.device_commands_enabled:
            error = CommandsDisabled("Real device commands are disabled")
        elif payload.expires_in_seconds > settings.device_command_max_expiry_seconds:
            error = CommandTooLong("Command expiry exceeds the configured maximum")
        elif connection.execute("SELECT 1 FROM nodes WHERE node_id = ?", (node_id,)).fetchone() is None:
            error = CommandNodeNotFound(node_id)
        else:
            cutoff = utc_iso(
                current - timedelta(seconds=settings.device_command_rate_window_seconds)
            )
            if repository.rate_count(connection, operator_id, cutoff) >= settings.device_command_rate_limit:
                error = CommandRateLimitExceeded("Device command rate limit exceeded")
            elif repository.duplicate_pending(
                connection,
                node_id=node_id,
                command_type=payload.command_type,
                is_simulated=payload.is_simulated,
            ):
                error = DuplicatePendingCommand("An equivalent command is already pending")
            else:
                command = {
                    "command_id": command_id,
                    "node_id": node_id,
                    "command_type": payload.command_type,
                    "reason": payload.reason,
                    "created_at": created_at,
                    "expires_at": expires_at,
                    "is_simulated": payload.is_simulated,
                    "created_by": operator_id,
                }
                repository.add_command(connection, command)
                _event(
                    connection,
                    command_id=command_id,
                    node_id=node_id,
                    event_type="CREATED",
                    actor=operator_id,
                    now=created_at,
                    details={
                        "command_type": payload.command_type,
                        "reason": payload.reason,
                        "is_simulated": payload.is_simulated,
                        "execution_state": "NOT_DISPATCHED",
                    },
                )
                result = repository.get_command(connection, command_id)
        if error is not None:
            _event(
                connection,
                command_id=None,
                node_id=node_id,
                event_type="REJECTED",
                actor=operator_id,
                now=created_at,
                details={"reason": type(error).__name__},
            )
    if error is not None:
        raise error
    if result is None:
        raise RuntimeError("Created command could not be retrieved")
    return result


def acknowledge_command(
    database_path: Path,
    command_id: str,
    payload: DeviceCommandAcknowledgement,
    *,
    operator_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or utc_now()).astimezone(timezone.utc)
    now_text = utc_iso(current)
    error: DeviceCommandError | None = None
    result: dict[str, Any] | None = None
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        command = repository.get_command(connection, command_id)
        if command is None:
            error = CommandNotFound(command_id)
        elif command["status"] == "PENDING" and command["expires_at"] <= now_text:
            connection.execute(
                "UPDATE device_commands SET status = 'EXPIRED' WHERE command_id = ? AND status = 'PENDING'",
                (command_id,),
            )
            _event(
                connection,
                command_id=command_id,
                node_id=command["node_id"],
                event_type="EXPIRED",
                actor=operator_id,
                now=now_text,
                details={"reason": "command_expiry_elapsed"},
            )
            error = CommandStateConflict("Expired commands cannot be acknowledged")
        elif payload.status == "ACKNOWLEDGED" and command["status"] == "PENDING":
            repository.update_status(
                connection,
                command_id=command_id,
                status="ACKNOWLEDGED",
                now=now_text,
                result_summary=payload.result_summary,
            )
            _event(
                connection,
                command_id=command_id,
                node_id=command["node_id"],
                event_type="ACKNOWLEDGED",
                actor=operator_id,
                now=now_text,
                details={"status": "ACKNOWLEDGED"},
            )
            result = repository.get_command(connection, command_id)
        elif payload.status in {"COMPLETED", "FAILED"} and command["status"] == "ACKNOWLEDGED":
            repository.update_status(
                connection,
                command_id=command_id,
                status=payload.status,
                now=now_text,
                result_summary=payload.result_summary,
            )
            _event(
                connection,
                command_id=command_id,
                node_id=command["node_id"],
                event_type=payload.status,
                actor=operator_id,
                now=now_text,
                details={"result_summary": payload.result_summary, "externally_reported": True},
            )
            result = repository.get_command(connection, command_id)
        else:
            error = CommandStateConflict("Command state does not allow the requested transition")
            _event(
                connection,
                command_id=command_id,
                node_id=command["node_id"],
                event_type="REJECTED",
                actor=operator_id,
                now=now_text,
                details={"reason": type(error).__name__, "requested_status": payload.status},
            )
    if error is not None:
        raise error
    if result is None:
        raise RuntimeError("Updated command could not be retrieved")
    return result


def list_commands(
    database_path: Path,
    *,
    node_id: str | None,
    status: str | None,
    is_simulated: bool | None,
    limit: int,
    offset: int,
    operator_id: str,
) -> list[dict[str, Any]]:
    now = utc_iso(utc_now())
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        repository.expire_due(connection, now=now, actor=operator_id)
        return repository.list_commands(
            connection,
            node_id=node_id,
            status=status,
            is_simulated=is_simulated,
            limit=limit,
            offset=offset,
        )

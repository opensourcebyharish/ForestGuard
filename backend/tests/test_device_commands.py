"""Security and lifecycle checks for the non-actuating device command API."""

import json

import pytest
from forestguard.config import Settings
from forestguard.database import connect, initialize_database
from forestguard.main import app
from forestguard.routes.commands import get_settings as command_settings_dependency

TEST_TOKEN = "test-command-token"
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture
def command_api(client, monkeypatch, tmp_path):
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "forestguard.sqlite3",
        device_commands_auth_token=TEST_TOKEN,
        device_commands_operator_id="operator-from-server",
    )
    monkeypatch.setitem(
        app.dependency_overrides, command_settings_dependency, lambda: settings
    )
    return client, settings


def register_station(client, node_id="command-node"):
    response = client(
        "POST", "/api/nodes", json={"node_id": node_id, "name": "Command Station"}
    )
    assert response.status_code == 201
    return node_id


def create_payload(**overrides):
    return {
        "command_type": "REQUEST_STATUS",
        "reason": "Operator requested a health check",
        "expires_in_seconds": 300,
        "is_simulated": True,
        **overrides,
    }


def audit_events(path, command_id):
    with connect(path) as connection:
        return connection.execute(
            "SELECT event_type, actor, details_json FROM device_command_events "
            "WHERE command_id = ? ORDER BY event_at, event_id",
            (command_id,),
        ).fetchall()


def test_authorization_and_real_commands_are_disabled_by_default(command_api):
    client, settings = command_api
    node_id = register_station(client)

    assert settings.device_commands_enabled is False
    denied = client("POST", f"/api/nodes/{node_id}/commands", json=create_payload(is_simulated=False), headers=AUTH)
    assert denied.status_code == 403
    unauthenticated = client(
        "POST", f"/api/nodes/{node_id}/commands", json=create_payload(), headers={"Authorization": "Bearer wrong"}
    )
    assert unauthenticated.status_code == 401

    with connect(settings.database_path) as connection:
        events = connection.execute(
            "SELECT actor, details_json FROM device_command_events WHERE event_type = 'REJECTED'"
        ).fetchall()
    assert len(events) == 2
    assert all(TEST_TOKEN not in row["details_json"] for row in events)
    assert json.loads(events[0]["details_json"])["reason"] == "CommandsDisabled"
    assert json.loads(events[1]["details_json"])["reason"] == "authorization_failed"


def test_simulated_command_has_provenance_and_safe_audited_transitions(command_api):
    client, settings = command_api
    node_id = register_station(client)
    created = client(
        "POST", f"/api/nodes/{node_id}/commands",
        json=create_payload(), headers=AUTH,
    )
    assert created.status_code == 201
    command = created.json()
    assert command["is_simulated"] is True
    assert command["created_by"] == "operator-from-server"
    assert command["execution_state"] == "NOT_DISPATCHED"
    assert [event["event_type"] for event in command["events"]] == ["CREATED"]

    premature_finish = client(
        "POST", f"/api/commands/{command['command_id']}/ack",
        json={"status": "COMPLETED", "result_summary": "Reported complete"}, headers=AUTH,
    )
    assert premature_finish.status_code == 409
    acknowledged = client(
        "POST", f"/api/commands/{command['command_id']}/ack",
        json={"status": "ACKNOWLEDGED"}, headers=AUTH,
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "ACKNOWLEDGED"
    duplicate_ack = client(
        "POST", f"/api/commands/{command['command_id']}/ack",
        json={"status": "ACKNOWLEDGED"}, headers=AUTH,
    )
    assert duplicate_ack.status_code == 409
    completed = client(
        "POST", f"/api/commands/{command['command_id']}/ack",
        json={"status": "COMPLETED", "result_summary": "Externally reported complete"}, headers=AUTH,
    )
    assert completed.status_code == 200
    assert completed.json()["execution_state"] == "NOT_DISPATCHED"
    assert [event["event_type"] for event in completed.json()["events"]] == [
        "CREATED", "REJECTED", "ACKNOWLEDGED", "REJECTED", "COMPLETED"
    ]
    assert json.loads(audit_events(settings.database_path, command["command_id"])[4]["details_json"])[
        "externally_reported"
    ] is True
    listing = client(
        "GET", "/api/commands?is_simulated=true&status=COMPLETED&limit=1&offset=0", headers=AUTH
    ).json()
    assert listing["limit"] == 1
    assert listing["offset"] == 0
    assert len(listing["items"]) == 1
    assert listing["items"][0]["command_id"] == command["command_id"]


def test_enabled_real_command_is_still_only_recorded_not_dispatched(command_api, monkeypatch):
    client, settings = command_api
    node_id = register_station(client)
    enabled = settings.model_copy(update={"device_commands_enabled": True})
    monkeypatch.setitem(
        app.dependency_overrides, command_settings_dependency, lambda: enabled
    )
    response = client(
        "POST", f"/api/nodes/{node_id}/commands",
        json=create_payload(is_simulated=False), headers=AUTH,
    )
    assert response.status_code == 201
    assert response.json()["is_simulated"] is False
    assert response.json()["execution_state"] == "NOT_DISPATCHED"


def test_invalid_payload_unknown_station_and_duplicate_pending_are_rejected(command_api):
    client, _settings = command_api
    node_id = register_station(client)
    invalid = client(
        "POST", f"/api/nodes/{node_id}/commands",
        json=create_payload(command_type="PUMP_ON"), headers=AUTH,
    )
    assert invalid.status_code == 422
    missing = client(
        "POST", "/api/nodes/missing-node/commands", json=create_payload(), headers=AUTH
    )
    assert missing.status_code == 404
    too_short = client(
        "POST", f"/api/nodes/{node_id}/commands",
        json=create_payload(expires_in_seconds=1), headers=AUTH,
    )
    assert too_short.status_code == 422

    first = client(
        "POST", f"/api/nodes/{node_id}/commands", json=create_payload(), headers=AUTH
    )
    duplicate = client(
        "POST", f"/api/nodes/{node_id}/commands", json=create_payload(), headers=AUTH
    )
    assert first.status_code == 201
    assert duplicate.status_code == 409


def test_expired_command_cannot_be_acknowledged(command_api):
    client, settings = command_api
    node_id = register_station(client)
    created = client(
        "POST", f"/api/nodes/{node_id}/commands", json=create_payload(), headers=AUTH
    ).json()
    with connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE device_commands SET created_at = '1999-01-01T00:00:00Z', "
            "expires_at = '2000-01-01T00:00:00Z' WHERE command_id = ?",
            (created["command_id"],),
        )

    response = client(
        "POST", f"/api/commands/{created['command_id']}/ack",
        json={"status": "ACKNOWLEDGED"}, headers=AUTH,
    )
    assert response.status_code == 409
    listing = client("GET", "/api/commands", headers=AUTH).json()
    assert listing["items"][0]["status"] == "EXPIRED"
    assert [event["event_type"] for event in listing["items"][0]["events"]] == [
        "CREATED", "EXPIRED"
    ]


def test_command_rate_limit_is_audited(command_api, monkeypatch):
    client, settings = command_api
    node_id = register_station(client)
    limited = settings.model_copy(update={"device_command_rate_limit": 1})
    monkeypatch.setitem(
        app.dependency_overrides, command_settings_dependency, lambda: limited
    )
    first = client(
        "POST", f"/api/nodes/{node_id}/commands", json=create_payload(), headers=AUTH
    )
    assert first.status_code == 201
    second = client(
        "POST", f"/api/nodes/{node_id}/commands",
        json=create_payload(command_type="SENSOR_SELF_TEST"), headers=AUTH,
    )
    assert second.status_code == 429
    with connect(settings.database_path) as connection:
        rejection = connection.execute(
            "SELECT details_json FROM device_command_events WHERE event_type = 'REJECTED'"
        ).fetchone()
    assert json.loads(rejection["details_json"])["reason"] == "CommandRateLimitExceeded"


def test_command_migration_is_repeatable_and_preserves_phase_six_outbox(tmp_path):
    path = tmp_path / "migration.sqlite3"
    initialize_database(path)
    with connect(path) as connection:
        connection.execute(
            "INSERT INTO nodes (node_id, name, created_at, updated_at) "
            "VALUES ('preserved-node', 'Preserved', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )
        connection.execute(
            "INSERT INTO alerts (alert_id, node_id, severity, risk_score, reasons, created_at, "
            "updated_at, status, is_simulated) VALUES ('preserved-alert', 'preserved-node', "
            "'WARNING', 60, '[]', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 'ACTIVE', 1)"
        )
        connection.execute(
            "INSERT INTO notification_log (notification_id, event_key, alert_id, event_type, "
            "severity, risk_score, is_simulated, message_text, status, created_at, updated_at) "
            "VALUES ('preserved-notification', 'preserved-event', 'preserved-alert', 'CREATED', "
            "'WARNING', 60, 1, 'queued message', 'PENDING', '2026-01-01T00:00:00Z', "
            "'2026-01-01T00:00:00Z')"
        )
        connection.execute("DROP TABLE device_command_events")
        connection.execute("DROP TABLE device_commands")
        connection.execute("DELETE FROM schema_migrations WHERE version = 5")
    initialize_database(path)
    initialize_database(path)
    with connect(path) as connection:
        assert connection.execute(
            "SELECT name FROM nodes WHERE node_id = 'preserved-node'"
        ).fetchone()["name"] == "Preserved"
        assert connection.execute(
            "SELECT message_text FROM notification_log WHERE notification_id = 'preserved-notification'"
        ).fetchone()["message_text"] == "queued message"
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 5"
        ).fetchone()[0] == 1
        tables = {row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "notification_log" in tables
        assert "device_commands" in tables

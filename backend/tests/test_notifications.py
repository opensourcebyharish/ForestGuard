"""Telegram outbox, security, delivery, and integration tests."""

import json
from urllib.error import HTTPError, URLError

import pytest
from forestguard.config import Settings
from forestguard.database import connect, initialize_database
from forestguard.notification_repository import format_alert_message
from forestguard.notifications import (
    TelegramDeliveryError,
    dispatch_one,
    notification_availability,
    send_telegram_message,
)


def configured_settings(path, **overrides):
    return Settings(
        _env_file=None,
        database_path=path,
        telegram_enabled=True,
        telegram_bot_token="123456:TEST_TOKEN",
        telegram_chat_id="-100123",
        **overrides,
    )


def payload(**overrides):
    reading = {
        "node_id": "notify-node",
        "temperature_c": 22,
        "humidity_percent": 60,
        "smoke_value": 50,
        "gas_value": None,
        "timestamp": "2026-10-15T10:00:00Z",
        "is_simulated": True,
    }
    reading.update(overrides)
    return reading


def post(client, **overrides):
    response = client("POST", "/api/readings", json=payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def notification_rows(path):
    with connect(path) as connection:
        return connection.execute(
            "SELECT status, event_type, severity, is_simulated, attempts, message_text, last_error "
            "FROM notification_log ORDER BY created_at, notification_id"
        ).fetchall()


def make_warning(client):
    return post(
        client,
        temperature_c=51,
        humidity_percent=20,
        smoke_value=50,
        gas_value=None,
    )


def configure_test_outbox(monkeypatch, settings):
    monkeypatch.setattr("forestguard.routes.readings.get_settings", lambda: settings)
    monkeypatch.setattr("forestguard.main.get_settings", lambda: settings)
    # Tests dispatch explicitly with a mocked sender instead of starting network workers.
    monkeypatch.setattr("forestguard.main.NotificationWorker.start", lambda _worker: None)


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.body


def test_notifications_disabled_by_default_and_missing_credentials_are_unavailable(tmp_path):
    defaults = Settings(_env_file=None, database_path=tmp_path / "default.sqlite3")
    incomplete = Settings(
        _env_file=None,
        database_path=tmp_path / "incomplete.sqlite3",
        telegram_enabled=True,
        telegram_bot_token="",
        telegram_chat_id=None,
    )
    assert defaults.telegram_enabled is False
    assert notification_availability(defaults) == "disabled"
    assert notification_availability(incomplete) == "unavailable: Telegram credentials are incomplete"
    assert incomplete.telegram_available is False


def test_telegram_success_uses_mocked_http_and_never_logs_token():
    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(b'{"ok":true,"result":{}}')

    send_telegram_message(
        token="secret-token",
        chat_id="chat-1",
        message="[SIMULATION — NOT A REAL FIRE]",
        timeout=2,
        retries=0,
        opener=opener,
    )
    request, timeout = calls[0]
    assert request.full_url.endswith("/sendMessage")
    assert json.loads(request.data)["text"] == "[SIMULATION — NOT A REAL FIRE]"
    assert json.loads(request.data)["chat_id"] == "chat-1"
    assert timeout == 2


def test_message_escapes_location_and_labels_simulated_alert():
    message = format_alert_message(
        {
            "alert_id": "a1",
            "node_id": "FG-SIM-001",
            "severity": "WARNING",
            "risk_score": 55,
            "reasons": ["<script>unsafe</script>"],
            "created_at": "2026-10-15T10:00:00Z",
            "is_simulated": True,
        },
        {"location": "<b>untrusted place</b>", "latitude": None, "longitude": None},
        "CREATED",
    )
    assert "[SIMULATION — NOT A REAL FIRE]" in message
    assert "<b>untrusted place</b>" not in message
    assert "&lt;b&gt;untrusted place&lt;/b&gt;" in message
    assert "&lt;script&gt;unsafe&lt;/script&gt;" in message


def test_telegram_rejection_is_sanitized():
    def opener(*_args, **_kwargs):
        raise HTTPError("https://telegram.test/botsecret-token/sendMessage", 403, "denied", {}, None)

    with pytest.raises(TelegramDeliveryError) as raised:
        send_telegram_message(
            token="secret-token", chat_id="chat", message="text", timeout=1, retries=0, opener=opener
        )
    assert "403" in str(raised.value)
    assert "secret-token" not in str(raised.value)


@pytest.mark.parametrize("failure", [TimeoutError("slow"), URLError("unreachable")])
def test_network_errors_retry_only_to_configured_limit(failure):
    attempts = []

    def opener(*_args, **_kwargs):
        attempts.append(1)
        raise failure

    with pytest.raises(TelegramDeliveryError) as raised:
        send_telegram_message(
            token="secret-token",
            chat_id="chat",
            message="text",
            timeout=0.5,
            retries=2,
            opener=opener,
            sleep=lambda _seconds: None,
        )
    assert len(attempts) == 3
    assert "secret-token" not in str(raised.value)


def test_http_server_failure_obeys_retry_limit():
    attempts = []

    def opener(*_args, **_kwargs):
        attempts.append(1)
        raise HTTPError("https://telegram.test", 503, "unavailable", {}, None)

    with pytest.raises(TelegramDeliveryError):
        send_telegram_message(
            token="token", chat_id="chat", message="text", timeout=1, retries=1,
            opener=opener, sleep=lambda _seconds: None
        )
    assert len(attempts) == 2


def test_plain_readings_do_not_create_notifications(client, tmp_path):
    post(client)
    assert notification_rows(tmp_path / "forestguard.sqlite3") == []


def test_simulated_eligible_alert_is_logged_skipped_when_notifications_disabled(client, tmp_path):
    assessment = post(client, temperature_c=51, humidity_percent=20)
    rows = notification_rows(tmp_path / "forestguard.sqlite3")
    assert assessment["risk_state"] == "WARNING"
    assert len(rows) == 1
    assert rows[0]["status"] == "SKIPPED"
    assert rows[0]["is_simulated"] == 1
    assert "[SIMULATION — NOT A REAL FIRE]" in rows[0]["message_text"]


def test_incomplete_credentials_keep_ingestion_available_and_log_skip(client, monkeypatch, tmp_path):
    from forestguard.routes import readings

    incomplete = Settings(
        _env_file=None,
        database_path=tmp_path / "forestguard.sqlite3",
        telegram_enabled=True,
    )
    monkeypatch.setattr("forestguard.routes.readings.get_settings", lambda: incomplete)
    assert post(client, temperature_c=51, humidity_percent=20)["risk_state"] == "WARNING"
    assert notification_rows(incomplete.database_path)[0]["status"] == "SKIPPED"
    assert readings.get_settings().telegram_bot_token is None


def test_new_alert_is_queued_once_and_ordinary_repeat_does_not_duplicate(client, monkeypatch, tmp_path):
    settings = configured_settings(tmp_path / "forestguard.sqlite3")
    configure_test_outbox(monkeypatch, settings)
    initial = make_warning(client)
    assert initial["risk_state"] == "WARNING"
    post(
        client,
        temperature_c=51,
        humidity_percent=20,
        smoke_value=50,
        gas_value=None,
    )
    rows = notification_rows(settings.database_path)
    assert len(rows) == 1
    assert rows[0]["status"] == "PENDING"
    assert rows[0]["event_type"] == "CREATED"
    assert rows[0]["severity"] == "WARNING"


def test_severity_escalation_adds_one_event_and_labels_simulation(client, monkeypatch, tmp_path):
    settings = configured_settings(tmp_path / "forestguard.sqlite3")
    configure_test_outbox(monkeypatch, settings)
    make_warning(client)
    elevated = post(
        client,
        temperature_c=51,
        humidity_percent=20,
        smoke_value=500,
        gas_value=500,
    )
    assert elevated["risk_state"] == "CRITICAL"
    rows = notification_rows(settings.database_path)
    assert [(row["event_type"], row["severity"]) for row in rows] == [
        ("CREATED", "WARNING"),
        ("ESCALATED", "CRITICAL"),
    ]
    assert all(row["is_simulated"] == 1 for row in rows)
    assert all("[SIMULATION — NOT A REAL FIRE]" in row["message_text"] for row in rows)


def test_failed_telegram_delivery_does_not_fail_ingestion_and_is_persisted(
    client, monkeypatch, tmp_path
):
    settings = configured_settings(tmp_path / "forestguard.sqlite3")
    configure_test_outbox(monkeypatch, settings)
    reading = make_warning(client)
    assert reading["risk_state"] == "WARNING"

    def fail_delivery(**_kwargs):
        raise TelegramDeliveryError("Telegram returned HTTP 503.")

    assert dispatch_one(settings.database_path, settings, sender=fail_delivery) is True
    rows = notification_rows(settings.database_path)
    assert rows[0]["status"] == "FAILED"
    assert rows[0]["attempts"] == 1
    assert rows[0]["last_error"] == "Telegram returned HTTP 503."
    assert client("GET", "/api/readings?node_id=notify-node").json()["items"]


def test_claimed_notification_cannot_be_dispatched_twice(client, monkeypatch, tmp_path):
    settings = configured_settings(tmp_path / "forestguard.sqlite3")
    configure_test_outbox(monkeypatch, settings)
    make_warning(client)
    sends = []

    def sender(**kwargs):
        sends.append(kwargs["message"])
        assert dispatch_one(settings.database_path, settings, sender=sender) is False

    assert dispatch_one(settings.database_path, settings, sender=sender) is True
    assert len(sends) == 1
    assert notification_rows(settings.database_path)[0]["status"] == "SENT"


def test_notification_log_migration_is_additive_idempotent_and_preserves_alerts(tmp_path):
    path = tmp_path / "existing-v3.sqlite3"
    initialize_database(path)
    with connect(path) as connection:
        connection.execute(
            "INSERT INTO nodes (node_id, name, created_at, updated_at) "
            "VALUES ('preserved', 'Preserved station', 'created', 'updated')"
        )
        connection.execute(
            "INSERT INTO alerts (alert_id, node_id, severity, risk_score, reasons, created_at, "
            "updated_at, status, is_simulated) VALUES ('keep-alert', 'preserved', 'WARNING', "
            "50, '[]', 'created', 'updated', 'ACTIVE', 0)"
        )
        connection.execute("DELETE FROM schema_migrations WHERE version = 5")
    initialize_database(path)
    initialize_database(path)
    with connect(path) as connection:
        alert = connection.execute("SELECT alert_id, severity FROM alerts").fetchone()
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'notification_log'"
        ).fetchone()
    assert tuple(alert) == ("keep-alert", "WARNING")
    assert [row[0] for row in versions] == [1, 2, 3, 4, 5]
    assert table is not None

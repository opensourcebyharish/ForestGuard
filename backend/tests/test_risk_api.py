"""Integration coverage for persisted assessments and the alert lifecycle."""

from typing import Any

OPERATOR_HEADERS = {"Authorization": "Bearer test-operator-token"}


def reading_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "node_id": "ridge-1",
        "temperature_c": 22,
        "humidity_percent": 60,
        "smoke_value": 50,
        "gas_value": None,
        "timestamp": "2026-10-15T10:00:00Z",
        "is_simulated": False,
    }
    payload.update(overrides)
    return payload


def submit(client, **overrides: Any) -> dict[str, Any]:
    response = client("POST", "/api/readings", json=reading_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def test_ingestion_persists_explainable_assessment_and_station_state(client) -> None:
    reading = submit(client)
    node = client("GET", "/api/nodes/ridge-1").json()

    assert reading["risk_state"] == "NORMAL"
    assert reading["risk_score"] == 0
    assert reading["risk_profile_version"] == "demo-v1"
    assert reading["assessment_timestamp"].endswith("Z")
    assert reading["connectivity_state"] == "ONLINE"
    assert {signal["name"] for signal in reading["risk_signals"]} >= {
        "temperature_elevated",
        "humidity_low",
        "smoke_elevated",
        "gas_elevated",
        "data_completeness",
    }
    assert node["current_risk_state"] == "NORMAL"
    assert node["connectivity_state"] == "ONLINE"
    assert client("GET", "/api/alerts/summary").json()["active"] == 0

    persisted = client("GET", "/api/readings?node_id=ridge-1").json()["items"][0]
    assert persisted["risk_state"] == "NORMAL"
    assert persisted["risk_reasons"] == reading["risk_reasons"]


def test_missing_smoke_is_persisted_as_missing_and_never_treated_as_safe(client) -> None:
    reading = submit(client, smoke_value=None)
    node = client("GET", "/api/nodes/ridge-1").json()

    assert reading["smoke_value"] is None
    assert reading["smoke_available"] is False
    assert reading["risk_state"] == "WATCH"
    assert any("not evidence of clean air" in reason for reason in reading["risk_reasons"])
    assert node["latest_smoke_value"] is None
    assert node["latest_smoke_available"] is False


def test_alert_is_deduplicated_and_updates_on_escalation(client) -> None:
    first = submit(client, smoke_value=400)
    alert = client("GET", "/api/alerts?status=ACTIVE").json()["items"][0]
    second = submit(client, timestamp="2026-10-15T10:01:00Z", smoke_value=400)
    third = submit(client, timestamp="2026-10-15T10:02:00Z", smoke_value=400)

    alerts = client("GET", "/api/alerts?node_id=ridge-1&is_simulated=false").json()
    summary = client("GET", "/api/alerts/summary").json()

    assert first["risk_state"] == "WATCH"
    assert second["risk_state"] == "WATCH"
    assert third["risk_state"] == "CRITICAL"
    assert len(alerts["items"]) == 1
    assert alerts["items"][0]["alert_id"] == alert["alert_id"]
    assert alerts["items"][0]["severity"] == "CRITICAL"
    assert summary["active"] == 1
    assert summary["by_severity"]["CRITICAL"] == 1


def test_acknowledgement_is_idempotent_and_escalation_reactivates_alert(client) -> None:
    submit(client, smoke_value=400)
    alert = client("GET", "/api/alerts").json()["items"][0]
    ack = client(
        "POST", f"/api/alerts/{alert['alert_id']}/acknowledge", headers=OPERATOR_HEADERS
    )
    repeated_ack = client(
        "POST", f"/api/alerts/{alert['alert_id']}/acknowledge", headers=OPERATOR_HEADERS
    )

    assert ack.status_code == 200
    assert ack.json()["status"] == "ACKNOWLEDGED"
    assert repeated_ack.json()["acknowledged_at"] == ack.json()["acknowledged_at"]

    submit(
        client,
        timestamp="2026-10-15T10:01:00Z",
        temperature_c=50,
        humidity_percent=20,
        smoke_value=400,
    )
    escalated = client("GET", "/api/alerts").json()["items"][0]

    assert escalated["alert_id"] == alert["alert_id"]
    assert escalated["severity"] == "CRITICAL"
    assert escalated["status"] == "ACTIVE"
    assert escalated["acknowledged_at"] is None


def test_two_consecutive_normal_readings_resolve_an_incident(client) -> None:
    submit(client, smoke_value=400)
    alert = client("GET", "/api/alerts").json()["items"][0]

    first_normal = submit(client, timestamp="2026-10-15T10:01:00Z")
    still_open = client("GET", "/api/alerts").json()["items"][0]
    second_normal = submit(client, timestamp="2026-10-15T10:02:00Z")
    resolved = client("GET", "/api/alerts?status=RESOLVED").json()["items"][0]

    assert first_normal["risk_state"] == "NORMAL"
    assert still_open["status"] == "ACTIVE"
    assert second_normal["risk_state"] == "NORMAL"
    assert resolved["alert_id"] == alert["alert_id"]
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution_reason"] == "Risk returned to NORMAL for 2 consecutive readings."
    assert client("GET", "/api/alerts/summary").json()["active"] == 0


def test_historical_reading_is_assessed_but_cannot_change_current_state_or_alert(client) -> None:
    submit(client, timestamp="2026-10-15T10:00:00Z", smoke_value=400)
    current = submit(client, timestamp="2026-10-15T10:02:00Z")
    before = client("GET", "/api/alerts").json()["items"][0]

    historical = submit(
        client,
        timestamp="2026-10-15T10:01:00Z",
        temperature_c=50,
        humidity_percent=20,
        smoke_value=400,
    )
    node = client("GET", "/api/nodes/ridge-1").json()
    after = client("GET", "/api/alerts").json()["items"][0]

    assert current["risk_state"] == "NORMAL"
    assert historical["risk_state"] == "CRITICAL"
    assert node["latest_reading_at"] == "2026-10-15T10:02:00Z"
    assert node["current_risk_state"] == "NORMAL"
    assert after["alert_id"] == before["alert_id"]
    assert after["updated_at"] == before["updated_at"]


def test_simulated_and_hardware_incidents_are_separate(client) -> None:
    simulated = submit(client, smoke_value=400, is_simulated=True)
    hardware = submit(
        client,
        timestamp="2026-10-15T10:01:00Z",
        smoke_value=400,
        is_simulated=False,
    )
    alerts = client("GET", "/api/alerts?node_id=ridge-1").json()["items"]

    assert simulated["risk_state"] == "WATCH"
    assert hardware["risk_state"] == "WATCH"
    assert len(alerts) == 2
    assert {item["is_simulated"] for item in alerts} == {False, True}


def test_alert_acknowledgement_reports_missing_and_resolved_alerts(client) -> None:
    assert client(
        "POST", "/api/alerts/missing/acknowledge", headers=OPERATOR_HEADERS
    ).status_code == 404
    submit(client, smoke_value=400)
    alert = client("GET", "/api/alerts").json()["items"][0]
    client(
        "POST", f"/api/alerts/{alert['alert_id']}/acknowledge", headers=OPERATOR_HEADERS
    )
    submit(client, timestamp="2026-10-15T10:01:00Z")
    submit(client, timestamp="2026-10-15T10:02:00Z")

    assert client(
        "POST", f"/api/alerts/{alert['alert_id']}/acknowledge", headers=OPERATOR_HEADERS
    ).status_code == 409


def test_alert_acknowledgement_requires_operator_authorization(client) -> None:
    submit(client, smoke_value=400)
    alert = client("GET", "/api/alerts").json()["items"][0]

    unauthorized = client("POST", f"/api/alerts/{alert['alert_id']}/acknowledge")
    invalid = client(
        "POST",
        f"/api/alerts/{alert['alert_id']}/acknowledge",
        headers={"Authorization": "Bearer incorrect"},
    )
    authorized = client(
        "POST", f"/api/alerts/{alert['alert_id']}/acknowledge", headers=OPERATOR_HEADERS
    )

    assert unauthorized.status_code == 401
    assert invalid.status_code == 401
    assert authorized.status_code == 200

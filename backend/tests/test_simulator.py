"""Unit and in-process API integration tests for the sensor simulator."""

import json
from datetime import datetime, timezone
from itertools import pairwise
from urllib.error import HTTPError, URLError

import pytest

from simulator.cli import Options, parse_options, run
from simulator.client import ApiError, ForestGuardClient
from simulator.scenarios import SCENARIOS, SensorGenerator


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_scenario_payload_has_contract_types_ranges_and_provenance(scenario):
    payload = SensorGenerator("FG-SIM-001", seed=10).reading(
        scenario, datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    assert payload["node_id"] == "FG-SIM-001"
    assert payload["is_simulated"] is True
    assert payload["timestamp"].endswith("Z")
    assert -80 <= payload["temperature_c"] <= 100
    assert 0 <= payload["humidity_percent"] <= 100
    assert payload["smoke_value"] is None or 0 <= payload["smoke_value"] <= 100000
    assert payload["gas_value"] is None or 0 <= payload["gas_value"] <= 100000
    assert 0 <= payload["battery_percent"] <= 100
    assert "latitude" not in payload and "longitude" not in payload


def test_fixed_seed_is_deterministic():
    first = SensorGenerator("FG-SIM-001", seed=123)
    second = SensorGenerator("FG-SIM-001", seed=123)
    fixed_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert [first.reading("normal", fixed_time) for _ in range(5)] == [
        second.reading("normal", fixed_time) for _ in range(5)
    ]


def test_configured_demo_coordinates_are_paired():
    payload = SensorGenerator("FG-SIM-001", seed=10, latitude=37.7, longitude=-119.5).reading(
        "normal", datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    assert (payload["latitude"], payload["longitude"]) == (37.7, -119.5)


def test_developing_risk_changes_gradually():
    generator = SensorGenerator("FG-SIM-001", seed=5)
    fixed_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    readings = [generator.reading("developing_risk", fixed_time) for _ in range(8)]
    assert all(abs(b["temperature_c"] - a["temperature_c"]) < 2.2 for a, b in pairwise(readings))
    assert all(abs(b["humidity_percent"] - a["humidity_percent"]) < 5 for a, b in pairwise(readings))
    assert readings[-1]["temperature_c"] > readings[0]["temperature_c"]
    assert readings[-1]["humidity_percent"] < readings[0]["humidity_percent"]


def test_smoke_event_has_corroborating_signals_and_recovery_moves_to_baseline():
    fixed_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    event = SensorGenerator("FG-SIM-001", seed=5)
    smoke = event.reading("smoke_event", fixed_time)
    assert smoke["smoke_value"] > 300 and smoke["gas_value"] > 350
    assert smoke["temperature_c"] > 38 and smoke["humidity_percent"] < 25
    recovery = SensorGenerator("FG-SIM-002", seed=5)
    values = [recovery.reading("recovery", fixed_time) for _ in range(4)]
    assert values[-1]["temperature_c"] < values[0]["temperature_c"]
    assert values[-1]["humidity_percent"] > values[0]["humidity_percent"]
    assert values[-1]["smoke_value"] < values[0]["smoke_value"]


def test_normal_variation_does_not_jump_and_sensor_failure_is_explicit():
    normal = SensorGenerator("FG-SIM-001", seed=4)
    values = [normal.reading("normal")["temperature_c"] for _ in range(20)]
    assert max(abs(b - a) for a, b in pairwise(values)) < 1
    failing = SensorGenerator("FG-SIM-001", seed=4)
    missing = failing.reading("sensor_failure")
    assert missing["smoke_value"] is None and missing["gas_value"] is None
    assert missing["temperature_c"] is not None


def test_cli_argument_validation():
    assert parse_options(["--stations", "2", "--scenario", "smoke_event"]).stations == 2
    with pytest.raises(SystemExit):
        parse_options(["--stations", "0"])
    with pytest.raises(SystemExit):
        parse_options(["--scenario", "unknown"])
    with pytest.raises(ValueError):
        parse_options(["--api-url", "localhost:8000"])


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.body


def test_http_success_and_json_payload():
    requests = []

    def opener(request, timeout):
        requests.append((request, timeout))
        return FakeResponse(b'{"ok":true}')

    result = ForestGuardClient("http://localhost:8000", opener=opener).send_reading(
        {"is_simulated": True}
    )
    assert result == {"ok": True}
    assert requests[0][0].method == "POST"
    assert json.loads(requests[0][0].data) == {"is_simulated": True}
    assert requests[0][1] == 5.0


def test_http_rejection_is_not_retried():
    calls = []

    def opener(*_args, **_kwargs):
        calls.append(1)
        raise HTTPError("http://test", 422, "invalid", {}, None)

    with pytest.raises(ApiError, match="HTTP 422"):
        ForestGuardClient("http://test", retries=3, opener=opener, sleep=lambda _: None)._request(
            "POST", "/api/readings", {}
        )
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [TimeoutError("timeout"), URLError("offline")])
def test_timeout_and_connection_errors_retry_then_report(failure):
    calls = []

    def opener(*_args, **_kwargs):
        calls.append(1)
        raise failure

    with pytest.raises(ApiError):
        ForestGuardClient("http://test", retries=2, opener=opener, sleep=lambda _: None)._request(
            "GET", "/health"
        )
    assert len(calls) == 3


def test_station_registration_handles_missing_and_existing():
    calls = []

    def opener(request, timeout):
        calls.append((request.method, request.full_url))
        if request.method == "GET":
            raise HTTPError("http://test", 404, "missing", {}, None)
        return FakeResponse(b"{}")

    api = ForestGuardClient("http://test", opener=opener, sleep=lambda _: None)
    api.ensure_station("FG-SIM-001", "Demo", 37.7, -119.5)
    assert [method for method, _ in calls] == ["GET", "POST"]


def test_station_registration_does_not_post_existing_station():
    calls = []

    def opener(request, timeout):
        calls.append(request.method)
        return FakeResponse(b"{}")

    ForestGuardClient("http://test", opener=opener).ensure_station(
        "FG-SIM-001", "Demo", None, None
    )
    assert calls == ["GET"]


def test_cli_clean_shutdown_summary(monkeypatch, capsys):
    class StubClient:
        def ensure_station(self, *_args):
            return None

        def send_reading(self, payload):
            assert payload["is_simulated"] is True

    options = Options("http://test", 1, 1, "normal", 1, 0.02, "FG-SIM")
    monkeypatch.setattr("simulator.cli.time.sleep", lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert run(options, StubClient()) == 0
    output = capsys.readouterr().out
    assert "SIMULATED DATA ONLY" in output
    assert "Simulator stopped. Simulated readings sent: 1; failures: 0." in output


def test_generated_smoke_event_round_trips_through_api_and_assesses_risk(client):
    class ApiHarness:
        def ensure_station(self, node_id, name, latitude, longitude):
            response = client(
                "POST",
                "/api/nodes",
                json={"node_id": node_id, "name": name, "latitude": latitude, "longitude": longitude},
            )
            assert response.status_code == 201, response.text

        def send_reading(self, payload):
            response = client("POST", "/api/readings", json=payload)
            assert response.status_code == 201, response.text
            return response.json()

    api = ApiHarness()
    generator = SensorGenerator("FG-SIM-001", seed=21, latitude=37.76, longitude=-119.6)
    api.ensure_station(generator.node_id, "Simulated station", 37.76, -119.6)
    reading = api.send_reading(generator.reading("smoke_event"))
    assert reading["is_simulated"] is True
    assert reading["risk_state"] == "CRITICAL"
    assert client("GET", "/api/alerts?is_simulated=true").json()["items"][0]["is_simulated"] is True

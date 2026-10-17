"""Data API, validation, migration, and existing-contract tests."""

import sqlite3
from typing import Any

import pytest
from forestguard.config import Settings
from forestguard.database import _migration_2, initialize_database
from forestguard.schemas import NodeCreate, ReadingCreate


def reading_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "node_id": "ridge-1",
        "temperature_c": 31.5,
        "humidity_percent": 42,
        "smoke_value": 128,
        "gas_value": 22,
        "timestamp": "2026-10-15T10:00:00+05:30",
        "is_simulated": True,
    }
    payload.update(overrides)
    return payload


def test_existing_root_health_and_cors_contracts_remain_available(client) -> None:
    root = client("GET", "/")
    health = client("GET", "/health")
    cors = client(
        "OPTIONS",
        "/api/readings",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert root.status_code == 200
    assert root.json()["name"] == "ForestGuard"
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "database": "ok"}
    assert cors.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_station_creation_listing_retrieval_and_update(client) -> None:
    created = client(
        "POST",
        "/api/nodes",
        json={
            "node_id": "ridge-1",
            "name": "North Ridge",
            "latitude": 18.52,
            "longitude": 73.85,
            "location": "Sector A",
        },
    )

    assert created.status_code == 201
    assert created.json()["node_id"] == "ridge-1"
    assert created.json()["latest_is_simulated"] is False
    assert client("GET", "/api/nodes/ridge-1").json()["name"] == "North Ridge"
    assert client("GET", "/api/nodes?limit=1&offset=0").json()[0]["node_id"] == "ridge-1"

    updated = client("PATCH", "/api/nodes/ridge-1", json={"name": "East Ridge"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "East Ridge"
    assert updated.json()["latitude"] == 18.52
    assert (
        client("POST", "/api/nodes", json={"node_id": "ridge-1", "name": "Duplicate"}).status_code
        == 409
    )


def test_station_payload_validation_rejects_invalid_ids_coordinates_and_names(client) -> None:
    invalid_payloads = [
        {"node_id": "bad id", "name": "North"},
        {"node_id": "node-2", "name": " "},
        {"node_id": "node-3", "name": "South", "latitude": 91, "longitude": 20},
        {"node_id": "node-4", "name": "South", "latitude": 12},
        {"node_id": "node-5", "name": "South", "latitude": 12, "longitude": -181},
    ]

    for payload in invalid_payloads:
        assert client("POST", "/api/nodes", json=payload).status_code == 422

    assert client("PATCH", "/api/nodes/missing", json={"name": "valid"}).status_code == 404
    assert client("PATCH", "/api/nodes/missing", json={}).status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [
        {"temperature_c": -80.1},
        {"temperature_c": 100.1},
        {"humidity_percent": -0.1},
        {"humidity_percent": 100.1},
        {"smoke_value": -1},
        {"gas_value": 100001},
        {"latitude": 90.1, "longitude": 10},
        {"latitude": 10},
        {"battery_percent": 101},
        {"timestamp": "2026-10-15T10:00:00"},
        {"is_simulated": "yes"},
    ],
)
def test_reading_payload_validation_rejects_invalid_values(client, overrides) -> None:
    response = client("POST", "/api/readings", json=reading_payload(**overrides))

    assert response.status_code == 422


def test_reading_ingestion_registers_station_and_updates_latest_state(client) -> None:
    response = client(
        "POST",
        "/api/readings",
        json=reading_payload(latitude=18.52, longitude=73.85, battery_percent=87),
    )

    assert response.status_code == 201
    saved_reading = response.json()
    assert saved_reading["node_id"] == "ridge-1"
    assert saved_reading["is_simulated"] is True
    assert saved_reading["timestamp"] == "2026-10-15T04:30:00Z"
    assert saved_reading["received_at"].endswith("Z")

    node = client("GET", "/api/nodes/ridge-1").json()
    assert node["name"] == "ridge-1"
    assert node["latitude"] == 18.52
    assert node["latest_temperature_c"] == 31.5
    assert node["battery_percent"] == 87
    assert node["latest_is_simulated"] is True


def test_reading_persistence_filters_pagination_and_series_order(client) -> None:
    payloads = [
        reading_payload(timestamp="2026-10-15T10:00:00Z", smoke_value=100),
        reading_payload(timestamp="2026-10-15T10:01:00Z", smoke_value=110),
        reading_payload(timestamp="2026-10-15T10:02:00Z", is_simulated=False, smoke_value=120),
        reading_payload(
            node_id="valley-2",
            timestamp="2026-10-15T10:03:00Z",
            is_simulated=False,
        ),
    ]
    for payload in payloads:
        assert client("POST", "/api/readings", json=payload).status_code == 201

    first_page = client(
        "GET", "/api/readings?node_id=ridge-1&is_simulated=true&limit=1&offset=0"
    ).json()
    second_page = client(
        "GET", "/api/readings?node_id=ridge-1&is_simulated=true&limit=1&offset=1"
    ).json()
    station_page = client("GET", "/api/nodes/ridge-1/readings?limit=2&offset=1").json()
    series = client("GET", "/api/nodes/ridge-1/series?limit=2").json()

    assert first_page["items"][0]["smoke_value"] == 110
    assert second_page["items"][0]["smoke_value"] == 100
    assert station_page["limit"] == 2
    assert len(station_page["items"]) == 2
    assert [item["smoke_value"] for item in series["items"]] == [110, 120]
    assert client("GET", "/api/nodes/unknown/readings").status_code == 404


def test_out_of_order_reading_is_stored_without_regressing_latest_station_state(client) -> None:
    client(
        "POST",
        "/api/readings",
        json=reading_payload(timestamp="2026-10-15T10:02:00Z", temperature_c=35),
    )
    older = client(
        "POST",
        "/api/readings",
        json=reading_payload(timestamp="2026-10-15T10:01:00Z", temperature_c=20),
    )

    assert older.status_code == 201
    node = client("GET", "/api/nodes/ridge-1").json()
    assert node["latest_temperature_c"] == 35
    assert node["latest_reading_at"] == "2026-10-15T10:02:00Z"
    assert len(client("GET", "/api/nodes/ridge-1/readings").json()["items"]) == 2


def test_schema_models_validate_and_normalize_reading_timestamp() -> None:
    node = NodeCreate.model_validate({"node_id": "forest-7", "name": "Forest Edge"})
    reading = ReadingCreate.model_validate(reading_payload())

    assert node.latitude is None
    assert reading.timestamp.isoformat() == "2026-10-15T04:30:00+00:00"


def test_migration_is_idempotent_and_preserves_existing_records(tmp_path) -> None:
    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO schema_migrations VALUES (1, 'legacy-time')")
        connection.execute("CREATE TABLE legacy_records (record_id TEXT PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO legacy_records VALUES ('keep-me', 'original')")

    initialize_database(database_path)
    initialize_database(database_path)

    with sqlite3.connect(database_path) as connection:
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        legacy_row = connection.execute("SELECT record_id, value FROM legacy_records").fetchone()
        table_names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }

    assert versions == [(1,), (2,), (3,), (4,), (5,)]
    assert legacy_row == ("keep-me", "original")
    assert {"nodes", "readings"}.issubset(table_names)


def test_fresh_database_migration_creates_parent_and_is_idempotent(tmp_path) -> None:
    database_path = tmp_path / "nested" / "forestguard.sqlite3"

    initialize_database(database_path)
    initialize_database(database_path)

    with sqlite3.connect(database_path) as connection:
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        indexes = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        }

    assert versions == [(1,), (2,), (3,), (4,), (5,)]
    assert {"idx_readings_node_measured", "idx_readings_simulated"}.issubset(indexes)


def test_phase4_migration_preserves_existing_v2_sensor_records(tmp_path) -> None:
    database_path = tmp_path / "version-two.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO schema_migrations VALUES (1, 'phase-2')")
        _migration_2(connection)
        connection.execute("INSERT INTO schema_migrations VALUES (2, 'phase-3')")
        connection.execute(
            """
            INSERT INTO nodes (node_id, name, created_at, updated_at)
            VALUES ('saved-node', 'Saved station', 'created', 'updated')
            """
        )
        connection.execute(
            """
            INSERT INTO readings (
                node_id, temperature_c, humidity_percent, smoke_value, measured_at,
                received_at, is_simulated
            ) VALUES ('saved-node', 39, 20, 420, 'sample-time', 'received-time', 0)
            """
        )

    initialize_database(database_path)

    with sqlite3.connect(database_path) as connection:
        node = connection.execute(
            "SELECT name, latest_temperature_available FROM nodes WHERE node_id = 'saved-node'"
        ).fetchone()
        reading = connection.execute(
            """
            SELECT temperature_c, humidity_percent, smoke_value, temperature_available,
                   humidity_available, smoke_available, risk_state
            FROM readings WHERE node_id = 'saved-node'
            """
        ).fetchone()
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert node == ("Saved station", 0)
    assert reading == (39, 20, 420, 1, 1, 1, None)
    assert versions == [(1,), (2,), (3,), (4,), (5,)]


def test_database_configuration_is_resolved_from_project_root(tmp_path) -> None:
    settings = Settings(database_path="data/example.sqlite3")

    assert settings.database_path.is_absolute()
    assert settings.database_path.name == "example.sqlite3"

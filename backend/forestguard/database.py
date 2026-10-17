"""SQLite connection and initialization helpers."""

import sqlite3
from pathlib import Path

LATEST_SCHEMA_VERSION = 5


def _migration_2(connection: sqlite3.Connection) -> None:
    """Add monitoring stations and sensor readings without altering legacy data."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS nodes (
            node_id TEXT PRIMARY KEY CHECK(length(node_id) BETWEEN 1 AND 64),
            name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 120),
            latitude REAL,
            longitude REAL,
            location TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_seen_at TEXT,
            latest_reading_at TEXT,
            latest_temperature_c REAL,
            latest_humidity_percent REAL,
            latest_smoke_value REAL,
            latest_gas_value REAL,
            battery_percent REAL,
            latest_is_simulated INTEGER NOT NULL DEFAULT 0
                CHECK(latest_is_simulated IN (0, 1)),
            CHECK(
                (latitude IS NULL AND longitude IS NULL)
                OR (latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)
            ),
            CHECK(battery_percent IS NULL OR battery_percent BETWEEN 0 AND 100),
            CHECK(latest_humidity_percent IS NULL OR latest_humidity_percent BETWEEN 0 AND 100)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id TEXT NOT NULL REFERENCES nodes(node_id) ON UPDATE CASCADE,
            temperature_c REAL NOT NULL CHECK(temperature_c BETWEEN -80 AND 100),
            humidity_percent REAL NOT NULL CHECK(humidity_percent BETWEEN 0 AND 100),
            smoke_value REAL NOT NULL CHECK(smoke_value BETWEEN 0 AND 100000),
            gas_value REAL CHECK(gas_value IS NULL OR gas_value BETWEEN 0 AND 100000),
            latitude REAL,
            longitude REAL,
            battery_percent REAL CHECK(battery_percent IS NULL OR battery_percent BETWEEN 0 AND 100),
            measured_at TEXT NOT NULL,
            received_at TEXT NOT NULL,
            is_simulated INTEGER NOT NULL CHECK(is_simulated IN (0, 1)),
            CHECK(
                (latitude IS NULL AND longitude IS NULL)
                OR (latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)
            )
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_readings_node_measured "
        "ON readings(node_id, measured_at DESC, id DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_readings_simulated "
        "ON readings(is_simulated, measured_at DESC)"
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_nodes_last_seen ON nodes(last_seen_at DESC)")


def _add_column_if_missing(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migration_3(connection: sqlite3.Connection) -> None:
    """Add risk result columns and a deduplicated alert lifecycle table."""
    reading_columns = (
        (
            "temperature_available",
            "INTEGER NOT NULL DEFAULT 1 CHECK(temperature_available IN (0, 1))",
        ),
        ("humidity_available", "INTEGER NOT NULL DEFAULT 1 CHECK(humidity_available IN (0, 1))"),
        ("smoke_available", "INTEGER NOT NULL DEFAULT 1 CHECK(smoke_available IN (0, 1))"),
        (
            "risk_state",
            "TEXT CHECK(risk_state IS NULL OR risk_state IN ('NORMAL', 'WATCH', 'WARNING', 'CRITICAL'))",
        ),
        ("risk_score", "INTEGER CHECK(risk_score IS NULL OR risk_score BETWEEN 0 AND 100)"),
        ("risk_reasons", "TEXT CHECK(risk_reasons IS NULL OR json_valid(risk_reasons))"),
        ("risk_signals", "TEXT CHECK(risk_signals IS NULL OR json_valid(risk_signals))"),
        ("risk_profile_version", "TEXT"),
        ("assessment_timestamp", "TEXT"),
        (
            "connectivity_state",
            "TEXT CHECK(connectivity_state IS NULL OR connectivity_state IN ('ONLINE', 'STALE', 'OFFLINE'))",
        ),
    )
    for column, definition in reading_columns:
        _add_column_if_missing(connection, "readings", column, definition)

    node_columns = (
        (
            "latest_temperature_available",
            "INTEGER NOT NULL DEFAULT 1 CHECK(latest_temperature_available IN (0, 1))",
        ),
        (
            "latest_humidity_available",
            "INTEGER NOT NULL DEFAULT 1 CHECK(latest_humidity_available IN (0, 1))",
        ),
        (
            "latest_smoke_available",
            "INTEGER NOT NULL DEFAULT 1 CHECK(latest_smoke_available IN (0, 1))",
        ),
        (
            "current_risk_state",
            "TEXT CHECK(current_risk_state IS NULL OR current_risk_state IN ('NORMAL', 'WATCH', 'WARNING', 'CRITICAL'))",
        ),
        (
            "current_risk_score",
            "INTEGER CHECK(current_risk_score IS NULL OR current_risk_score BETWEEN 0 AND 100)",
        ),
        (
            "current_risk_reasons",
            "TEXT CHECK(current_risk_reasons IS NULL OR json_valid(current_risk_reasons))",
        ),
        ("current_risk_profile_version", "TEXT"),
        ("risk_assessed_at", "TEXT"),
    )
    for column, definition in node_columns:
        _add_column_if_missing(connection, "nodes", column, definition)
    connection.execute(
        """
        UPDATE nodes SET latest_temperature_available = 0,
            latest_humidity_available = 0, latest_smoke_available = 0
        WHERE latest_reading_at IS NULL
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            alert_id TEXT PRIMARY KEY,
            node_id TEXT NOT NULL REFERENCES nodes(node_id) ON UPDATE CASCADE,
            severity TEXT NOT NULL CHECK(severity IN ('WATCH', 'WARNING', 'CRITICAL')),
            risk_score INTEGER NOT NULL CHECK(risk_score BETWEEN 0 AND 100),
            reasons TEXT NOT NULL CHECK(json_valid(reasons)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE'
                CHECK(status IN ('ACTIVE', 'ACKNOWLEDGED', 'RESOLVED')),
            is_simulated INTEGER NOT NULL CHECK(is_simulated IN (0, 1)),
            last_reading_id INTEGER REFERENCES readings(id),
            acknowledged_at TEXT,
            resolved_at TEXT,
            resolution_reason TEXT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_alerts_node_created ON alerts(node_id, created_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_alerts_status_created ON alerts(status, created_at DESC)"
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_one_open_per_node
        ON alerts(node_id, is_simulated) WHERE status IN ('ACTIVE', 'ACKNOWLEDGED')
        """
    )


def _migration_4(connection: sqlite3.Connection) -> None:
    """Add a durable notification outbox without changing alert or reading records."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_log (
            notification_id TEXT PRIMARY KEY,
            event_key TEXT NOT NULL UNIQUE,
            alert_id TEXT NOT NULL REFERENCES alerts(alert_id),
            event_type TEXT NOT NULL CHECK(event_type IN ('CREATED', 'ESCALATED')),
            severity TEXT NOT NULL CHECK(severity IN ('WATCH', 'WARNING', 'CRITICAL')),
            risk_score INTEGER NOT NULL CHECK(risk_score BETWEEN 0 AND 100),
            is_simulated INTEGER NOT NULL CHECK(is_simulated IN (0, 1)),
            message_text TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('PENDING', 'SENDING', 'SENT', 'FAILED', 'SKIPPED')),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            sending_started_at TEXT,
            next_attempt_at TEXT,
            sent_at TEXT,
            last_error TEXT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_log_dispatch "
        "ON notification_log(status, next_attempt_at, created_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_log_alert "
        "ON notification_log(alert_id, created_at)"
    )


def _migration_5(connection: sqlite3.Connection) -> None:
    """Create audited command records without adding any device execution mechanism."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS device_commands (
            command_id TEXT PRIMARY KEY,
            node_id TEXT NOT NULL REFERENCES nodes(node_id) ON UPDATE CASCADE,
            command_type TEXT NOT NULL CHECK(command_type IN ('REQUEST_STATUS', 'SENSOR_SELF_TEST')),
            reason TEXT NOT NULL CHECK(length(trim(reason)) BETWEEN 5 AND 500),
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN
                ('PENDING', 'ACKNOWLEDGED', 'COMPLETED', 'FAILED', 'EXPIRED')),
            is_simulated INTEGER NOT NULL CHECK(is_simulated IN (0, 1)),
            created_by TEXT NOT NULL,
            acknowledged_at TEXT,
            finished_at TEXT,
            result_summary TEXT,
            CHECK(expires_at > created_at)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_device_commands_node_created "
        "ON device_commands(node_id, created_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_device_commands_status_expiry "
        "ON device_commands(status, expires_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_device_commands_operator_rate "
        "ON device_commands(created_by, created_at DESC)"
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_device_commands_no_duplicate_pending
        ON device_commands(node_id, command_type, is_simulated) WHERE status = 'PENDING'
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS device_command_events (
            event_id TEXT PRIMARY KEY,
            command_id TEXT REFERENCES device_commands(command_id) ON DELETE SET NULL,
            node_id TEXT,
            event_type TEXT NOT NULL CHECK(event_type IN
                ('CREATED', 'ACKNOWLEDGED', 'COMPLETED', 'FAILED', 'EXPIRED', 'REJECTED')),
            actor TEXT NOT NULL,
            event_at TEXT NOT NULL,
            details_json TEXT NOT NULL CHECK(json_valid(details_json))
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_device_command_events_command "
        "ON device_command_events(command_id, event_at DESC)"
    )


def connect(database_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with foreign-key enforcement enabled."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(database_path: Path) -> None:
    """Apply additive, idempotent migrations while preserving existing rows."""
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )
        migration_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(schema_migrations)")
        }
        if "applied_at" not in migration_columns:
            connection.execute("ALTER TABLE schema_migrations ADD COLUMN applied_at TEXT")
        connection.execute(
            """
            UPDATE schema_migrations
            SET applied_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE applied_at IS NULL
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO schema_migrations (version, applied_at)
            VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """
        )
        applied = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()[0]
        if applied > LATEST_SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {applied} is newer than supported "
                f"version {LATEST_SCHEMA_VERSION}"
            )
        if applied < 2:
            _migration_2(connection)
            connection.execute(
                """
                INSERT INTO schema_migrations (version, applied_at)
                VALUES (2, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """
            )
            applied = 2
        if applied < 3:
            _migration_3(connection)
            connection.execute(
                """
                INSERT INTO schema_migrations (version, applied_at)
                VALUES (3, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """
            )
            applied = 3
        if applied < 4:
            _migration_4(connection)
            connection.execute(
                """
                INSERT INTO schema_migrations (version, applied_at)
                VALUES (4, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """
            )
            applied = 4
        if applied < 5:
            _migration_5(connection)
            connection.execute(
                """
                INSERT INTO schema_migrations (version, applied_at)
                VALUES (5, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """
            )


def check_database(database_path: Path) -> bool:
    """Return whether SQLite can run a lightweight query at the configured path."""
    try:
        with connect(database_path) as connection:
            row = connection.execute("SELECT 1").fetchone()
            return row is not None and row[0] == 1
    except (OSError, sqlite3.Error):
        return False

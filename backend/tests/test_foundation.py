"""Regression tests for configuration and SQLite foundation behavior."""

import sqlite3

from forestguard.config import PROJECT_ROOT, Settings
from forestguard.database import check_database, initialize_database


def test_database_initialization_is_idempotent_and_creates_parent(tmp_path) -> None:
    database_path = tmp_path / "nested" / "forestguard.sqlite3"

    initialize_database(database_path)
    initialize_database(database_path)

    assert check_database(database_path)
    with sqlite3.connect(database_path) as connection:
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert versions == [(1,), (2,), (3,), (4,), (5,)]


def test_database_connection_failure_is_reported_as_unhealthy(tmp_path) -> None:
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("block database creation", encoding="utf-8")

    assert check_database(parent_file / "forestguard.sqlite3") is False


def test_database_path_is_resolved_relative_to_project() -> None:
    settings = Settings(database_path="data/test.sqlite3")

    assert settings.database_path.is_absolute()
    assert settings.database_path.name == "test.sqlite3"


def test_environment_example_loads_with_safe_demo_defaults() -> None:
    settings = Settings(_env_file=PROJECT_ROOT / ".env.example")

    assert settings.cors_origins == ["http://localhost:5173"]
    assert settings.telegram_enabled is False
    assert settings.telegram_bot_token is None
    assert settings.device_commands_enabled is False
    assert settings.device_commands_auth_token is None

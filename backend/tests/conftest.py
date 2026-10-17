"""Shared isolated HTTP fixture for FastAPI route tests."""

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import Response
from forestguard.config import Settings, get_settings
from forestguard.main import app


@pytest.fixture
def client(tmp_path, monkeypatch) -> Callable[..., Response]:
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "forestguard.sqlite3",
        device_commands_auth_token="test-operator-token",
    )
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)
    monkeypatch.setattr("forestguard.main.get_settings", lambda: settings)
    monkeypatch.setattr("forestguard.routes.nodes.get_settings", lambda: settings)
    monkeypatch.setattr("forestguard.routes.readings.get_settings", lambda: settings)
    monkeypatch.setattr("forestguard.routes.alerts.get_settings", lambda: settings)

    def request(method: str, path: str, **kwargs: Any) -> Response:
        async def send() -> Response:
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://test",
                ) as http_client:
                    return await http_client.request(method, path, **kwargs)

        return asyncio.run(send())

    return request

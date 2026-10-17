"""Small standard-library HTTP client for the ForestGuard API."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ApiError(RuntimeError):
    """An API request failed after applicable retries."""


class ForestGuardClient:
    def __init__(
        self,
        api_url: str,
        timeout: float = 5.0,
        retries: int = 2,
        opener: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self._opener = opener or urlopen
        self._sleep = sleep

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            f"{self.api_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        for attempt in range(self.retries + 1):
            try:
                with self._opener(request, timeout=self.timeout) as response:
                    raw = response.read()
                return json.loads(raw) if raw else None
            except HTTPError as error:
                if error.code < 500 and error.code != 429:
                    raise ApiError(f"API returned HTTP {error.code} for {method} {path}") from error
                message = f"API returned HTTP {error.code} for {method} {path}"
                if attempt == self.retries:
                    raise ApiError(message) from error
            except (TimeoutError, URLError, OSError) as error:
                message = f"Could not reach API for {method} {path}: {error.reason if isinstance(error, URLError) else error}"
                if attempt == self.retries:
                    raise ApiError(message) from error
            self._sleep(min(0.25 * (2**attempt), 1.0))
        raise ApiError(message)

    def ensure_station(
        self, node_id: str, name: str, latitude: float | None, longitude: float | None
    ) -> None:
        try:
            self._request("GET", f"/api/nodes/{node_id}")
            return
        except ApiError as error:
            if "HTTP 404" not in str(error):
                raise
        body: dict[str, Any] = {"node_id": node_id, "name": name}
        if latitude is not None and longitude is not None:
            body.update(latitude=latitude, longitude=longitude)
        try:
            self._request("POST", "/api/nodes", body)
        except ApiError as error:
            # A concurrent simulator may have registered the station in between.
            if "HTTP 409" not in str(error):
                raise

    def send_reading(self, payload: dict[str, Any]) -> Any:
        return self._request("POST", "/api/readings", payload)

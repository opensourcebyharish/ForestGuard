"""Bounded, deterministic environmental readings for demonstration scenarios."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

SCENARIOS = ("normal", "developing_risk", "smoke_event", "recovery", "sensor_failure")


@dataclass
class SensorGenerator:
    """Generate one station's readings using a private seeded random stream."""

    node_id: str
    seed: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    battery_enabled: bool = True

    def __post_init__(self) -> None:
        self.random = random.Random(self.seed)
        self.step = 0

    def reading(self, scenario: str, timestamp: datetime | None = None) -> dict[str, Any]:
        if scenario not in SCENARIOS:
            raise ValueError(f"unsupported scenario: {scenario}")
        tick = self.step
        self.step += 1
        noise = self.random.uniform
        temperature, humidity, smoke, gas = 25.0, 55.0, 18.0, 45.0

        if scenario == "developing_risk":
            progress = min(tick / 12, 1.0)
            temperature = 25 + progress * 16
            humidity = 55 - progress * 34
            smoke = 20 + progress * 8
            gas = 45 + progress * 15
        elif scenario == "smoke_event":
            temperature, humidity, smoke, gas = 42.0, 20.0, 520.0, 480.0
        elif scenario == "recovery":
            progress = min(tick / 10, 1.0)
            temperature = 42 - progress * 17
            humidity = 20 + progress * 35
            smoke = 520 - progress * 500
            gas = 480 - progress * 435

        # Normal variation stays smooth; only tiny sensor noise is applied.
        temperature = round(max(-20.0, min(60.0, temperature + noise(-0.35, 0.35))), 2)
        humidity = round(max(0.0, min(100.0, humidity + noise(-1.0, 1.0))), 2)
        smoke = round(max(0.0, min(100000.0, smoke + noise(-3.0, 3.0))), 2)
        gas = round(max(0.0, min(100000.0, gas + noise(-4.0, 4.0))), 2)

        # Every third sensor_failure sample has an unavailable smoke channel;
        # every fifth has gas unavailable. Other channels remain measured.
        if scenario == "sensor_failure":
            if tick % 3 == 0:
                smoke = None
            if tick % 5 == 0:
                gas = None

        measured_at = timestamp or datetime.now(timezone.utc)
        payload: dict[str, Any] = {
            "node_id": self.node_id,
            "temperature_c": temperature,
            "humidity_percent": humidity,
            "smoke_value": smoke,
            "gas_value": gas,
            "battery_percent": round(max(0.0, min(100.0, 92 - tick * 0.03)), 2)
            if self.battery_enabled
            else None,
            "timestamp": measured_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "is_simulated": True,
        }
        if self.latitude is not None and self.longitude is not None:
            payload.update(latitude=self.latitude, longitude=self.longitude)
        return payload

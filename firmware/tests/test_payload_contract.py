"""Host-side checks against the actual backend payload schema and firmware serializer."""

from pathlib import Path

import pytest
from forestguard.schemas import ReadingCreate
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SOURCE = (ROOT / "firmware" / "src" / "main.cpp").read_text(encoding="utf-8")


def payload(**overrides):
    value = {
        "node_id": "FG-ESP32-001",
        "humidity_percent": 48.5,
        "timestamp": "2026-10-16T10:15:30Z",
        "is_simulated": False,
    }
    value.update(overrides)
    return value


def test_minimal_physical_payload_with_missing_channels_is_accepted():
    reading = ReadingCreate.model_validate(payload())

    assert reading.is_simulated is False
    assert reading.temperature_c is None
    assert reading.smoke_value is None
    assert reading.gas_value is None
    assert reading.latitude is None
    assert reading.longitude is None
    assert reading.battery_percent is None


def test_temperature_smoke_gas_and_battery_ranges_match_backend():
    ReadingCreate.model_validate(
        payload(temperature_c=-80, smoke_value=0, gas_value=100000, battery_percent=100)
    )
    with pytest.raises(ValidationError):
        ReadingCreate.model_validate(payload(temperature_c=100.1))
    with pytest.raises(ValidationError):
        ReadingCreate.model_validate(payload(smoke_value=-1))
    with pytest.raises(ValidationError):
        ReadingCreate.model_validate(payload(gas_value=100001))
    with pytest.raises(ValidationError):
        ReadingCreate.model_validate(payload(battery_percent=101))


def test_timestamp_must_be_timezone_aware():
    ReadingCreate.model_validate(payload(timestamp="2026-10-16T10:15:30Z"))
    with pytest.raises(ValidationError):
        ReadingCreate.model_validate(payload(timestamp="2026-10-16T10:15:30"))


def test_coordinates_must_be_paired_and_bounded():
    ReadingCreate.model_validate(payload(latitude=0, longitude=0))
    with pytest.raises(ValidationError):
        ReadingCreate.model_validate(payload(latitude=40))
    with pytest.raises(ValidationError):
        ReadingCreate.model_validate(payload(latitude=91, longitude=40))


def test_at_least_one_environmental_channel_is_required():
    with pytest.raises(ValidationError):
        ReadingCreate.model_validate(
            {
                "node_id": "FG-ESP32-001",
                "battery_percent": 50,
                "is_simulated": False,
            }
        )


def test_firmware_serializes_physical_provenance_and_omits_unavailable_fields():
    assert 'document["is_simulated"] = false;' in FIRMWARE_SOURCE
    assert 'document["temperature_c"] = reading.temperatureC;' in FIRMWARE_SOURCE
    assert 'document["humidity_percent"] = reading.humidityPercent;' in FIRMWARE_SOURCE
    assert 'document["smoke_value"] = reading.smokeValue;' in FIRMWARE_SOURCE
    assert 'document["gas_value"] = reading.gasValue;' in FIRMWARE_SOURCE
    assert 'document["battery_percent"] = reading.batteryPercent;' in FIRMWARE_SOURCE
    assert 'if (reading.timestamp[0] != \'\\0\') document["timestamp"]' in FIRMWARE_SOURCE


def test_example_config_has_no_assumed_sensors_pins_or_credentials():
    example = (ROOT / "firmware" / "include" / "config.example.h").read_text(encoding="utf-8")

    assert '#define FG_WIFI_SSID ""' in example
    assert '#define FG_WIFI_PASSWORD ""' in example
    assert "#define FG_ENABLE_DHT22 0" in example
    assert "#define FG_ENABLE_SMOKE_ADC 0" in example
    assert "#define FG_ENABLE_GAS_ADC 0" in example
    assert "#define FG_ENABLE_BATTERY_ADC 0" in example
    assert "#define FG_HAS_COORDINATES 0" in example
    assert "#define FG_DHT_PIN -1" in example


def test_firmware_has_no_actuator_or_command_execution_path():
    lowered = FIRMWARE_SOURCE.lower()
    assert "pump" not in lowered
    assert "relay" not in lowered
    assert "gpio_write" not in lowered
    assert "/api/commands" not in lowered

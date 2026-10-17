"""Single versioned set of demonstration thresholds for ForestGuard risk scoring."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskThresholdProfile:
    version: str = "demo-v1"
    temperature_elevated_c: float = 38.0
    temperature_extreme_c: float = 50.0
    humidity_low_percent: float = 25.0
    smoke_elevated_value: float = 300.0
    gas_elevated_value: float = 350.0
    rapid_temperature_rise_c: float = 8.0
    rapid_humidity_drop_percent: float = 15.0
    rapid_smoke_change_value: float = 100.0
    rapid_smoke_change_ratio: float = 0.5
    trend_window_seconds: int = 3600
    consecutive_readings_for_sustained: int = 3
    sustained_window_seconds: int = 1800
    minimum_sustained_duration_seconds: int = 60
    stale_after_seconds: int = 300
    offline_after_seconds: int = 900
    normal_readings_to_resolve: int = 2
    temperature_points: int = 22
    extreme_temperature_points: int = 35
    low_humidity_points: int = 20
    smoke_points: int = 35
    gas_points: int = 20
    rapid_change_points: int = 20
    sustained_points: int = 30
    incomplete_data_score_floor: int = 20
    warning_score: int = 45
    critical_score_with_corroboration: int = 70
    critical_score_when_sustained: int = 60


DEMO_RISK_PROFILE = RiskThresholdProfile()

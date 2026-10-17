"""Unit tests for the pure risk and connectivity assessment engine."""

from datetime import datetime, timedelta, timezone

import pytest
from forestguard.risk_engine import (
    ConnectivityState,
    RiskObservation,
    RiskState,
    assess_connectivity,
    assess_risk,
)
from forestguard.risk_profile import DEMO_RISK_PROFILE

BASE_TIME = datetime(2026, 10, 15, 10, tzinfo=timezone.utc)


def sample(minute: int = 0, **overrides: object) -> RiskObservation:
    values: dict[str, object] = {
        "timestamp": BASE_TIME + timedelta(minutes=minute),
        "temperature_c": 22.0,
        "humidity_percent": 60.0,
        "smoke_value": 50.0,
        "gas_value": None,
        "is_simulated": False,
    }
    values.update(overrides)
    return RiskObservation(**values)  # type: ignore[arg-type]


def test_normal_reading_has_zero_score_and_explainable_signals() -> None:
    assessment = assess_risk(sample(), assessed_at=BASE_TIME)

    assert assessment.risk_state is RiskState.NORMAL
    assert assessment.risk_score == 0
    assert assessment.profile_version == DEMO_RISK_PROFILE.version
    assert assessment.is_simulated is False
    assert {signal.name for signal in assessment.signals} >= {
        "temperature_elevated",
        "humidity_low",
        "smoke_elevated",
        "gas_elevated",
        "rapid_change",
        "sustained_abnormal",
        "data_completeness",
    }


@pytest.mark.parametrize(
    ("values", "expected_score"),
    [
        ({"temperature_c": 40.0}, 22),
        ({"humidity_percent": 20.0}, 20),
        ({"smoke_value": 400.0}, 35),
        ({"gas_value": 400.0}, 20),
    ],
)
def test_single_sensor_evidence_never_assigns_critical(values, expected_score) -> None:
    assessment = assess_risk(sample(**values), assessed_at=BASE_TIME)

    assert assessment.risk_state is RiskState.WATCH
    assert assessment.risk_score == expected_score
    assert assessment.risk_state is not RiskState.CRITICAL


def test_critical_requires_corroboration_from_independent_sensor_channels() -> None:
    assessment = assess_risk(
        sample(temperature_c=50, humidity_percent=20, smoke_value=400),
        assessed_at=BASE_TIME,
    )

    assert assessment.risk_state is RiskState.CRITICAL
    assert assessment.risk_score >= DEMO_RISK_PROFILE.critical_score_with_corroboration
    assert any("corroborated" in reason for reason in assessment.reasons)


def test_critical_can_follow_three_consecutive_abnormal_readings() -> None:
    history = [sample(-2, smoke_value=400), sample(-1, smoke_value=400)]

    assessment = assess_risk(sample(smoke_value=400), history, assessed_at=BASE_TIME)

    assert assessment.risk_state is RiskState.CRITICAL
    assert any("3 consecutive" in reason for reason in assessment.reasons)


def test_one_extreme_smoke_reading_is_not_critical_without_supporting_evidence() -> None:
    assessment = assess_risk(sample(smoke_value=5000), assessed_at=BASE_TIME)

    assert assessment.risk_state is RiskState.WATCH
    assert assessment.risk_state is not RiskState.CRITICAL


def test_missing_smoke_is_uncertainty_and_never_proof_of_safe_air() -> None:
    assessment = assess_risk(sample(smoke_value=None), assessed_at=BASE_TIME)
    smoke_signal = next(signal for signal in assessment.signals if signal.name == "smoke_elevated")

    assert assessment.risk_state is RiskState.WATCH
    assert smoke_signal.available is False
    assert any("not evidence of clean air" in reason for reason in assessment.reasons)


def test_missing_all_sensors_is_watch_and_invalid_values_are_unavailable() -> None:
    missing = assess_risk(
        sample(temperature_c=None, humidity_percent=None, smoke_value=None),
        assessed_at=BASE_TIME,
    )
    invalid = assess_risk(sample(humidity_percent=140), assessed_at=BASE_TIME)

    assert missing.risk_state is RiskState.WATCH
    assert missing.risk_score == DEMO_RISK_PROFILE.incomplete_data_score_floor
    assert invalid.risk_state is RiskState.WATCH
    assert any("outside valid range" in signal.detail for signal in invalid.signals)


def test_rapid_sensor_change_contributes_to_watch_state() -> None:
    previous = sample(-5, temperature_c=20, humidity_percent=65, smoke_value=100)
    current = sample(temperature_c=30, humidity_percent=45, smoke_value=250)

    assessment = assess_risk(current, [previous], assessed_at=BASE_TIME)
    trend = next(signal for signal in assessment.signals if signal.name == "rapid_change")

    assert trend.triggered is True
    assert assessment.risk_state is RiskState.WATCH


def test_contradictory_sensors_are_reported_without_suppressing_smoke_risk() -> None:
    assessment = assess_risk(
        sample(temperature_c=20, humidity_percent=70, smoke_value=400),
        assessed_at=BASE_TIME,
    )
    disagreement = next(
        signal for signal in assessment.signals if signal.name == "sensor_disagreement"
    )

    assert disagreement.triggered is True
    assert assessment.risk_score == 35
    assert assessment.risk_state is RiskState.WATCH


def test_simulated_history_is_never_mixed_with_hardware_history() -> None:
    simulated_history = [
        sample(-2, smoke_value=400, is_simulated=True),
        sample(-1, smoke_value=400, is_simulated=True),
    ]
    hardware_current = sample(smoke_value=400, is_simulated=False)

    assessment = assess_risk(hardware_current, simulated_history, assessed_at=BASE_TIME)

    assert assessment.is_simulated is False
    assert assessment.risk_state is RiskState.WATCH


@pytest.mark.parametrize(
    ("age_seconds", "state"),
    [
        (30, ConnectivityState.ONLINE),
        (600, ConnectivityState.STALE),
        (1800, ConnectivityState.OFFLINE),
    ],
)
def test_connectivity_states_are_separate_from_risk(age_seconds, state) -> None:
    last_seen = BASE_TIME - timedelta(seconds=age_seconds)

    assert assess_connectivity(last_seen, assessed_at=BASE_TIME) is state


def test_assessment_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone"):
        assess_risk(sample(timestamp=datetime(2026, 10, 15, 10)), assessed_at=BASE_TIME)

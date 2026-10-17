"""Pure, explainable fire-risk and device-connectivity assessment functions."""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from forestguard.risk_profile import DEMO_RISK_PROFILE, RiskThresholdProfile


class RiskState(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class ConnectivityState(str, Enum):
    ONLINE = "ONLINE"
    STALE = "STALE"
    OFFLINE = "OFFLINE"


RISK_STATE_RANK = {
    RiskState.NORMAL: 0,
    RiskState.WATCH: 1,
    RiskState.WARNING: 2,
    RiskState.CRITICAL: 3,
}


@dataclass(frozen=True)
class RiskObservation:
    timestamp: datetime
    temperature_c: float | None
    humidity_percent: float | None
    smoke_value: float | None
    gas_value: float | None = None
    is_simulated: bool = False


@dataclass(frozen=True)
class SignalResult:
    name: str
    domain: str
    available: bool
    value: float | None
    triggered: bool
    points: int
    detail: str


@dataclass(frozen=True)
class RiskAssessment:
    risk_state: RiskState
    risk_score: int
    reasons: tuple[str, ...]
    signals: tuple[SignalResult, ...]
    timestamp: datetime
    is_simulated: bool
    connectivity_state: ConnectivityState
    profile_version: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "risk_state": self.risk_state.value,
            "risk_score": self.risk_score,
            "reasons": list(self.reasons),
            "signals": [asdict(signal) for signal in self.signals],
            "timestamp": self.timestamp.astimezone(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "is_simulated": self.is_simulated,
            "connectivity_state": self.connectivity_state.value,
            "profile_version": self.profile_version,
        }


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("risk assessment timestamps must include a timezone")
    return value.astimezone(timezone.utc)


def _valid(value: float | None, lower: float, upper: float) -> bool:
    return value is not None and lower <= value <= upper


def _recent_previous(
    current: RiskObservation,
    history: Sequence[RiskObservation],
    profile: RiskThresholdProfile,
) -> RiskObservation | None:
    current_time = _aware_utc(current.timestamp)
    candidates = [
        item
        for item in history
        if item.is_simulated == current.is_simulated
        and _aware_utc(item.timestamp) < current_time
        and current_time - _aware_utc(item.timestamp)
        <= timedelta(seconds=profile.trend_window_seconds)
    ]
    return max(candidates, key=lambda item: _aware_utc(item.timestamp), default=None)


def _abnormal(observation: RiskObservation, profile: RiskThresholdProfile) -> bool:
    return (
        (
            _valid(observation.temperature_c, -80, 100)
            and observation.temperature_c >= profile.temperature_elevated_c
        )
        or (
            _valid(observation.humidity_percent, 0, 100)
            and observation.humidity_percent <= profile.humidity_low_percent
        )
        or (
            _valid(observation.smoke_value, 0, 100000)
            and observation.smoke_value >= profile.smoke_elevated_value
        )
        or (
            _valid(observation.gas_value, 0, 100000)
            and observation.gas_value >= profile.gas_elevated_value
        )
    )


def _sustained_samples(
    current: RiskObservation,
    history: Sequence[RiskObservation],
    profile: RiskThresholdProfile,
) -> list[RiskObservation]:
    samples = [
        item
        for item in history
        if item.is_simulated == current.is_simulated
        and _aware_utc(item.timestamp) <= _aware_utc(current.timestamp)
        and _aware_utc(current.timestamp) - _aware_utc(item.timestamp)
        <= timedelta(seconds=profile.sustained_window_seconds)
    ]
    samples.append(current)
    ordered = sorted(samples, key=lambda item: _aware_utc(item.timestamp), reverse=True)
    sustained: list[RiskObservation] = []
    for item in ordered:
        if not _abnormal(item, profile):
            break
        sustained.append(item)
    return sustained


def assess_connectivity(
    last_seen_at: datetime,
    *,
    assessed_at: datetime | None = None,
    profile: RiskThresholdProfile = DEMO_RISK_PROFILE,
) -> ConnectivityState:
    now = _aware_utc(assessed_at or datetime.now(timezone.utc))
    seen = _aware_utc(last_seen_at)
    age_seconds = max(0.0, (now - seen).total_seconds())
    if age_seconds <= profile.stale_after_seconds:
        return ConnectivityState.ONLINE
    if age_seconds <= profile.offline_after_seconds:
        return ConnectivityState.STALE
    return ConnectivityState.OFFLINE


def assess_risk(
    current: RiskObservation,
    history: Sequence[RiskObservation] = (),
    *,
    assessed_at: datetime | None = None,
    connectivity_at: datetime | None = None,
    profile: RiskThresholdProfile = DEMO_RISK_PROFILE,
) -> RiskAssessment:
    """Score one observation using only its values and supplied earlier history."""
    _aware_utc(current.timestamp)
    assessment_at = _aware_utc(assessed_at or datetime.now(timezone.utc))
    connection_time = _aware_utc(connectivity_at or current.timestamp)
    score = 0
    reasons: list[str] = []
    signals: list[SignalResult] = []
    corroborating_domains: set[str] = set()
    primary_sensor_missing = False

    sensor_specs = (
        ("temperature", current.temperature_c, -80, 100),
        ("humidity", current.humidity_percent, 0, 100),
        ("smoke", current.smoke_value, 0, 100000),
        ("gas", current.gas_value, 0, 100000),
    )
    availability: dict[str, bool] = {}
    for name, value, lower, upper in sensor_specs:
        valid = _valid(value, lower, upper)
        availability[name] = valid
        if not valid:
            if name in {"temperature", "humidity", "smoke"}:
                primary_sensor_missing = True
            detail = "sensor unavailable" if value is None else "sensor value outside valid range"
            signals.append(SignalResult(name, name, False, None, False, 0, detail))
            reasons.append(
                f"{name.title()} data is unavailable or invalid; it is not treated as safe."
            )

    def add_signal(
        name: str,
        domain: str,
        value: float | None,
        triggered: bool,
        points: int,
        detail: str,
    ) -> None:
        nonlocal score
        available = availability.get(domain, True)
        signals.append(SignalResult(name, domain, available, value, triggered, points, detail))
        if triggered:
            score += points
            reasons.append(detail)
            if domain in {"temperature", "humidity", "smoke", "gas"}:
                corroborating_domains.add(domain)
        elif not available and detail not in reasons:
            reasons.append(detail)

    temperature = current.temperature_c if availability["temperature"] else None
    if temperature is None:
        add_signal(
            "temperature_elevated", "temperature", None, False, 0, "Temperature unavailable."
        )
    elif temperature >= profile.temperature_extreme_c:
        add_signal(
            "temperature_extreme",
            "temperature",
            temperature,
            True,
            profile.extreme_temperature_points,
            f"Temperature is extremely elevated at {temperature:.1f} °C.",
        )
    else:
        temperature_detail = (
            f"Temperature is elevated at {temperature:.1f} °C."
            if temperature >= profile.temperature_elevated_c
            else "Temperature is below the elevated threshold."
        )
        add_signal(
            "temperature_elevated",
            "temperature",
            temperature,
            temperature >= profile.temperature_elevated_c,
            profile.temperature_points,
            temperature_detail,
        )

    humidity = current.humidity_percent if availability["humidity"] else None
    add_signal(
        "humidity_low",
        "humidity",
        humidity,
        humidity is not None and humidity <= profile.humidity_low_percent,
        profile.low_humidity_points,
        (
            (
                f"Relative humidity is low at {humidity:.1f}%."
                if humidity <= profile.humidity_low_percent
                else "Relative humidity is above the low-humidity threshold."
            )
            if humidity is not None
            else "Humidity unavailable."
        ),
    )

    smoke = current.smoke_value if availability["smoke"] else None
    add_signal(
        "smoke_elevated",
        "smoke",
        smoke,
        smoke is not None and smoke >= profile.smoke_elevated_value,
        profile.smoke_points,
        (
            (
                f"Smoke sensor value is elevated at {smoke:.1f}."
                if smoke >= profile.smoke_elevated_value
                else "Smoke sensor value is below the elevated threshold."
            )
            if smoke is not None
            else "Smoke data unavailable; absence of a reading is not evidence of clean air."
        ),
    )

    gas = current.gas_value if availability["gas"] else None
    add_signal(
        "gas_elevated",
        "gas",
        gas,
        gas is not None and gas >= profile.gas_elevated_value,
        profile.gas_points,
        (
            (
                f"Gas sensor value is elevated at {gas:.1f}."
                if gas >= profile.gas_elevated_value
                else "Gas sensor value is below the elevated threshold."
            )
            if gas is not None
            else "Gas sensor unavailable."
        ),
    )

    previous = _recent_previous(current, history, profile)
    changes: list[str] = []
    if previous is not None:
        if (
            availability["temperature"]
            and _valid(previous.temperature_c, -80, 100)
            and current.temperature_c - previous.temperature_c >= profile.rapid_temperature_rise_c
        ):
            changes.append("temperature rose rapidly")
        if (
            availability["humidity"]
            and _valid(previous.humidity_percent, 0, 100)
            and previous.humidity_percent - current.humidity_percent
            >= profile.rapid_humidity_drop_percent
        ):
            changes.append("humidity dropped rapidly")
        if (
            availability["smoke"]
            and _valid(previous.smoke_value, 0, 100000)
            and current.smoke_value - previous.smoke_value
            >= max(
                profile.rapid_smoke_change_value,
                previous.smoke_value * profile.rapid_smoke_change_ratio,
            )
        ):
            changes.append("smoke value rose rapidly")
    trend = bool(changes)
    trend_detail = (
        "Rapid change detected: " + ", ".join(changes) + "."
        if changes
        else "No rapid sensor change detected in the available recent history."
    )
    add_signal("rapid_change", "trend", None, trend, profile.rapid_change_points, trend_detail)

    sustained_samples = _sustained_samples(current, history, profile)
    sustained_count = len(sustained_samples)
    sustained_duration = 0.0
    if sustained_count >= 2:
        sustained_times = [_aware_utc(item.timestamp) for item in sustained_samples]
        sustained_duration = (max(sustained_times) - min(sustained_times)).total_seconds()
    sustained = (
        sustained_count >= profile.consecutive_readings_for_sustained
        and sustained_duration >= profile.minimum_sustained_duration_seconds
    )
    sustained_detail = (
        f"Abnormal conditions persisted across {sustained_count} consecutive readings "
        f"over {int(sustained_duration)} seconds."
        if sustained
        else "Sustained abnormal conditions are not yet established."
    )
    add_signal(
        "sustained_abnormal",
        "persistence",
        float(sustained_count),
        sustained,
        profile.sustained_points,
        sustained_detail,
    )

    contradictory = bool(
        smoke is not None
        and smoke >= profile.smoke_elevated_value
        and temperature is not None
        and temperature < 30
        and humidity is not None
        and humidity > 60
    )
    signals.append(
        SignalResult(
            "sensor_disagreement",
            "data_quality",
            all(availability[name] for name in ("temperature", "humidity", "smoke")),
            None,
            contradictory,
            0,
            "Smoke conflicts with cool, humid readings; verify sensor health."
            if contradictory
            else "No direct contradiction among available primary readings.",
        )
    )
    if contradictory:
        reasons.append("Smoke conflicts with cool, humid readings; verify sensor health.")

    missing_primary = primary_sensor_missing
    signals.append(
        SignalResult(
            "data_completeness",
            "data_quality",
            not missing_primary,
            None,
            missing_primary,
            0,
            "One or more primary sensors are unavailable or invalid."
            if missing_primary
            else "All primary sensor channels reported valid values.",
        )
    )
    if missing_primary:
        score = max(score, profile.incomplete_data_score_floor)
        reasons.append(
            "Risk estimate is incomplete because a primary sensor channel is unavailable."
        )
    if not reasons:
        reasons.append("No elevated indicators were found in the available sensor data.")

    score = min(100, max(0, int(score)))
    if (len(corroborating_domains) >= 2 and score >= profile.critical_score_with_corroboration) or (
        sustained and score >= profile.critical_score_when_sustained
    ):
        state = RiskState.CRITICAL
        reasons.append("Critical risk criteria met through corroborated or sustained evidence.")
    elif score >= profile.warning_score:
        state = RiskState.WARNING
        if score >= profile.critical_score_with_corroboration:
            reasons.append(
                "Critical classification withheld because corroboration criteria were not met."
            )
    elif score >= profile.incomplete_data_score_floor:
        state = RiskState.WATCH
    else:
        state = RiskState.NORMAL

    return RiskAssessment(
        risk_state=state,
        risk_score=score,
        reasons=tuple(reasons),
        signals=tuple(signals),
        timestamp=assessment_at,
        is_simulated=current.is_simulated,
        connectivity_state=assess_connectivity(
            connection_time,
            assessed_at=assessment_at,
            profile=profile,
        ),
        profile_version=profile.version,
    )

"""Validated API schemas for stations and sensor readings."""

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

NodeId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]
NodeName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Location = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
OperatorReason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=5, max_length=500),
]
CommandId = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$")]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime) -> str:
    """Serialize a timezone-aware timestamp in a consistent UTC form."""
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def validate_coordinate_pair(latitude: float | None, longitude: float | None) -> None:
    if (latitude is None) != (longitude is None):
        raise ValueError("latitude and longitude must be provided together")


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class NodeCreate(ApiSchema):
    node_id: NodeId
    name: NodeName
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    location: Location | None = None

    @model_validator(mode="after")
    def coordinates_are_paired(self) -> "NodeCreate":
        validate_coordinate_pair(self.latitude, self.longitude)
        return self


class NodeUpdate(ApiSchema):
    name: NodeName | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    location: Location | None = None

    @model_validator(mode="after")
    def update_has_fields_and_coordinate_pair_is_valid(self) -> "NodeUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one station field must be provided")
        if {"latitude", "longitude"}.issubset(self.model_fields_set):
            validate_coordinate_pair(self.latitude, self.longitude)
        return self


class NodeRead(ApiSchema):
    node_id: NodeId
    name: NodeName
    latitude: float | None
    longitude: float | None
    location: str | None
    created_at: datetime
    updated_at: datetime
    last_seen_at: datetime | None
    latest_reading_at: datetime | None
    latest_temperature_c: float | None
    latest_humidity_percent: float | None
    latest_smoke_value: float | None
    latest_gas_value: float | None
    battery_percent: float | None
    latest_is_simulated: bool
    latest_temperature_available: bool
    latest_humidity_available: bool
    latest_smoke_available: bool
    current_risk_state: Literal["NORMAL", "WATCH", "WARNING", "CRITICAL"] | None
    current_risk_score: int | None
    current_risk_reasons: list[str] | None
    current_risk_profile_version: str | None
    risk_assessed_at: datetime | None
    connectivity_state: Literal["ONLINE", "STALE", "OFFLINE"]


class ReadingCreate(ApiSchema):
    node_id: NodeId
    temperature_c: float | None = Field(default=None, ge=-80, le=100)
    humidity_percent: float | None = Field(default=None, ge=0, le=100)
    smoke_value: float | None = Field(default=None, ge=0, le=100000)
    gas_value: float | None = Field(default=None, ge=0, le=100000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    battery_percent: float | None = Field(default=None, ge=0, le=100)
    timestamp: datetime = Field(default_factory=utc_now)
    is_simulated: StrictBool

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_timezone_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def coordinates_are_paired(self) -> "ReadingCreate":
        validate_coordinate_pair(self.latitude, self.longitude)
        if all(
            value is None
            for value in (
                self.temperature_c,
                self.humidity_percent,
                self.smoke_value,
                self.gas_value,
            )
        ):
            raise ValueError("at least one sensor reading must be available")
        return self


class RiskSignalRead(ApiSchema):
    name: str
    domain: str
    available: bool
    value: float | None
    triggered: bool
    points: int
    detail: str


class ReadingRead(ApiSchema):
    id: int
    node_id: NodeId
    temperature_c: float | None
    humidity_percent: float | None
    smoke_value: float | None
    gas_value: float | None
    temperature_available: bool
    humidity_available: bool
    smoke_available: bool
    latitude: float | None
    longitude: float | None
    battery_percent: float | None
    timestamp: datetime
    received_at: datetime
    is_simulated: bool
    risk_state: Literal["NORMAL", "WATCH", "WARNING", "CRITICAL"] | None = None
    risk_score: int | None = None
    risk_reasons: list[str] | None = None
    risk_signals: list[RiskSignalRead] | None = None
    risk_profile_version: str | None = None
    assessment_timestamp: datetime | None = None
    connectivity_state: Literal["ONLINE", "STALE", "OFFLINE"] | None = None


class ReadingPage(ApiSchema):
    items: list[ReadingRead]
    limit: int
    offset: int


class ReadingSeries(ApiSchema):
    node_id: NodeId
    items: list[ReadingRead]
    limit: int


class AlertRead(ApiSchema):
    alert_id: str
    node_id: NodeId
    severity: Literal["WATCH", "WARNING", "CRITICAL"]
    risk_score: int
    reasons: list[str]
    created_at: datetime
    updated_at: datetime
    status: Literal["ACTIVE", "ACKNOWLEDGED", "RESOLVED"]
    is_simulated: bool
    last_reading_id: int | None
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    resolution_reason: str | None


class AlertPage(ApiSchema):
    items: list[AlertRead]
    limit: int
    offset: int


class AlertSummary(ApiSchema):
    active: int
    acknowledged: int
    resolved: int
    by_severity: dict[str, int]


class DeviceCommandCreate(ApiSchema):
    command_type: Literal["REQUEST_STATUS", "SENSOR_SELF_TEST"]
    reason: OperatorReason
    expires_in_seconds: int = Field(default=300, ge=30, le=86400)
    is_simulated: StrictBool


class DeviceCommandAcknowledgement(ApiSchema):
    status: Literal["ACKNOWLEDGED", "COMPLETED", "FAILED"] = "ACKNOWLEDGED"
    result_summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None = None

    @model_validator(mode="after")
    def terminal_status_requires_summary(self) -> "DeviceCommandAcknowledgement":
        if self.status in {"COMPLETED", "FAILED"} and self.result_summary is None:
            raise ValueError("result_summary is required when reporting a final outcome")
        return self


class DeviceCommandAuditEvent(ApiSchema):
    event_id: CommandId
    command_id: CommandId | None
    node_id: str | None
    event_type: Literal[
        "CREATED", "ACKNOWLEDGED", "COMPLETED", "FAILED", "EXPIRED", "REJECTED"
    ]
    actor: str
    event_at: datetime
    details: dict[str, Any]


class DeviceCommandRead(ApiSchema):
    command_id: CommandId
    node_id: NodeId
    command_type: Literal["REQUEST_STATUS", "SENSOR_SELF_TEST"]
    reason: OperatorReason
    created_at: datetime
    expires_at: datetime
    status: Literal["PENDING", "ACKNOWLEDGED", "COMPLETED", "FAILED", "EXPIRED"]
    is_simulated: bool
    created_by: str
    acknowledged_at: datetime | None
    finished_at: datetime | None
    result_summary: str | None
    execution_state: Literal["NOT_DISPATCHED"] = "NOT_DISPATCHED"
    events: list[DeviceCommandAuditEvent] = Field(default_factory=list)


class DeviceCommandPage(ApiSchema):
    items: list[DeviceCommandRead]
    limit: int
    offset: int

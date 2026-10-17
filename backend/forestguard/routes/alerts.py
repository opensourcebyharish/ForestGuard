"""Alert list, summary, and acknowledgement API routes."""

import hmac
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from forestguard.config import Settings, get_settings
from forestguard.schemas import AlertPage, AlertRead, AlertSummary, NodeId
from forestguard.services import (
    AlertAlreadyResolved,
    AlertNotFound,
    acknowledge_alert,
    get_alert_summary,
    list_alerts,
)

router = APIRouter(prefix="/api/alerts", tags=["alerts"])
PageLimit = Annotated[int, Query(ge=1, le=200)]
PageOffset = Annotated[int, Query(ge=0, le=1_000_000)]
AlertStatus = Literal["ACTIVE", "ACKNOWLEDGED", "RESOLVED"]
AlertSeverity = Literal["WATCH", "WARNING", "CRITICAL"]
AlertStatusFilter = Annotated[AlertStatus | None, Query(alias="status")]


def require_alert_operator(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Use the server-configured operator token for alert state changes."""
    expected = settings.device_commands_auth_token
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Operator authorization is not configured",
        )
    scheme, separator, supplied = (authorization or "").partition(" ")
    if (
        separator == ""
        or scheme.lower() != "bearer"
        or not hmac.compare_digest(supplied.strip().encode(), expected.encode())
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid operator authorization is required",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/summary", response_model=AlertSummary)
def get_summary() -> dict:
    return get_alert_summary(get_settings().database_path)


@router.get("", response_model=AlertPage)
def get_alerts(
    limit: PageLimit = 50,
    offset: PageOffset = 0,
    node_id: NodeId | None = None,
    severity: AlertSeverity | None = None,
    alert_status: AlertStatusFilter = None,
    is_simulated: bool | None = None,
) -> dict:
    items = list_alerts(
        get_settings().database_path,
        node_id=node_id,
        severity=severity,
        status=alert_status,
        is_simulated=is_simulated,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "limit": limit, "offset": offset}


@router.post("/{alert_id}/acknowledge", response_model=AlertRead)
def post_acknowledge(
    alert_id: str,
    _operator: None = Depends(require_alert_operator),
) -> dict:
    try:
        return acknowledge_alert(get_settings().database_path, alert_id)
    except AlertNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found"
        ) from error
    except AlertAlreadyResolved as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Resolved alerts cannot be acknowledged",
        ) from error

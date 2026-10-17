"""Authorized, audited APIs for queueing and tracking non-actuating device commands."""

import hmac
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from forestguard.config import Settings, get_settings
from forestguard.device_command_service import (
    CommandNodeNotFound,
    CommandNotFound,
    CommandRateLimitExceeded,
    CommandsDisabled,
    CommandStateConflict,
    CommandTooLong,
    DuplicatePendingCommand,
    acknowledge_command,
    create_command,
    list_commands,
    record_unauthorized_attempt,
)
from forestguard.schemas import (
    DeviceCommandAcknowledgement,
    DeviceCommandCreate,
    DeviceCommandPage,
    DeviceCommandRead,
    NodeId,
)

router = APIRouter(prefix="/api", tags=["device commands"])
PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0, le=1_000_000)]
CommandStatus = Literal["PENDING", "ACKNOWLEDGED", "COMPLETED", "FAILED", "EXPIRED"]


def require_operator(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """Authorize with a server-configured bearer token; never accept a caller identity."""
    expected = settings.device_commands_auth_token
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Command authorization is not configured",
        )
    scheme, separator, supplied = (authorization or "").partition(" ")
    invalid_authorization = (
        separator == ""
        or scheme.lower() != "bearer"
        or not hmac.compare_digest(supplied.strip().encode(), expected.encode())
    )
    if invalid_authorization:
        record_unauthorized_attempt(
            settings.database_path,
            request.path_params.get("node_id"),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid operator authorization is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return settings.device_commands_operator_id


@router.post(
    "/nodes/{node_id}/commands",
    response_model=DeviceCommandRead,
    status_code=status.HTTP_201_CREATED,
)
def post_command(
    node_id: NodeId,
    payload: DeviceCommandCreate,
    operator_id: str = Depends(require_operator),
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict:
    try:
        return create_command(
            settings.database_path,
            node_id,
            payload,
            operator_id=operator_id,
            settings=settings,
        )
    except CommandNodeNotFound as error:
        raise HTTPException(status_code=404, detail="Station not found") from error
    except CommandsDisabled as error:
        raise HTTPException(status_code=403, detail="Real device commands are disabled") from error
    except CommandTooLong as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except DuplicatePendingCommand as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except CommandRateLimitExceeded as error:
        raise HTTPException(
            status_code=429,
            detail=str(error),
            headers={"Retry-After": str(settings.device_command_rate_window_seconds)},
        ) from error


@router.get("/commands", response_model=DeviceCommandPage)
def get_commands(
    limit: PageLimit = 50,
    offset: PageOffset = 0,
    node_id: NodeId | None = None,
    command_status: Annotated[CommandStatus | None, Query(alias="status")] = None,
    is_simulated: bool | None = None,
    operator_id: str = Depends(require_operator),
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict:
    items = list_commands(
        settings.database_path,
        node_id=node_id,
        status=command_status,
        is_simulated=is_simulated,
        limit=limit,
        offset=offset,
        operator_id=operator_id,
    )
    return {"items": items, "limit": limit, "offset": offset}


@router.post("/commands/{command_id}/ack", response_model=DeviceCommandRead)
def post_command_acknowledgement(
    command_id: str,
    payload: DeviceCommandAcknowledgement,
    operator_id: str = Depends(require_operator),
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict:
    if len(command_id) != 32 or any(character not in "0123456789abcdef" for character in command_id):
        raise HTTPException(status_code=404, detail="Command not found")
    try:
        return acknowledge_command(
            settings.database_path,
            command_id,
            payload,
            operator_id=operator_id,
        )
    except CommandNotFound as error:
        raise HTTPException(status_code=404, detail="Command not found") from error
    except CommandStateConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

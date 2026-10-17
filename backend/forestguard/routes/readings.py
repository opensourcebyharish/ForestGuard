"""Sensor-reading ingestion and query routes."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from forestguard.config import get_settings
from forestguard.schemas import NodeId, ReadingCreate, ReadingPage, ReadingRead
from forestguard.services import (
    NodeNotFound,
    ingest_reading,
    list_node_readings,
    list_readings,
)

router = APIRouter(prefix="/api", tags=["readings"])
PageLimit = Annotated[int, Query(ge=1, le=200)]
PageOffset = Annotated[int, Query(ge=0, le=1000000)]


@router.post("/readings", response_model=ReadingRead, status_code=status.HTTP_201_CREATED)
def post_reading(reading: ReadingCreate) -> dict:
    settings = get_settings()
    return ingest_reading(settings.database_path, reading, settings)


@router.get("/readings", response_model=ReadingPage)
def get_readings(
    limit: PageLimit = 50,
    offset: PageOffset = 0,
    node_id: NodeId | None = None,
    is_simulated: bool | None = None,
) -> dict:
    items = list_readings(
        get_settings().database_path,
        node_id=node_id,
        is_simulated=is_simulated,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/nodes/{node_id}/readings", response_model=ReadingPage)
def get_node_readings(
    node_id: NodeId,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> dict:
    try:
        items = list_node_readings(get_settings().database_path, node_id, limit, offset)
    except NodeNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found") from error
    return {"items": items, "limit": limit, "offset": offset}

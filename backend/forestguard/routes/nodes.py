"""Monitoring-station API routes."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from forestguard.config import get_settings
from forestguard.schemas import NodeCreate, NodeId, NodeRead, NodeUpdate, ReadingSeries
from forestguard.services import (
    DuplicateNode,
    InvalidNodeUpdate,
    NodeNotFound,
    create_node,
    get_node,
    list_node_series,
    list_nodes,
    update_node,
)

router = APIRouter(prefix="/api/nodes", tags=["nodes"])
PageLimit = Annotated[int, Query(ge=1, le=200)]
PageOffset = Annotated[int, Query(ge=0, le=1000000)]


@router.get("", response_model=list[NodeRead])
def get_nodes(limit: PageLimit = 50, offset: PageOffset = 0) -> list[dict]:
    return list_nodes(get_settings().database_path, limit, offset)


@router.post("", response_model=NodeRead, status_code=status.HTTP_201_CREATED)
def post_node(node: NodeCreate) -> dict:
    try:
        return create_node(get_settings().database_path, node)
    except DuplicateNode as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Node already exists") from error


@router.get("/{node_id}/series", response_model=ReadingSeries)
def get_node_series(node_id: NodeId, limit: PageLimit = 100) -> dict:
    try:
        return {
            "node_id": node_id,
            "items": list_node_series(get_settings().database_path, node_id, limit),
            "limit": limit,
        }
    except NodeNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found") from error


@router.get("/{node_id}", response_model=NodeRead)
def get_node_by_id(node_id: NodeId) -> dict:
    try:
        return get_node(get_settings().database_path, node_id)
    except NodeNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found") from error


@router.patch("/{node_id}", response_model=NodeRead)
def patch_node(node_id: NodeId, update: NodeUpdate) -> dict:
    try:
        return update_node(get_settings().database_path, node_id, update)
    except NodeNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found") from error
    except InvalidNodeUpdate as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error

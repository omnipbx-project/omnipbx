from fastapi import APIRouter, Depends, HTTPException, status
import psycopg

from app.core.db import get_connection
from app.models.ring_group import RingGroupCreate, RingGroupRead
from app.services.asterisk import sync_asterisk_config
from app.services.ring_groups import create_ring_group, delete_ring_group, list_ring_groups


router = APIRouter(prefix="/api/ring-groups", tags=["ring-groups"])


@router.get("", response_model=list[RingGroupRead])
def get_ring_groups(
    connection: psycopg.Connection = Depends(get_connection),
) -> list[RingGroupRead]:
    return list_ring_groups(connection)


@router.post("", response_model=RingGroupRead, status_code=status.HTTP_201_CREATED)
def post_ring_group(
    payload: RingGroupCreate,
    connection: psycopg.Connection = Depends(get_connection),
) -> RingGroupRead:
    try:
        ring_group = create_ring_group(connection, payload)
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ring group {payload.name} already exists.",
        ) from exc
    sync_asterisk_config(connection)
    return ring_group


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def remove_ring_group(
    name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> None:
    try:
        deleted = delete_ring_group(connection, name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Ring group {name} was not found.")
    sync_asterisk_config(connection)

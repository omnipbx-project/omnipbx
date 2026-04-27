from fastapi import APIRouter, Depends, HTTPException, status
import psycopg

from app.core.db import get_connection
from app.models.queue import QueueCreate, QueueRead
from app.services.asterisk import sync_asterisk_config
from app.services.queues import create_queue, delete_queue, list_queues


router = APIRouter(prefix="/api/queues", tags=["queues"])


@router.get("", response_model=list[QueueRead])
def get_queues(
    connection: psycopg.Connection = Depends(get_connection),
) -> list[QueueRead]:
    return list_queues(connection)


@router.post("", response_model=QueueRead, status_code=status.HTTP_201_CREATED)
def post_queue(
    payload: QueueCreate,
    connection: psycopg.Connection = Depends(get_connection),
) -> QueueRead:
    try:
        queue = create_queue(connection, payload)
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Queue {payload.name} already exists.") from exc
    sync_asterisk_config(connection)
    return queue


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def remove_queue(
    name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> None:
    try:
        deleted = delete_queue(connection, name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Queue {name} was not found.")
    sync_asterisk_config(connection)

from fastapi import APIRouter, Depends, HTTPException, status
import psycopg

from app.core.db import get_connection
from app.models.ivr import IvrCreate, IvrRead
from app.services.asterisk import sync_asterisk_config
from app.services.ivrs import create_ivr, delete_ivr, list_ivrs


router = APIRouter(prefix="/api/ivrs", tags=["ivrs"])


@router.get("", response_model=list[IvrRead])
def get_ivrs(
    connection: psycopg.Connection = Depends(get_connection),
) -> list[IvrRead]:
    return list_ivrs(connection)


@router.post("", response_model=IvrRead, status_code=status.HTTP_201_CREATED)
def post_ivr(
    payload: IvrCreate,
    connection: psycopg.Connection = Depends(get_connection),
) -> IvrRead:
    try:
        ivr = create_ivr(connection, payload)
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"IVR {payload.name} already exists.") from exc
    sync_asterisk_config(connection)
    return ivr


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def remove_ivr(
    name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> None:
    try:
        deleted = delete_ivr(connection, name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"IVR {name} was not found.")
    sync_asterisk_config(connection)

from fastapi import APIRouter, Depends, HTTPException, status
import psycopg

from app.core.db import get_connection
from app.models.trunk import TrunkCreate, TrunkRead
from app.services.asterisk import sync_asterisk_config
from app.services.trunks import create_trunk, delete_trunk, list_trunks


router = APIRouter(prefix="/api/trunks", tags=["trunks"])


@router.get("", response_model=list[TrunkRead])
def get_trunks(
    connection: psycopg.Connection = Depends(get_connection),
) -> list[TrunkRead]:
    return list_trunks(connection)


@router.post("", response_model=TrunkRead, status_code=status.HTTP_201_CREATED)
def post_trunk(
    payload: TrunkCreate,
    connection: psycopg.Connection = Depends(get_connection),
) -> TrunkRead:
    try:
        trunk = create_trunk(connection, payload)
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Trunk {payload.name} already exists.",
        ) from exc

    sync_asterisk_config(connection)
    return trunk


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def remove_trunk(
    name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> None:
    deleted = delete_trunk(connection, name)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trunk {name} was not found.",
        )
    sync_asterisk_config(connection)

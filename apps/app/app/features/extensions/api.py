from fastapi import APIRouter, Depends, HTTPException, status
import psycopg

from app.core.db import get_connection
from app.models.extension import ExtensionCreate, ExtensionRead
from app.services.asterisk import sync_asterisk_config
from app.services.extensions import create_extension, delete_extension, list_extensions


router = APIRouter(prefix="/api/extensions", tags=["extensions"])


@router.get("", response_model=list[ExtensionRead])
def get_extensions(
    connection: psycopg.Connection = Depends(get_connection),
) -> list[ExtensionRead]:
    return list_extensions(connection)


@router.post("", response_model=ExtensionRead, status_code=status.HTTP_201_CREATED)
def post_extension(
    payload: ExtensionCreate,
    connection: psycopg.Connection = Depends(get_connection),
) -> ExtensionRead:
    try:
        extension = create_extension(connection, payload)
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Extension {payload.extension} already exists.",
        ) from exc

    sync_asterisk_config(connection)
    return extension


@router.delete("/{extension}", status_code=status.HTTP_204_NO_CONTENT)
def remove_extension(
    extension: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> None:
    deleted = delete_extension(connection, extension)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Extension {extension} was not found.",
        )
    sync_asterisk_config(connection)

from fastapi import APIRouter, Depends, HTTPException, status
import psycopg

from app.core.db import get_connection
from app.models.working_hours import WorkingHoursCreate, WorkingHoursRead
from app.services.asterisk import sync_asterisk_config
from app.services.working_hours import create_working_hours, delete_working_hours, list_working_hours


router = APIRouter(prefix="/api/working-hours", tags=["working-hours"])


@router.get("", response_model=list[WorkingHoursRead])
def get_working_hours(
    connection: psycopg.Connection = Depends(get_connection),
) -> list[WorkingHoursRead]:
    return list_working_hours(connection)


@router.post("", response_model=WorkingHoursRead, status_code=status.HTTP_201_CREATED)
def post_working_hours(
    payload: WorkingHoursCreate,
    connection: psycopg.Connection = Depends(get_connection),
) -> WorkingHoursRead:
    try:
        schedule = create_working_hours(connection, payload)
    except (psycopg.errors.UniqueViolation, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    sync_asterisk_config(connection)
    return schedule


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def remove_working_hours(
    name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> None:
    deleted = delete_working_hours(connection, name)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Working hours {name} were not found.")
    sync_asterisk_config(connection)

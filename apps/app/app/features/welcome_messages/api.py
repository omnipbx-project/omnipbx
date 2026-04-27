from fastapi import APIRouter, Depends, HTTPException, status
import psycopg

from app.core.db import get_connection
from app.models.welcome_message import WelcomeMessageCreate, WelcomeMessageRead
from app.services.asterisk import sync_asterisk_config
from app.services.welcome_messages import create_welcome_message, delete_welcome_message, list_welcome_messages


router = APIRouter(prefix="/api/welcome-messages", tags=["welcome-messages"])


@router.get("", response_model=list[WelcomeMessageRead])
def get_welcome_messages(
    connection: psycopg.Connection = Depends(get_connection),
) -> list[WelcomeMessageRead]:
    return list_welcome_messages(connection)


@router.post("", response_model=WelcomeMessageRead, status_code=status.HTTP_201_CREATED)
def post_welcome_message(
    payload: WelcomeMessageCreate,
    connection: psycopg.Connection = Depends(get_connection),
) -> WelcomeMessageRead:
    try:
        message = create_welcome_message(connection, payload)
    except (psycopg.errors.UniqueViolation, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    sync_asterisk_config(connection)
    return message


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def remove_welcome_message(
    name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> None:
    deleted = delete_welcome_message(connection, name)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Welcome message {name} was not found.")
    sync_asterisk_config(connection)

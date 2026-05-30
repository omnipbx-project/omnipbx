from fastapi import APIRouter, Depends, Request
import psycopg

from app.core.db import get_connection
from app.models.callback import CallbackFollowupUpdate
from app.services.call_logs import (
    complete_callback_followup,
    list_callback_worklist,
    take_callback_followup,
    update_callback_followup,
)


router = APIRouter(prefix="/api", tags=["callbacks"])


@router.get("/callbacks")
def get_callbacks(
    search: str = "",
    open_only: bool = True,
    limit: int = 500,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    return {"status": "ok", **list_callback_worklist(connection, search=search, open_only=open_only, limit=limit)}


@router.post("/callbacks/{linkedid}/take")
def take_callback(
    request: Request,
    linkedid: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    current_user = getattr(request.state, "current_user", None) or {}
    actor_username = current_user.get("username") or "Team member"
    take_callback_followup(connection, linkedid, actor_username=actor_username)
    return {"status": "ok"}


@router.post("/callbacks/{linkedid}/done")
def complete_callback(
    request: Request,
    linkedid: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    current_user = getattr(request.state, "current_user", None) or {}
    actor_username = current_user.get("username") or "Team member"
    complete_callback_followup(connection, linkedid, actor_username=actor_username)
    return {"status": "ok"}


@router.post("/callbacks/{linkedid}")
def post_callback_followup(
    linkedid: str,
    payload: CallbackFollowupUpdate,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    update_callback_followup(
        connection,
        linkedid,
        completed=payload.completed,
        callback_number=payload.callback_number,
        note=payload.note,
    )
    return {"status": "ok"}

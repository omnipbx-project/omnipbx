from fastapi import APIRouter, Depends
import psycopg

from app.core.db import get_connection
from app.models.callback import CallbackFollowupUpdate
from app.services.call_logs import list_callback_worklist, update_callback_followup


router = APIRouter(prefix="/api", tags=["callbacks"])


@router.get("/callbacks")
def get_callbacks(
    search: str = "",
    open_only: bool = True,
    limit: int = 500,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    return {"status": "ok", **list_callback_worklist(connection, search=search, open_only=open_only, limit=limit)}


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

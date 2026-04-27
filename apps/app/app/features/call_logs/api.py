from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
import psycopg

from app.core.db import get_connection
from app.services.call_logs import list_call_logs, resolve_recording_path, sync_cdr_from_asterisk


router = APIRouter(prefix="/api", tags=["call-logs"])


@router.get("/call-logs")
def get_call_logs(
    search: str = "",
    direction: str = "all",
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 250,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    return {"status": "ok", **list_call_logs(connection, search=search, direction=direction, date_from=date_from, date_to=date_to, limit=limit)}


@router.post("/call-logs/sync")
def sync_call_logs(
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    return {"status": "ok", **sync_cdr_from_asterisk(connection)}


@router.get("/call-recordings/{recordingfile}")
def get_call_recording(recordingfile: str) -> FileResponse:
    path = resolve_recording_path(recordingfile)
    if not path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found.")
    return FileResponse(path, media_type="audio/wav", filename=path.name)

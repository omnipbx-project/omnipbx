from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg
from pydantic import ValidationError
from starlette import status

from app.core.db import get_connection
from app.models.queue import QueueCreate
from app.services.asterisk import sync_asterisk_config
from app.services.audio import save_queue_moh
from app.services.extensions import list_extensions
from app.services.queues import create_queue, delete_queue, list_queues
from app.web import render_template


router = APIRouter(tags=["queues"])


def _parse_members_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@router.get("/queues", response_class=HTMLResponse)
def queues_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    return render_template(
        request,
        "queues/index.html",
        page_title="Queues",
        page_description="Queues are now isolated into their own feature with separate queue definitions, MOH classes, and dialplan generation.",
        active_nav="/queues",
        result=result,
        detail=detail,
        queues=list_queues(connection),
        extensions=list_extensions(connection),
    )


@router.post("/queues/create")
def create_queue_from_ui(
    name: str = Form(...),
    extension: str = Form(...),
    strategy: str = Form(default="ringall"),
    timeout: int = Form(default=20),
    retry: int = Form(default=5),
    wrapuptime: int = Form(default=0),
    max_wait_time_raw: str = Form(default=""),
    members_csv: str = Form(default=""),
    voicemail_mailbox: str = Form(default=""),
    announce_position_raw: str | None = Form(default=None),
    enabled_raw: str | None = Form(default=None),
    voicemail_enabled_raw: str | None = Form(default=None),
    moh_file: UploadFile | None = File(default=None),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        moh_file_name = None
        musicclass = "default"
        if moh_file and moh_file.filename:
            moh_file_name, musicclass = save_queue_moh(moh_file, name)
        payload = QueueCreate(
            name=name,
            extension=extension,
            strategy=strategy,
            timeout=timeout,
            retry=retry,
            wrapuptime=wrapuptime,
            max_wait_time=int(max_wait_time_raw) if max_wait_time_raw.strip() else None,
            announce_position=announce_position_raw is not None,
            musicclass=musicclass,
            moh_file_name=moh_file_name,
            enabled=enabled_raw is not None,
            voicemail_enabled=voicemail_enabled_raw is not None,
            voicemail_mailbox=voicemail_mailbox or None,
            members=_parse_members_csv(members_csv),
        )
        record = create_queue(connection, payload)
    except (ValidationError, psycopg.errors.UniqueViolation, ValueError) as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
        return RedirectResponse(url=f"/queues?{params}", status_code=status.HTTP_303_SEE_OTHER)

    reload_result = sync_asterisk_config(connection)
    params = urlencode(
        {
            "result": "success",
            "detail": f"Saved queue {record['name']}. Asterisk reload status: {reload_result['status']}.",
        }
    )
    return RedirectResponse(url=f"/queues?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/queues/{name}/delete")
def delete_queue_from_ui(
    name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        deleted = delete_queue(connection, name)
    except ValueError as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
        return RedirectResponse(url=f"/queues?{params}", status_code=status.HTTP_303_SEE_OTHER)
    if deleted:
        reload_result = sync_asterisk_config(connection)
        params = urlencode(
            {
                "result": "success",
                "detail": f"Deleted queue {name}. Asterisk reload status: {reload_result['status']}.",
            }
        )
    else:
        params = urlencode({"result": "error", "detail": f"Queue {name} was not found."})
    return RedirectResponse(url=f"/queues?{params}", status_code=status.HTTP_303_SEE_OTHER)

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg
from pydantic import ValidationError
from starlette import status

from app.core.db import get_connection
from app.models.welcome_message import WelcomeMessageCreate
from app.services.asterisk import sync_asterisk_config
from app.services.audio import normalize_sound_name, save_custom_sound
from app.services.inbound_routes import list_inbound_routes
from app.services.welcome_messages import create_welcome_message, delete_welcome_message, list_welcome_messages
from app.web import render_template


router = APIRouter(tags=["welcome-messages"])


@router.get("/welcome-messages", response_class=HTMLResponse)
def welcome_messages_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    return render_template(
        request,
        "welcome_messages/index.html",
        page_title="Welcome Messages",
        page_description="Welcome prompts are managed in their own feature and linked to inbound routes without mixing that logic into routing CRUD.",
        active_nav="/welcome-messages",
        result=result,
        detail=detail,
        welcome_messages=list_welcome_messages(connection),
        routes=list_inbound_routes(connection),
    )


@router.post("/welcome-messages/create")
def create_welcome_message_from_ui(
    name: str = Form(...),
    inbound_route_name: str = Form(...),
    sound_name: str = Form(default=""),
    enabled_raw: str | None = Form(default=None),
    prompt_file: UploadFile | None = File(default=None),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        resolved_sound = normalize_sound_name(sound_name)
        if prompt_file and prompt_file.filename:
            resolved_sound = save_custom_sound(prompt_file, "welcome", name)
        if not resolved_sound:
            raise ValueError("Provide a prompt name or upload a WAV file.")
        payload = WelcomeMessageCreate(
            name=name,
            inbound_route_name=inbound_route_name,
            sound_name=resolved_sound,
            enabled=enabled_raw is not None,
        )
        record = create_welcome_message(connection, payload)
    except (ValidationError, psycopg.errors.UniqueViolation, ValueError) as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
        return RedirectResponse(url=f"/welcome-messages?{params}", status_code=status.HTTP_303_SEE_OTHER)

    reload_result = sync_asterisk_config(connection)
    params = urlencode(
        {
            "result": "success",
            "detail": f"Saved welcome message {record['name']}. Asterisk reload status: {reload_result['status']}.",
        }
    )
    return RedirectResponse(url=f"/welcome-messages?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/welcome-messages/{name}/delete")
def delete_welcome_message_from_ui(
    name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    deleted = delete_welcome_message(connection, name)
    if deleted:
        reload_result = sync_asterisk_config(connection)
        params = urlencode(
            {
                "result": "success",
                "detail": f"Deleted welcome message {name}. Asterisk reload status: {reload_result['status']}.",
            }
        )
    else:
        params = urlencode({"result": "error", "detail": f"Welcome message {name} was not found."})
    return RedirectResponse(url=f"/welcome-messages?{params}", status_code=status.HTTP_303_SEE_OTHER)

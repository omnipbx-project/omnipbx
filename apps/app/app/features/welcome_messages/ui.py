from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
import psycopg
from psycopg.rows import dict_row
from starlette import status

from app.core.db import get_connection
from app.core.settings import get_settings
from app.services.asterisk import sync_asterisk_config
from app.services.call_routing import delete_call_routing_rule, list_call_routing_item_rules, save_call_routing_rule
from app.services.inbound_routes import list_inbound_routes
from app.web import render_template


router = APIRouter(tags=["voicemail"])


@router.get("/welcome-messages", response_class=HTMLResponse)
def voicemail_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    rules = list_call_routing_item_rules(connection, "incoming-calls", "voicemail")
    return render_template(
        request,
        "welcome_messages/index.html",
        page_title="Voicemail",
        page_description="Simple voicemail setup for missed inbound calls.",
        active_nav="/welcome-messages",
        result=result,
        detail=detail,
        routes=list_inbound_routes(connection),
        extensions=_list_extensions(connection),
        voicemail_rules=rules,
        messages=_list_voicemail_messages(),
    )


@router.post("/welcome-messages/create")
def save_voicemail_rule_from_ui(
    inbound_route_name: str = Form(...),
    mailbox: str = Form(...),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        route = inbound_route_name.strip()
        clean_mailbox = "".join(ch for ch in mailbox.strip() if ch.isdigit())
        if not route:
            raise ValueError("Choose where voicemail should be used.")
        if not clean_mailbox:
            raise ValueError("Choose a mailbox.")
        save_call_routing_rule(
            connection,
            section_slug="incoming-calls",
            item_slug="voicemail",
            name=f"voicemail-{route}",
            enabled=True,
            config={"route": route, "mailbox": clean_mailbox},
        )
        reload_result = sync_asterisk_config(connection)
    except (ValueError, psycopg.Error) as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
        return RedirectResponse(url=f"/welcome-messages?{params}", status_code=status.HTTP_303_SEE_OTHER)

    params = urlencode(
        {
            "result": "success",
            "detail": f"Voicemail is ready. Asterisk reload status: {reload_result['status']}.",
        }
    )
    return RedirectResponse(url=f"/welcome-messages?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/welcome-messages/{rule_id}/delete")
def delete_voicemail_rule_from_ui(
    rule_id: int,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    deleted = delete_call_routing_rule(connection, rule_id)
    if deleted:
        reload_result = sync_asterisk_config(connection)
        params = urlencode({"result": "success", "detail": f"Voicemail rule removed. Asterisk reload status: {reload_result['status']}."})
    else:
        params = urlencode({"result": "error", "detail": "Voicemail rule was not found."})
    return RedirectResponse(url=f"/welcome-messages?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/voicemail/messages/{mailbox}/{folder}/{filename}")
def play_voicemail_message(mailbox: str, folder: str, filename: str) -> FileResponse:
    path = _resolve_voicemail_path(mailbox, folder, filename)
    return FileResponse(path, media_type="audio/wav", filename=path.name)


@router.post("/voicemail/messages/{mailbox}/{folder}/{filename}/delete")
def delete_voicemail_message(mailbox: str, folder: str, filename: str) -> RedirectResponse:
    path = _resolve_voicemail_path(mailbox, folder, filename)
    for suffix in (".wav", ".txt", ".WAV", ".gsm"):
        candidate = path.with_suffix(suffix)
        if candidate.exists():
            candidate.unlink()
    params = urlencode({"result": "success", "detail": "Voicemail message deleted."})
    return RedirectResponse(url=f"/welcome-messages?{params}", status_code=status.HTTP_303_SEE_OTHER)


def _list_extensions(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT extension, display_name
            FROM extensions
            WHERE enabled = TRUE
            ORDER BY extension
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def _list_voicemail_messages() -> list[dict]:
    root = Path(get_settings().voicemail_spool_dir)
    messages: list[dict] = []
    for wav_path in sorted(root.glob("default/*/*/msg*.wav"), reverse=True):
        try:
            mailbox = wav_path.parts[-3]
            folder = wav_path.parts[-2]
        except IndexError:
            continue
        messages.append(
            {
                "mailbox": mailbox,
                "folder": folder,
                "filename": wav_path.name,
                "size": wav_path.stat().st_size,
                "created": wav_path.stat().st_mtime,
                "url": f"/voicemail/messages/{mailbox}/{folder}/{wav_path.name}",
            }
        )
    return messages[:100]


def _resolve_voicemail_path(mailbox: str, folder: str, filename: str) -> Path:
    settings = get_settings()
    root = Path(settings.voicemail_spool_dir).resolve()
    clean_mailbox = "".join(ch for ch in mailbox if ch.isdigit())
    clean_folder = folder if folder in {"INBOX", "Old"} else "INBOX"
    clean_filename = Path(filename).name
    if not clean_mailbox or not clean_filename.endswith(".wav"):
        raise HTTPException(status_code=404, detail="Voicemail message not found.")
    path = (root / "default" / clean_mailbox / clean_folder / clean_filename).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Voicemail message not found.") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Voicemail message not found.")
    return path

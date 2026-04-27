from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg
from pydantic import ValidationError
from starlette import status

from app.core.db import get_connection
from app.models.ivr import IvrCreate, IVROptionCreate
from app.services.asterisk import sync_asterisk_config
from app.services.audio import normalize_sound_name, save_custom_sound
from app.services.extensions import list_extensions
from app.services.ivrs import create_ivr, delete_ivr, list_ivrs
from app.services.queues import list_queues
from app.services.ring_groups import list_ring_groups
from app.services.trunks import list_trunks
from app.web import render_template


router = APIRouter(tags=["ivrs"])


def _parse_options_text(value: str) -> list[dict]:
    options: list[dict] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3:
            raise ValueError("IVR options must use: digit,destination_type,destination_value")
        option = IVROptionCreate(digit=parts[0], destination_type=parts[1], destination_value=parts[2])
        options.append(option.model_dump())
    return options


@router.get("/ivrs", response_class=HTMLResponse)
def ivrs_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    return render_template(
        request,
        "ivrs/index.html",
        page_title="IVR",
        page_description="IVR menus are separated into their own feature with prompt storage and digit-to-destination routing.",
        active_nav="/ivrs",
        result=result,
        detail=detail,
        ivrs=list_ivrs(connection),
        extensions=list_extensions(connection),
        trunks=list_trunks(connection),
        queues=list_queues(connection),
        ring_groups=list_ring_groups(connection),
    )


@router.post("/ivrs/create")
def create_ivr_from_ui(
    name: str = Form(...),
    extension: str = Form(...),
    prompt_sound: str = Form(default=""),
    timeout: int = Form(default=5),
    invalid_retries: int = Form(default=2),
    options_text: str = Form(default=""),
    enabled_raw: str | None = Form(default=None),
    prompt_file: UploadFile | None = File(default=None),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        prompt = normalize_sound_name(prompt_sound)
        if prompt_file and prompt_file.filename:
            prompt = save_custom_sound(prompt_file, "ivr", name)
        if not prompt:
            raise ValueError("Provide an IVR prompt name or upload a WAV file.")
        payload = IvrCreate(
            name=name,
            extension=extension,
            prompt=prompt,
            timeout=timeout,
            invalid_retries=invalid_retries,
            options=_parse_options_text(options_text),
            enabled=enabled_raw is not None,
        )
        record = create_ivr(connection, payload)
    except (ValidationError, psycopg.errors.UniqueViolation, ValueError) as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
        return RedirectResponse(url=f"/ivrs?{params}", status_code=status.HTTP_303_SEE_OTHER)

    reload_result = sync_asterisk_config(connection)
    params = urlencode(
        {
            "result": "success",
            "detail": f"Saved IVR {record['name']}. Asterisk reload status: {reload_result['status']}.",
        }
    )
    return RedirectResponse(url=f"/ivrs?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/ivrs/{name}/delete")
def delete_ivr_from_ui(
    name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        deleted = delete_ivr(connection, name)
    except ValueError as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
        return RedirectResponse(url=f"/ivrs?{params}", status_code=status.HTTP_303_SEE_OTHER)
    if deleted:
        reload_result = sync_asterisk_config(connection)
        params = urlencode(
            {
                "result": "success",
                "detail": f"Deleted IVR {name}. Asterisk reload status: {reload_result['status']}.",
            }
        )
    else:
        params = urlencode({"result": "error", "detail": f"IVR {name} was not found."})
    return RedirectResponse(url=f"/ivrs?{params}", status_code=status.HTTP_303_SEE_OTHER)

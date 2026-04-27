from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg
from pydantic import ValidationError
from starlette import status

from app.core.db import get_connection
from app.models.trunk import TrunkCreate
from app.services.asterisk import sync_asterisk_config
from app.services.trunks import create_trunk, delete_trunk, list_trunks
from app.web import render_template


router = APIRouter(tags=["trunks"])


@router.get("/trunks", response_class=HTMLResponse)
def trunks_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    trunks = list_trunks(connection)
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    return render_template(
        request,
        "trunks/index.html",
        page_title="Trunks",
        page_description="Provider connectivity and outbound rules now live in a dedicated OmniPBX feature with file-based PJSIP generation.",
        active_nav="/trunks",
        trunks=trunks,
        result=result,
        detail=detail,
    )


@router.post("/trunks/create")
def create_trunk_from_ui(
    name: str = Form(...),
    provider_name: str = Form(default=""),
    host: str = Form(...),
    username: str = Form(default=""),
    password: str = Form(default=""),
    outbound_prefix: str = Form(default=""),
    strip_digits: int = Form(default=0),
    match_ip: str = Form(default=""),
    register_enabled_raw: str | None = Form(default=None),
    enabled_raw: str | None = Form(default=None),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        payload = TrunkCreate(
            name=name,
            provider_name=provider_name or None,
            host=host,
            username=username or None,
            password=password or None,
            register_enabled=register_enabled_raw is not None,
            outbound_prefix=outbound_prefix or None,
            strip_digits=strip_digits,
            match_ip=match_ip or None,
            enabled=enabled_raw is not None,
        )
        record = create_trunk(connection, payload)
    except (ValidationError, psycopg.errors.UniqueViolation, ValueError) as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
        return RedirectResponse(url=f"/trunks?{params}", status_code=status.HTTP_303_SEE_OTHER)

    reload_result = sync_asterisk_config(connection)
    params = urlencode(
        {
            "result": "success",
            "detail": (
                f"Created trunk {record['name']}. "
                f"Asterisk reload status: {reload_result['status']}."
            ),
        }
    )
    return RedirectResponse(url=f"/trunks?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/trunks/{name}/delete")
def delete_trunk_from_ui(
    name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    deleted = delete_trunk(connection, name)
    if deleted:
        reload_result = sync_asterisk_config(connection)
        params = urlencode(
            {
                "result": "success",
                "detail": (
                    f"Deleted trunk {name}. "
                    f"Asterisk reload status: {reload_result['status']}."
                ),
            }
        )
    else:
        params = urlencode({"result": "error", "detail": f"Trunk {name} was not found."})
    return RedirectResponse(url=f"/trunks?{params}", status_code=status.HTTP_303_SEE_OTHER)

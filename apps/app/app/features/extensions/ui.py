from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg
from starlette import status

from app.core.db import get_connection
from app.features.status.service import collect_status_snapshot
from app.models.extension import ExtensionCreate
from app.services.asterisk import sync_asterisk_config
from app.services.extensions import create_extension, delete_extension, list_extensions
from app.web import render_template


router = APIRouter(tags=["extensions-ui"])


@router.get("/extensions", response_class=HTMLResponse)
def extensions_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    extensions = list_extensions(connection)
    status_snapshot = collect_status_snapshot(connection)
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    status_by_extension = {
        row["extension"]: row["status"] for row in status_snapshot["extensions"]
    }

    return render_template(
        request,
        "extensions/index.html",
        page_title="Extensions",
        page_description="Manage internal endpoints as a dedicated OmniPBX feature instead of one mixed UI file.",
        active_nav="/extensions",
        extensions=extensions,
        status_by_extension=status_by_extension,
        summary=status_snapshot["summary"],
        result=result,
        detail=detail,
    )


@router.post("/extensions/create")
def create_extension_from_ui(
    extension: str = Form(...),
    display_name: str = Form(...),
    secret: str = Form(default=""),
    enabled_raw: str | None = Form(default=None),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    payload = ExtensionCreate(
        extension=extension,
        display_name=display_name,
        secret=secret or None,
        enabled=enabled_raw is not None,
    )
    try:
        record = create_extension(connection, payload)
    except psycopg.errors.UniqueViolation:
        params = urlencode(
            {
                "result": "error",
                "detail": f"Extension {extension} already exists.",
            }
        )
        return RedirectResponse(
            url=f"/extensions?{params}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    reload_result = sync_asterisk_config(connection)
    params = urlencode(
        {
            "result": "success",
            "detail": (
                f"Created extension {record['extension']}. "
                f"Asterisk reload status: {reload_result['status']}."
            ),
        }
    )
    return RedirectResponse(
        url=f"/extensions?{params}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/extensions/{extension}/delete")
def delete_extension_from_ui(
    extension: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    deleted = delete_extension(connection, extension)
    if deleted:
        reload_result = sync_asterisk_config(connection)
        params = urlencode(
            {
                "result": "success",
                "detail": (
                    f"Deleted extension {extension}. "
                    f"Asterisk reload status: {reload_result['status']}."
                ),
            }
        )
    else:
        params = urlencode(
            {
                "result": "error",
                "detail": f"Extension {extension} was not found.",
            }
        )
    return RedirectResponse(
        url=f"/extensions?{params}",
        status_code=status.HTTP_303_SEE_OTHER,
    )

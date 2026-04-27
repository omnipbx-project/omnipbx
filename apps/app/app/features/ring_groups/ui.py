from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg
from pydantic import ValidationError
from starlette import status

from app.core.db import get_connection
from app.models.ring_group import RingGroupCreate
from app.services.asterisk import sync_asterisk_config
from app.services.extensions import list_extensions
from app.services.ring_groups import create_ring_group, delete_ring_group, list_ring_groups
from app.web import render_template


router = APIRouter(tags=["ring-groups"])


def _parse_members_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@router.get("/ring-groups", response_class=HTMLResponse)
def ring_groups_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    return render_template(
        request,
        "ring_groups/index.html",
        page_title="Ring Groups",
        page_description="Ring groups now live in their own OmniPBX feature with clear membership and dialplan generation.",
        active_nav="/ring-groups",
        result=result,
        detail=detail,
        ring_groups=list_ring_groups(connection),
        extensions=list_extensions(connection),
    )


@router.post("/ring-groups/create")
def create_ring_group_from_ui(
    name: str = Form(...),
    extension: str = Form(...),
    ring_strategy: str = Form(default="ringall"),
    ring_timeout: int = Form(default=20),
    members_csv: str = Form(default=""),
    enabled_raw: str | None = Form(default=None),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        payload = RingGroupCreate(
            name=name,
            extension=extension,
            ring_strategy=ring_strategy,
            ring_timeout=ring_timeout,
            members=_parse_members_csv(members_csv),
            enabled=enabled_raw is not None,
        )
        record = create_ring_group(connection, payload)
    except (ValidationError, psycopg.errors.UniqueViolation, ValueError) as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
        return RedirectResponse(url=f"/ring-groups?{params}", status_code=status.HTTP_303_SEE_OTHER)

    reload_result = sync_asterisk_config(connection)
    params = urlencode(
        {
            "result": "success",
            "detail": f"Saved ring group {record['name']}. Asterisk reload status: {reload_result['status']}.",
        }
    )
    return RedirectResponse(url=f"/ring-groups?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/ring-groups/{name}/delete")
def delete_ring_group_from_ui(
    name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        deleted = delete_ring_group(connection, name)
    except ValueError as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
        return RedirectResponse(url=f"/ring-groups?{params}", status_code=status.HTTP_303_SEE_OTHER)
    if deleted:
        reload_result = sync_asterisk_config(connection)
        params = urlencode(
            {
                "result": "success",
                "detail": f"Deleted ring group {name}. Asterisk reload status: {reload_result['status']}.",
            }
        )
    else:
        params = urlencode({"result": "error", "detail": f"Ring group {name} was not found."})
    return RedirectResponse(url=f"/ring-groups?{params}", status_code=status.HTTP_303_SEE_OTHER)

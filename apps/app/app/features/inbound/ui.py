from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg
from pydantic import ValidationError
from starlette import status

from app.core.db import get_connection
from app.services.extensions import list_extensions
from app.models.inbound_route import InboundRouteCreate
from app.services.asterisk import sync_asterisk_config
from app.services.inbound_routes import create_inbound_route, delete_inbound_route, list_inbound_routes, update_inbound_route
from app.services.ivrs import list_ivrs
from app.services.queues import list_queues
from app.services.ring_groups import list_ring_groups
from app.services.trunks import list_trunks
from app.web import render_template


router = APIRouter(tags=["inbound"])


@router.get("/inbound-routes", response_class=HTMLResponse)
def inbound_routes_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    routes = list_inbound_routes(connection)
    trunks = list_trunks(connection)
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    edit_name = request.query_params.get("edit", "")
    edit_route = next((route for route in routes if route["name"] == edit_name), None)
    edit_destination_values = _split_form_values(edit_route["destination_value"]) if edit_route else []
    return render_template(
        request,
        "inbound/index.html",
        page_title="Inbound Routes",
        page_description="Inbound routing now stays focused on DID dispatch while queues, IVRs, ring groups, greetings, and schedules remain separate features.",
        active_nav="/inbound-routes",
        routes=routes,
        trunks=trunks,
        extensions=list_extensions(connection),
        queues=list_queues(connection),
        ivrs=list_ivrs(connection),
        ring_groups=list_ring_groups(connection),
        edit_route=edit_route,
        edit_destination_values=edit_destination_values,
        result=result,
        detail=detail,
        page_css=["/static/css/call_routing.css"],
        page_js=["/static/js/inbound.js"],
    )


@router.post("/inbound-routes/create")
async def create_inbound_route_from_ui(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    form = await request.form()
    destination_values = _split_form_values(form.getlist("destination_value"))
    try:
        payload = InboundRouteCreate(
            name=str(form.get("name", "")),
            trunk_name=str(form.get("trunk_name", "")),
            did_pattern=str(form.get("did_pattern", "")) or None,
            destination_type=str(form.get("destination_type", "")),
            destination_value=", ".join(destination_values),
            enabled=form.get("enabled_raw") is not None,
        )
        record = create_inbound_route(connection, payload)
    except (ValidationError, psycopg.errors.UniqueViolation, ValueError) as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
        return RedirectResponse(url=f"/inbound-routes?{params}", status_code=status.HTTP_303_SEE_OTHER)

    reload_result = sync_asterisk_config(connection)
    params = urlencode(
        {
            "result": "success",
            "detail": (
                f"Created inbound route {record['name']}. "
                f"Asterisk reload status: {reload_result['status']}."
            ),
        }
    )
    return RedirectResponse(url=f"/inbound-routes?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/inbound-routes/{name}/update")
async def update_inbound_route_from_ui(
    name: str,
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    form = await request.form()
    destination_values = _split_form_values(form.getlist("destination_value"))
    try:
        payload = InboundRouteCreate(
            name=str(form.get("new_name", "")),
            trunk_name=str(form.get("trunk_name", "")),
            did_pattern=str(form.get("did_pattern", "")) or None,
            destination_type=str(form.get("destination_type", "")),
            destination_value=", ".join(destination_values),
            enabled=form.get("enabled_raw") is not None,
        )
        record = update_inbound_route(connection, name, payload)
        if not record:
            params = urlencode({"result": "error", "detail": f"Inbound route {name} was not found."})
            return RedirectResponse(url=f"/inbound-routes?{params}", status_code=status.HTTP_303_SEE_OTHER)
    except (ValidationError, psycopg.errors.UniqueViolation, ValueError) as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
        return RedirectResponse(url=f"/inbound-routes?edit={name}&{params}", status_code=status.HTTP_303_SEE_OTHER)

    reload_result = sync_asterisk_config(connection)
    params = urlencode(
        {
            "result": "success",
            "detail": (
                f"Updated inbound route {record['name']}. "
                f"Asterisk reload status: {reload_result['status']}."
            ),
        }
    )
    return RedirectResponse(url=f"/inbound-routes?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/inbound-routes/{name}/delete")
def delete_inbound_route_from_ui(
    name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    deleted = delete_inbound_route(connection, name)
    if deleted:
        reload_result = sync_asterisk_config(connection)
        params = urlencode(
            {
                "result": "success",
                "detail": (
                    f"Deleted inbound route {name}. "
                    f"Asterisk reload status: {reload_result['status']}."
                ),
            }
        )
    else:
        params = urlencode({"result": "error", "detail": f"Inbound route {name} was not found."})
    return RedirectResponse(url=f"/inbound-routes?{params}", status_code=status.HTTP_303_SEE_OTHER)


def _split_form_values(value: object) -> list[str]:
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = str(value or "").split(",")
    return [str(item).strip() for item in raw_values if str(item).strip()]

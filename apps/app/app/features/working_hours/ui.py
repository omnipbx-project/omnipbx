from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg
from pydantic import ValidationError
from starlette import status

from app.core.db import get_connection
from app.models.working_hours import ALLOWED_WEEKDAYS, WorkingHoursCreate
from app.services.asterisk import sync_asterisk_config
from app.services.audio import normalize_sound_name, save_custom_sound
from app.services.inbound_routes import list_inbound_routes
from app.services.working_hours import create_working_hours, delete_working_hours, list_working_hours
from app.web import render_template


router = APIRouter(tags=["working-hours"])
WEEKDAY_ORDER = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


@router.get("/working-hours", response_class=HTMLResponse)
def working_hours_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    return render_template(
        request,
        "working_hours/index.html",
        page_title="Working Hours",
        page_description="Working hours are now their own feature, with route-linked office schedules and after-hours prompts.",
        active_nav="/working-hours",
        result=result,
        detail=detail,
        working_hours=list_working_hours(connection),
        routes=list_inbound_routes(connection),
        weekdays=[day for day in WEEKDAY_ORDER if day in ALLOWED_WEEKDAYS],
    )


@router.post("/working-hours/create")
def create_working_hours_from_ui(
    name: str = Form(...),
    start_day: str = Form(...),
    end_day: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    inbound_route_name: str = Form(...),
    after_hours_sound: str = Form(default=""),
    enabled_raw: str | None = Form(default=None),
    after_hours_file: UploadFile | None = File(default=None),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        sound_name = normalize_sound_name(after_hours_sound)
        if after_hours_file and after_hours_file.filename:
            sound_name = save_custom_sound(after_hours_file, "after_hours", name)
        payload = WorkingHoursCreate(
            name=name,
            start_day=start_day,
            end_day=end_day,
            start_time=start_time,
            end_time=end_time,
            inbound_route_name=inbound_route_name,
            after_hours_sound=sound_name,
            enabled=enabled_raw is not None,
        )
        record = create_working_hours(connection, payload)
    except (ValidationError, psycopg.errors.UniqueViolation, ValueError) as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
        return RedirectResponse(url=f"/working-hours?{params}", status_code=status.HTTP_303_SEE_OTHER)

    reload_result = sync_asterisk_config(connection)
    params = urlencode(
        {
            "result": "success",
            "detail": f"Saved working hours {record['name']}. Asterisk reload status: {reload_result['status']}.",
        }
    )
    return RedirectResponse(url=f"/working-hours?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/working-hours/{name}/delete")
def delete_working_hours_from_ui(
    name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    deleted = delete_working_hours(connection, name)
    if deleted:
        reload_result = sync_asterisk_config(connection)
        params = urlencode(
            {
                "result": "success",
                "detail": f"Deleted working hours {name}. Asterisk reload status: {reload_result['status']}.",
            }
        )
    else:
        params = urlencode({"result": "error", "detail": f"Working hours {name} were not found."})
    return RedirectResponse(url=f"/working-hours?{params}", status_code=status.HTTP_303_SEE_OTHER)

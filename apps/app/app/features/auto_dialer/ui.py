from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg
from starlette import status

from app.core.db import get_connection
from app.services.auto_dialer import (
    delete_campaign,
    delete_lead,
    detect_phone_column,
    fetch_google_sheet_csv,
    get_campaign,
    import_leads,
    list_all_leads,
    list_ready_campaign_callers,
    list_campaigns,
    list_leads,
    parse_lead_file,
    parse_pasted_leads,
    save_campaign,
    set_campaign_status,
    start_lead_call,
)
from app.services.extensions import list_extensions
from app.services.trunks import list_trunks
from app.services.user_management import list_groups
from app.web import render_template


router = APIRouter(tags=["auto-dialer"])


@router.get("/call-routing/auto-dialer/campaigns", response_class=HTMLResponse)
def campaign_dialer_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    edit_id = request.query_params.get("edit_id", "")
    campaigns = list_campaigns(connection)
    edit_campaign = next((campaign for campaign in campaigns if str(campaign["id"]) == edit_id), None)
    return render_template(
        request,
        "auto_dialer/index.html",
        page_title="Campaign Dialer",
        page_description="",
        active_nav="/call-routing",
        campaigns=campaigns,
        edit_campaign=edit_campaign,
        trunks=list_trunks(connection),
        groups=list_groups(connection),
        extensions=list_extensions(connection),
        result=request.query_params.get("result", ""),
        detail=request.query_params.get("detail", ""),
        page_css=["/static/css/call_routing.css", "/static/css/auto_dialer.css"],
        page_js=["/static/js/call_routing.js", "/static/js/auto_dialer.js"],
        topbar_search={"placeholder": "Search campaign or number...", "label": "Search campaign dialer"},
    )


@router.get("/call-routing/auto-dialer/leads", response_class=HTMLResponse)
def campaign_leads_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    selected_campaign_id = _int_query(request.query_params.get("campaign_id", ""))
    campaigns = list_campaigns(connection)
    selected_campaign = next((campaign for campaign in campaigns if campaign["id"] == selected_campaign_id), None)
    leads = list_all_leads(connection, selected_campaign_id)
    caller_options_by_campaign = {
        campaign["id"]: list_ready_campaign_callers(connection, campaign)
        for campaign in campaigns
    }
    return render_template(
        request,
        "auto_dialer/leads.html",
        page_title="Leads",
        page_description="",
        active_nav="/call-routing/auto-dialer/leads",
        campaigns=campaigns,
        selected_campaign=selected_campaign,
        selected_campaign_id=selected_campaign_id,
        leads=leads,
        caller_options_by_campaign=caller_options_by_campaign,
        result=request.query_params.get("result", ""),
        detail=request.query_params.get("detail", ""),
        page_css=["/static/css/call_routing.css", "/static/css/auto_dialer.css"],
        page_js=["/static/js/auto_dialer.js"],
        topbar_search={"placeholder": "Search lead or number...", "label": "Search leads"},
    )


@router.post("/call-routing/auto-dialer/campaigns/save")
async def save_campaign_from_ui(
    request: Request,
    campaign_id: int | None = Form(default=None),
    name: str = Form(...),
    trunk_name: str = Form(...),
    dialing_mode: str = Form(default="preview"),
    next_call_wait_seconds: int = Form(default=5),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    form = await request.form()
    try:
        campaign = save_campaign(
            connection,
            campaign_id=campaign_id,
            name=name,
            trunk_name=trunk_name,
            dialing_mode=dialing_mode,
            next_call_wait_seconds=next_call_wait_seconds,
            assigned_users=_assigned_values(form, "user"),
            assigned_groups=_assigned_values(form, "group"),
        )
        detail = f"Saved {campaign['name']}."
        result = "success"
    except Exception as exc:
        detail = str(exc)
        result = "error"
    return _redirect(result, detail)


@router.post("/call-routing/auto-dialer/campaigns/{campaign_id}/delete")
def delete_campaign_from_ui(
    campaign_id: int,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    deleted = delete_campaign(connection, campaign_id)
    return _redirect("success" if deleted else "error", "Campaign deleted." if deleted else "Campaign was not found.")


@router.post("/call-routing/auto-dialer/campaigns/{campaign_id}/status")
def set_campaign_status_from_ui(
    campaign_id: int,
    campaign_status: str = Form(...),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    updated = set_campaign_status(connection, campaign_id, campaign_status)
    return _redirect("success" if updated else "error", f"Campaign marked {campaign_status}." if updated else "Campaign was not found.")


@router.post("/call-routing/auto-dialer/campaigns/{campaign_id}/leads/{lead_id}/delete")
def delete_lead_from_ui(
    campaign_id: int,
    lead_id: int,
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    deleted = delete_lead(connection, campaign_id, lead_id)
    params = urlencode(
        {
            "result": "success" if deleted else "error",
            "detail": "Lead deleted." if deleted else "Lead was not found.",
        }
    )
    if request.query_params.get("return_to") == "leads":
        return RedirectResponse(
            url=f"/call-routing/auto-dialer/leads?{params}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(
        url=f"/call-routing/auto-dialer/campaigns/{campaign_id}?{params}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/call-routing/auto-dialer/campaigns/{campaign_id}/leads/{lead_id}/call")
def call_lead_from_ui(
    campaign_id: int,
    lead_id: int,
    request: Request,
    caller_extension: str = Form(default=""),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        detail = start_lead_call(connection, campaign_id, lead_id, caller_extension)
        result = "success"
    except Exception as exc:
        detail = str(exc)
        result = "error"
    params = urlencode({"result": result, "detail": detail})
    if request.query_params.get("return_to") == "leads":
        return RedirectResponse(
            url=f"/call-routing/auto-dialer/leads?{params}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(
        url=f"/call-routing/auto-dialer/campaigns/{campaign_id}?{params}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/call-routing/auto-dialer/campaigns/{campaign_id}", response_class=HTMLResponse)
def campaign_detail_page(
    campaign_id: int,
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    campaign = get_campaign(connection, campaign_id)
    if not campaign:
        return RedirectResponse(url="/call-routing/auto-dialer/campaigns?result=error&detail=Campaign+was+not+found.", status_code=status.HTTP_303_SEE_OTHER)
    return render_template(
        request,
        "auto_dialer/detail.html",
        page_title=campaign["name"],
        page_description="",
        active_nav="/call-routing",
        campaign=campaign,
        leads=list_leads(connection, campaign_id),
        caller_options=list_ready_campaign_callers(connection, campaign),
        result=request.query_params.get("result", ""),
        detail=request.query_params.get("detail", ""),
        import_columns=request.query_params.get("columns", "").split(",") if request.query_params.get("columns") else [],
        detected_phone=request.query_params.get("phone", ""),
        page_css=["/static/css/call_routing.css", "/static/css/auto_dialer.css"],
        page_js=["/static/js/auto_dialer.js"],
        topbar_search={"placeholder": "Search name or number...", "label": "Search campaign numbers"},
    )


@router.post("/call-routing/auto-dialer/campaigns/{campaign_id}/leads/import")
async def import_leads_from_ui(
    campaign_id: int,
    lead_file: UploadFile | None = File(default=None),
    google_sheet_url: str = Form(default=""),
    pasted_leads: str = Form(default=""),
    phone_column: str = Form(default=""),
    name_column: str = Form(default=""),
    company_column: str = Form(default=""),
    email_column: str = Form(default=""),
    note_column: str = Form(default=""),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        rows, columns = await _read_import_rows(lead_file, google_sheet_url, pasted_leads)
        if not rows:
            raise ValueError("No numbers were found in the upload.")
        phone = phone_column.strip()
        result = import_leads(
            connection,
            campaign_id=campaign_id,
            rows=rows,
            phone_column=phone,
            name_column=name_column.strip(),
            company_column=company_column.strip(),
            email_column=email_column.strip(),
            note_column=note_column.strip(),
        )
        params = urlencode({"result": "success", "detail": result.message})
    except Exception as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
    return RedirectResponse(
        url=f"/call-routing/auto-dialer/campaigns/{campaign_id}?{params}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/call-routing/auto-dialer/leads/import")
async def import_leads_from_leads_page(
    campaign_id: int = Form(...),
    lead_file: UploadFile | None = File(default=None),
    google_sheet_url: str = Form(default=""),
    pasted_leads: str = Form(default=""),
    lead_name: str = Form(default=""),
    phone_column: str = Form(default=""),
    name_column: str = Form(default=""),
    company_column: str = Form(default=""),
    email_column: str = Form(default=""),
    note_column: str = Form(default=""),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        campaign = get_campaign(connection, campaign_id)
        if not campaign:
            raise ValueError("Choose a campaign before uploading leads.")
        rows, columns = await _read_import_rows(lead_file, google_sheet_url, pasted_leads)
        if not rows:
            raise ValueError("No numbers were found in the upload.")
        default_lead_name = lead_name.strip()
        if default_lead_name:
            for row in rows:
                row.setdefault("lead_name", default_lead_name)
        result = import_leads(
            connection,
            campaign_id=campaign_id,
            rows=rows,
            phone_column=phone_column.strip(),
            name_column=name_column.strip() or "lead_name",
            company_column=company_column.strip(),
            email_column=email_column.strip(),
            note_column=note_column.strip() or "note",
        )
        params = urlencode({"result": "success", "detail": result.message})
    except Exception as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
    return RedirectResponse(
        url=f"/call-routing/auto-dialer/leads?{params}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


async def _read_import_rows(
    lead_file: UploadFile | None,
    google_sheet_url: str,
    pasted_leads: str,
) -> tuple[list[dict[str, str]], list[str]]:
    if lead_file and lead_file.filename:
        return parse_lead_file(lead_file.filename, await lead_file.read())
    if google_sheet_url.strip():
        return fetch_google_sheet_csv(google_sheet_url)
    if pasted_leads.strip():
        return parse_pasted_leads(pasted_leads)
    raise ValueError("Upload a contact list, paste numbers, or add a Google Sheet link.")


def _redirect(result: str, detail: str) -> RedirectResponse:
    params = urlencode({"result": result, "detail": detail})
    return RedirectResponse(url=f"/call-routing/auto-dialer/campaigns?{params}", status_code=status.HTTP_303_SEE_OTHER)


def _int_query(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _assigned_values(form, kind: str) -> list[str]:
    source_type = str(form.get("source_type") or "").strip()
    if source_type:
        if source_type != kind:
            return []
        return [str(value) for value in form.getlist("source_values")]
    field_name = "assigned_users" if kind == "user" else "assigned_groups"
    return [str(value) for value in form.getlist(field_name)]

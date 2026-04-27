from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
import psycopg

from app.core.db import get_connection
from app.core.settings import get_settings
from app.models.setup import SetupWizardPayload
from app.services.setup import get_environment_summary, get_internal_root_ca_path, get_system_settings, save_setup_wizard
from app.web import render_template


router = APIRouter(tags=["setup"])


@router.get("/setup", response_class=HTMLResponse)
def setup_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    system_settings = get_system_settings(connection)
    env_summary = get_environment_summary(request.url.hostname)
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    public_url = system_settings.get("public_base_url") or f"http://127.0.0.1:{get_settings().http_port}"
    root_ca_path = get_internal_root_ca_path()
    return render_template(
        request,
        "setup/index.html",
        page_title="Setup Wizard",
        page_description="Walk through a simple first-time install for OmniPBX with guided access, HTTPS, admin, and PBX defaults.",
        active_nav="/setup",
        system_settings=system_settings,
        env_summary=env_summary,
        result=result,
        detail=detail,
        deployment_modes=[
            {
                "value": "office",
                "label": "Office or Home PBX",
                "description": "Best for local networks, shops, and small offices.",
            },
            {
                "value": "public_server",
                "label": "Public Internet or Cloud",
                "description": "Best when OmniPBX will be reachable from the public internet.",
            },
            {
                "value": "advanced",
                "label": "Advanced Network",
                "description": "Use this if you already know you need more custom networking later.",
            },
        ],
        access_modes=[
            {
                "value": "local_network",
                "label": "Private Network HTTPS",
                "description": "Best for office LAN or private IP use. OmniPBX sets up local HTTPS with its own trusted local CA.",
            },
            {
                "value": "public_domain",
                "label": "Recommended: Domain + Free HTTPS",
                "description": "Best production option. Use a real public domain and OmniPBX will request free HTTPS automatically.",
            },
            {
                "value": "public_ip",
                "label": "Public IP + Free HTTPS",
                "description": "Advanced option when you do not have a domain. Works with public IP certificates and shorter renewal cycles.",
            },
            {
                "value": "private_self_hosted",
                "label": "Upload Existing Certificate",
                "description": "Advanced option for teams who already manage their own certificate files.",
            },
            {
                "value": "http_only",
                "label": "No HTTPS Yet",
                "description": "Temporary setup mode. Start with HTTP now and switch to HTTPS after the PBX is online.",
            },
        ],
        countries=[
            {"value": "Bangladesh", "label": "Bangladesh"},
            {"value": "United States", "label": "United States"},
            {"value": "United Kingdom", "label": "United Kingdom"},
            {"value": "United Arab Emirates", "label": "United Arab Emirates"},
            {"value": "India", "label": "India"},
        ],
        languages=[
            {"value": "en", "label": "English"},
            {"value": "bn", "label": "Bangla"},
            {"value": "ar", "label": "Arabic"},
            {"value": "hi", "label": "Hindi"},
        ],
        show_shell=bool(system_settings.get("setup_completed")),
        public_url=public_url,
        local_ca_ready=root_ca_path.is_file(),
    )


@router.post("/setup")
def save_setup_page(
    request: Request,
    company_name: str = Form(...),
    country: str = Form(default="Bangladesh"),
    timezone: str = Form(...),
    default_language: str = Form(default="en"),
    dialing_region: str = Form(default="+880"),
    deployment_mode: str = Form(default="office"),
    access_mode: str = Form(default="local_network"),
    behind_nat_raw: str | None = Form(default=None),
    external_host: str = Form(default=""),
    ssl_contact_email: str = Form(default=""),
    admin_username: str = Form(...),
    admin_password: str = Form(...),
    admin_email: str = Form(default=""),
    sip_port: int = Form(default=5060),
    rtp_start: int = Form(default=10000),
    rtp_end: int = Form(default=20000),
    local_networks: str = Form(default=""),
    first_extension: str = Form(default=""),
    first_extension_name: str = Form(default=""),
    first_extension_secret: str = Form(default=""),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    try:
        env_summary = get_environment_summary(request.url.hostname if request else None)
        derived_host = (external_host or "").strip() or env_summary["detected_host"]
        ssl_mode = {
            "local_network": "internal_local",
            "public_domain": "public_domain",
            "public_ip": "public_ip",
            "private_self_hosted": "custom_certificate",
            "http_only": "http",
        }.get(access_mode, "http")
        payload = SetupWizardPayload(
            company_name=company_name,
            country=country,
            timezone=timezone,
            default_language=default_language,
            dialing_region=dialing_region,
            deployment_mode=deployment_mode,
            access_mode=access_mode,
            behind_nat=behind_nat_raw is not None,
            external_host=derived_host if access_mode != "http_only" else external_host,
            ssl_mode=ssl_mode,
            ssl_contact_email=ssl_contact_email,
            admin_username=admin_username,
            admin_password=admin_password,
            admin_email=admin_email,
            sip_port=sip_port,
            rtp_start=rtp_start,
            rtp_end=rtp_end,
            local_networks=local_networks,
            first_extension=first_extension,
            first_extension_name=first_extension_name,
            first_extension_secret=first_extension_secret,
        )
        result = save_setup_wizard(connection, payload)
        detail = f"Setup saved. Access OmniPBX at {result['settings'].get('public_base_url') or 'http://127.0.0.1:18000'}"
        params = urlencode({"result": "success", "detail": detail})
        return RedirectResponse(url=f"/setup?{params}", status_code=303)
    except ValueError as exc:
        params = urlencode({"result": "error", "detail": str(exc)})
        return RedirectResponse(url=f"/setup?{params}", status_code=303)
    except Exception as exc:  # pragma: no cover - defensive route fallback
        params = urlencode({"result": "error", "detail": f"Setup failed: {exc}"})
        return RedirectResponse(url=f"/setup?{params}", status_code=303)


@router.get("/setup/internal-ca.crt")
def download_internal_ca() -> FileResponse:
    path = get_internal_root_ca_path()
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The local CA root is not available yet.")
    return FileResponse(path, filename="omnipbx-local-root-ca.crt", media_type="application/x-x509-ca-cert")

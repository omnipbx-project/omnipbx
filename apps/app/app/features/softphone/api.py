from fastapi import APIRouter, Depends, HTTPException, Request, status
import psycopg

from app.core.db import get_connection
from app.models.softphone import SoftphoneDndPayload, SoftphoneSettingsPayload
from app.services.softphone import (
    build_softphone_bootstrap,
    get_softphone_settings,
    resolve_current_webphone,
    save_softphone_settings,
    set_softphone_dnd,
)


router = APIRouter(prefix="/api/softphone", tags=["softphone"])


@router.get("/settings")
def get_softphone_settings_api(
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    return {"status": "ok", "settings": get_softphone_settings(connection)}


@router.post("/settings")
def post_softphone_settings_api(
    payload: SoftphoneSettingsPayload,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    return {"status": "ok", "settings": save_softphone_settings(connection, payload)}


@router.get("/bootstrap")
def get_softphone_bootstrap_api(
    extension: str,
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    return {
        "status": "ok",
        "config": build_softphone_bootstrap(
            connection,
            extension,
            request_host=request.headers.get("host", ""),
            request_scheme=_request_scheme(request),
        ),
    }


@router.get("/bootstrap/current")
def get_current_softphone_bootstrap_api(
    request: Request,
    extension: str = "",
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    current_user = getattr(request.state, "current_user", None) or {}
    role = str(current_user.get("role") or "")
    can_switch = role in {"owner", "admin"}
    return {
        "status": "ok",
        **resolve_current_webphone(
            connection,
            username=str(current_user.get("extension") or current_user.get("username") or ""),
            extension=extension,
            request_host=request.headers.get("host", ""),
            request_scheme=_request_scheme(request),
            can_switch=can_switch,
        ),
    }


@router.post("/dnd/{extension}")
def post_softphone_dnd_api(
    request: Request,
    extension: str,
    payload: SoftphoneDndPayload,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    _require_own_extension(request, extension)
    set_softphone_dnd(connection, extension, payload.enabled)
    return {"status": "ok", "extension": extension, "dnd": payload.enabled}


def _request_scheme(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    return forwarded or request.url.scheme


def _require_own_extension(request: Request, extension: str) -> None:
    current_user = getattr(request.state, "current_user", None) or {}
    if current_user.get("role") != "user":
        return
    own_extension = str(current_user.get("extension") or current_user.get("username") or "")
    if extension != own_extension:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only change your own webphone.",
        )

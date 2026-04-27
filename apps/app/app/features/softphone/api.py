from fastapi import APIRouter, Depends
import psycopg

from app.core.db import get_connection
from app.models.softphone import SoftphoneDndPayload, SoftphoneSettingsPayload
from app.services.softphone import (
    build_softphone_bootstrap,
    get_softphone_settings,
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
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    return {"status": "ok", "config": build_softphone_bootstrap(connection, extension)}


@router.post("/dnd/{extension}")
def post_softphone_dnd_api(
    extension: str,
    payload: SoftphoneDndPayload,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    set_softphone_dnd(connection, extension, payload.enabled)
    return {"status": "ok", "extension": extension, "dnd": payload.enabled}

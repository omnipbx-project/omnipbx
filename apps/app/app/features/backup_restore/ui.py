from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
import psycopg

from app.core.db import get_connection
from app.services.admin_accounts import role_can_manage_admins
from app.services.audit import log_admin_event, list_admin_audit_entries
from app.services.backup import (
    create_backup_bundle,
    get_backup_dir,
    list_backup_files,
    restore_backup_bundle,
)
from app.web import render_template


router = APIRouter(tags=["backup-restore"])


@router.get("/backup-restore", response_class=HTMLResponse)
def backup_restore_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    current_user = request.state.current_user
    backups = list_backup_files()
    recent_audit = list_admin_audit_entries(connection, limit=10)
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    return render_template(
        request,
        "backup_restore/index.html",
        page_title="Backup & Restore",
        page_description="Create lightweight OmniPBX backups and restore account/system settings when you need a safe recovery point.",
        active_nav="/backup-restore",
        backups=backups,
        recent_audit=recent_audit,
        can_manage=bool(current_user and role_can_manage_admins(current_user.get("role"))),
        result=result,
        detail=detail,
    )


@router.post("/backup-restore/create")
def create_backup_from_ui(
    request: Request,
    label: str = Form(default=""),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    current_user = request.state.current_user
    if not current_user or not role_can_manage_admins(current_user.get("role")):
        return _redirect_with_message("error", "Only owner admins can create backups.")
    backup_path = create_backup_bundle(connection, label=label.strip() or "OmniPBX backup", actor_username=current_user["username"])
    log_admin_event(
        connection,
        event_type="backup.create",
        actor_admin_id=int(current_user["id"]),
        actor_username=current_user["username"],
        target_kind="backup",
        target_value=backup_path.name,
        message="Created a backup snapshot",
    )
    return _redirect_with_message("success", f"Backup created: {backup_path.name}")


@router.get("/backup-restore/download/{file_name}")
def download_backup(file_name: str) -> FileResponse:
    backup_dir = get_backup_dir()
    safe_name = Path(file_name).name
    path = backup_dir / safe_name
    if not path.is_file() or path.suffix != ".json":
        raise HTTPException(status_code=404, detail="Backup file not found.")
    return FileResponse(path, filename=safe_name, media_type="application/json")


@router.post("/backup-restore/restore")
async def restore_backup_from_ui(
    request: Request,
    backup_file: UploadFile = File(...),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    current_user = request.state.current_user
    if not current_user or not role_can_manage_admins(current_user.get("role")):
        return _redirect_with_message("error", "Only owner admins can restore a backup.")
    raw = await backup_file.read()
    if not raw:
        return _redirect_with_message("error", "Backup file is empty.")
    try:
        import json

        payload = json.loads(raw.decode("utf-8"))
        restore_backup_bundle(connection, payload)
    except Exception as exc:
        return _redirect_with_message("error", f"Restore failed: {exc}")
    log_admin_event(
        connection,
        event_type="backup.restore",
        actor_admin_id=int(current_user["id"]),
        actor_username=current_user["username"],
        target_kind="backup",
        target_value=backup_file.filename or "uploaded-backup",
        message="Restored a backup snapshot",
    )
    return _redirect_with_message("success", "Backup restored successfully.")


def _redirect_with_message(result: str, detail: str) -> RedirectResponse:
    params = urlencode({"result": result, "detail": detail})
    return RedirectResponse(url=f"/backup-restore?{params}", status_code=303)

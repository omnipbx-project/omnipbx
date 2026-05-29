from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg
from starlette import status

from app.core.db import get_connection
from app.models.extension import ExtensionCreate
from app.services.asterisk import sync_asterisk_config
from app.services.extensions import (
    create_extension,
    delete_extension,
    list_extensions,
    update_extension_enabled,
    update_extension_user,
)
from app.services.user_management import (
    create_group,
    create_permission,
    delete_group,
    delete_permission,
    ensure_profile,
    list_groups,
    list_permissions,
    profiles_by_extension,
    save_user_photo,
)
from app.web import render_template


router = APIRouter(tags=["extensions-ui"])

ALLOWED_USER_TRANSPORTS = {"transport-udp", "transport-udp-softphone", "transport-wss"}


@router.get("/extensions", response_class=HTMLResponse)
def extensions_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    extensions = list_extensions(connection)
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    status_by_extension = {row["extension"]: "Unknown" for row in extensions}
    groups = list_groups(connection)
    permissions = list_permissions(connection)

    return render_template(
        request,
        "extensions/index.html",
        page_title="Users",
        page_description="",
        active_nav="/extensions",
        extensions=extensions,
        status_by_extension=status_by_extension,
        profiles_by_extension=profiles_by_extension(connection),
        groups=groups,
        permissions=permissions,
        summary={
            "extensions_total": len(extensions),
            "extensions_online": 0,
            "extensions_offline": 0,
            "extensions_unknown": len(extensions),
        },
        result=result,
        detail=detail,
        topbar_action={"id": "users-primary-action", "label": "+ Add User"},
        page_css=["/static/css/users.css"],
        page_js=["/static/js/users.js"],
    )


@router.post("/extensions/create")
def create_extension_from_ui(
    extension: str = Form(...),
    display_name: str = Form(...),
    secret: str = Form(default=""),
    enabled_raw: str | None = Form(default=None),
    email: str = Form(default=""),
    group_name: str = Form(default=""),
    transport: str = Form(default="transport-udp"),
    photo: UploadFile | None = File(default=None),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    extension_value = extension.strip()
    if not extension_value.isdigit() or not 1 <= int(extension_value) <= 9999:
        params = urlencode(
            {
                "result": "error",
                "detail": "Extension must be a number from 1 to 9999.",
            }
        )
        return RedirectResponse(
            url=f"/extensions?{params}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    payload = ExtensionCreate(
        extension=extension_value,
        display_name=display_name.strip(),
        secret=secret.strip() or None,
        transport=transport if transport in ALLOWED_USER_TRANSPORTS else "transport-udp",
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
    photo_path = save_user_photo(record["extension"], photo)
    ensure_profile(
        connection,
        extension=record["extension"],
        email=email,
        group_name=group_name,
        photo_path=photo_path,
    )
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


@router.post("/extensions/{extension}/update")
def update_extension_from_ui(
    extension: str,
    display_name: str = Form(...),
    new_extension: str = Form(...),
    secret: str = Form(default=""),
    email: str = Form(default=""),
    group_name: str = Form(default=""),
    transport: str = Form(default="transport-udp"),
    photo: UploadFile | None = File(default=None),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    extension_value = new_extension.strip()
    if not extension_value.isdigit() or not 1 <= int(extension_value) <= 9999:
        params = urlencode(
            {
                "result": "error",
                "detail": "Extension must be a number from 1 to 9999.",
            }
        )
        return RedirectResponse(url=f"/extensions?{params}", status_code=status.HTTP_303_SEE_OTHER)
    if secret.strip() and len(secret.strip()) < 8:
        params = urlencode({"result": "error", "detail": "Password must be at least 8 characters."})
        return RedirectResponse(url=f"/extensions?{params}", status_code=status.HTTP_303_SEE_OTHER)

    try:
        updated = update_extension_user(
            connection,
            extension,
            extension_value,
            display_name.strip(),
            transport if transport in ALLOWED_USER_TRANSPORTS else "transport-udp",
            secret.strip() or None,
        )
    except psycopg.errors.UniqueViolation:
        params = urlencode(
            {
                "result": "error",
                "detail": f"Extension {extension_value} already exists.",
            }
        )
        return RedirectResponse(url=f"/extensions?{params}", status_code=status.HTTP_303_SEE_OTHER)
    if updated:
        reload_result = sync_asterisk_config(connection)
        photo_path = save_user_photo(updated["extension"], photo)
        ensure_profile(
            connection,
            extension=updated["extension"],
            email=email,
            group_name=group_name,
            photo_path=photo_path,
        )
        params = urlencode(
            {
                "result": "success",
                "detail": (
                    f"Updated user {updated['extension']}. "
                    f"Asterisk reload status: {reload_result['status']}."
                ),
            }
        )
    else:
        params = urlencode({"result": "error", "detail": f"User {extension} was not found."})
    return RedirectResponse(url=f"/extensions?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/extensions/groups/create")
def create_group_from_ui(
    group_name: str = Form(...),
    group_description: str = Form(default=""),
    group_permission: str = Form(default="User"),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    create_group(
        connection,
        name=group_name,
        description=group_description,
        permission_name=group_permission,
    )
    params = urlencode({"result": "success", "detail": f"Saved group {group_name.strip()}."})
    return RedirectResponse(url=f"/extensions?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/extensions/permissions/create")
def create_permission_from_ui(
    permission_name: str = Form(...),
    permission_description: str = Form(default=""),
    permission_features: str = Form(default=""),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    create_permission(
        connection,
        name=permission_name,
        description=permission_description,
        features=permission_features,
    )
    params = urlencode({"result": "success", "detail": f"Saved permission {permission_name.strip()}."})
    return RedirectResponse(url=f"/extensions?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/extensions/groups/{group_name}/delete")
def delete_group_from_ui(
    group_name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    deleted = delete_group(connection, group_name)
    detail = f"Deleted group {group_name}." if deleted else f"Group {group_name} was not found."
    params = urlencode({"result": "success" if deleted else "error", "detail": detail})
    return RedirectResponse(url=f"/extensions?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/extensions/permissions/{permission_name}/delete")
def delete_permission_from_ui(
    permission_name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    deleted = delete_permission(connection, permission_name)
    detail = f"Deleted permission {permission_name}." if deleted else f"Permission {permission_name} was not found."
    params = urlencode({"result": "success" if deleted else "error", "detail": detail})
    return RedirectResponse(url=f"/extensions?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/extensions/{extension}/set-enabled")
def set_extension_enabled_from_ui(
    extension: str,
    enabled_raw: str | None = Form(default=None),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    enabled = enabled_raw == "on"
    updated = update_extension_enabled(connection, extension, enabled)
    if updated:
        reload_result = sync_asterisk_config(connection)
        state = "enabled" if enabled else "disabled"
        params = urlencode(
            {
                "result": "success",
                "detail": (
                    f"User {extension} {state}. "
                    f"Asterisk reload status: {reload_result['status']}."
                ),
            }
        )
    else:
        params = urlencode({"result": "error", "detail": f"User {extension} was not found."})
    return RedirectResponse(url=f"/extensions?{params}", status_code=status.HTTP_303_SEE_OTHER)


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

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg
from starlette import status

from app.core.db import get_connection
from app.services.admin_accounts import (
    ADMIN_ROLE_ADMIN,
    ADMIN_ROLE_OWNER,
    ADMIN_ROLE_READ_ONLY,
    change_admin_password,
    change_own_password,
    count_owner_admins,
    create_admin_account,
    delete_admin_account,
    get_smtp_settings,
    list_admin_accounts,
    save_smtp_settings,
    role_can_manage_admins,
    role_label,
    update_admin_profile,
)
from app.services.audit import log_admin_event
from app.services.mailer import send_smtp_test_email, smtp_is_ready
from app.web import render_template


router = APIRouter(tags=["admin-accounts"])


@router.get("/admin-accounts", response_class=HTMLResponse)
def admin_accounts_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    current_user = request.state.current_user
    smtp_settings = get_smtp_settings(connection)
    admins = list_admin_accounts(connection)
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    return render_template(
        request,
        "admin_accounts/index.html",
        page_title="Admin Accounts",
        page_description="Manage PBX administrators, roles, recovery, and SMTP for email-based password reset.",
        active_nav="/admin-accounts",
        admins=admins,
        current_user_id=current_user["id"] if current_user else None,
        current_user_role=current_user["role"] if current_user else None,
        owner_count=count_owner_admins(connection),
        smtp_settings=smtp_settings,
        smtp_ready=smtp_is_ready(smtp_settings),
        result=result,
        detail=detail,
    )


@router.post("/admin-accounts/create")
def create_admin_from_ui(
    request: Request,
    username: str = Form(...),
    email: str = Form(default=""),
    password: str = Form(...),
    role: str = Form(default=ADMIN_ROLE_ADMIN),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    current_user = request.state.current_user
    if not current_user or not role_can_manage_admins(current_user.get("role")):
        return _redirect_with_message("error", "Only owner admins can create other admin accounts.")
    try:
        create_admin_account(
            connection,
            username=username.strip(),
            email=(email or "").strip() or None,
            password=password,
            role=role,
        )
    except psycopg.errors.UniqueViolation:
        return _redirect_with_message("error", f"Admin username {username.strip()} already exists.")
    log_admin_event(
        connection,
        event_type="admin.create",
        actor_admin_id=int(current_user["id"]),
        actor_username=current_user["username"],
        target_kind="admin",
        target_value=username.strip(),
        message=f"Created admin account {username.strip()}",
        details={"role": role},
    )
    return _redirect_with_message("success", f"Created admin account {username.strip()}.")


@router.post("/admin-accounts/change-password")
def change_own_password_from_ui(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    current_user = request.state.current_user
    if not current_user:
        return RedirectResponse(url="/login?next=/admin-accounts", status_code=status.HTTP_303_SEE_OTHER)
    if new_password != confirm_password:
        return _redirect_with_message("error", "New password and confirmation do not match.")
    try:
        change_own_password(
            connection,
            admin_id=int(current_user["id"]),
            current_password=current_password,
            new_password=new_password,
        )
    except ValueError as exc:
        return _redirect_with_message("error", str(exc))
    log_admin_event(
        connection,
        event_type="admin.password_change",
        actor_admin_id=int(current_user["id"]),
        actor_username=current_user["username"],
        target_kind="admin",
        target_value=current_user["username"],
        message="Current admin changed their own password",
    )
    return _redirect_with_message("success", "Your password was updated.")


@router.post("/admin-accounts/set-password")
def set_admin_password_from_ui(
    request: Request,
    admin_id: int = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    current_user = request.state.current_user
    if not current_user or not role_can_manage_admins(current_user.get("role")):
        return _redirect_with_message("error", "Only owner admins can set another admin password.")
    if new_password != confirm_password:
        return _redirect_with_message("error", "New password and confirmation do not match.")
    updated = change_admin_password(connection, admin_id=admin_id, new_password=new_password)
    if not updated:
        return _redirect_with_message("error", "Admin account was not found.")
    log_admin_event(
        connection,
        event_type="admin.password_set",
        actor_admin_id=int(current_user["id"]),
        actor_username=current_user["username"],
        target_kind="admin",
        target_value=updated["username"],
        message=f"Owner set password for {updated['username']}",
    )
    return _redirect_with_message("success", f"Updated password for {updated['username']}.")


@router.post("/admin-accounts/update")
def update_admin_profile_from_ui(
    request: Request,
    admin_id: int = Form(...),
    email: str = Form(default=""),
    role: str = Form(default=ADMIN_ROLE_ADMIN),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    current_user = request.state.current_user
    if not current_user or not role_can_manage_admins(current_user.get("role")):
        return _redirect_with_message("error", "Only owner admins can update other admin profiles.")
    updated = update_admin_profile(
        connection,
        admin_id=admin_id,
        email=(email or "").strip() or None,
        role=role,
    )
    if not updated:
        return _redirect_with_message("error", "Admin account was not found.")
    log_admin_event(
        connection,
        event_type="admin.profile_update",
        actor_admin_id=int(current_user["id"]),
        actor_username=current_user["username"],
        target_kind="admin",
        target_value=updated["username"],
        message=f"Updated profile for {updated['username']}",
        details={"role": updated.get("role"), "email": updated.get("email")},
    )
    return _redirect_with_message("success", f"Updated profile for {updated['username']}.")


@router.post("/admin-accounts/{admin_id}/delete")
def delete_admin_from_ui(
    request: Request,
    admin_id: int,
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    current_user = request.state.current_user
    if not current_user or not role_can_manage_admins(current_user.get("role")):
        return _redirect_with_message("error", "Only owner admins can delete admin accounts.")
    try:
        deleted = delete_admin_account(connection, admin_id=admin_id, acting_admin_id=int(current_user["id"]))
    except ValueError as exc:
        return _redirect_with_message("error", str(exc))
    if not deleted:
        return _redirect_with_message("error", "Admin account was not found.")
    log_admin_event(
        connection,
        event_type="admin.delete",
        actor_admin_id=int(current_user["id"]),
        actor_username=current_user["username"],
        target_kind="admin",
        target_value=str(admin_id),
        message="Deleted admin account",
    )
    return _redirect_with_message("success", "Admin account removed.")


@router.post("/admin-accounts/smtp")
def save_smtp_from_ui(
    request: Request,
    enabled_raw: str | None = Form(default=None),
    mail_from: str = Form(default=""),
    mail_from_name: str = Form(default=""),
    mail_username: str = Form(default=""),
    mail_server: str = Form(default=""),
    mail_port: int = Form(default=587),
    mail_password: str = Form(default=""),
    mail_starttls_raw: str | None = Form(default=None),
    mail_ssl_tls_raw: str | None = Form(default=None),
    use_credentials_raw: str | None = Form(default=None),
    validate_certs_raw: str | None = Form(default=None),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    current_user = request.state.current_user
    save_smtp_settings(
        connection,
        enabled=enabled_raw is not None,
        mail_from=mail_from.strip() or None,
        mail_from_name=mail_from_name.strip() or None,
        mail_username=mail_username.strip() or None,
        mail_server=mail_server.strip() or None,
        mail_port=mail_port,
        mail_password=mail_password.strip() or None,
        mail_starttls=mail_starttls_raw is not None,
        mail_ssl_tls=mail_ssl_tls_raw is not None,
        use_credentials=use_credentials_raw is not None,
        validate_certs=validate_certs_raw is not None,
    )
    log_admin_event(
        connection,
        event_type="smtp.save",
        actor_admin_id=int(current_user["id"]) if current_user else None,
        actor_username=current_user["username"] if current_user else None,
        target_kind="smtp",
        target_value="settings",
        message="SMTP settings updated",
        details={"enabled": enabled_raw is not None, "mail_server": mail_server.strip() or None, "mail_port": mail_port},
    )
    return _redirect_with_message("success", "SMTP settings saved.")


@router.post("/admin-accounts/smtp/test")
async def send_smtp_test_from_ui(
    request: Request,
    test_email: str = Form(...),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    current_user = request.state.current_user
    smtp_settings = get_smtp_settings(connection)
    if not smtp_is_ready(smtp_settings):
        return _redirect_with_message("error", "SMTP is not ready yet. Save a complete SMTP configuration first.")
    try:
        sent = await send_smtp_test_email(connection, recipient=test_email.strip())
    except Exception as exc:  # pragma: no cover - network dependent
        return _redirect_with_message("error", f"SMTP test failed: {exc}")
    if not sent:
        return _redirect_with_message("error", "SMTP is not ready yet. Save a complete SMTP configuration first.")
    log_admin_event(
        connection,
        event_type="smtp.test",
        actor_admin_id=int(current_user["id"]) if current_user else None,
        actor_username=current_user["username"] if current_user else None,
        target_kind="smtp",
        target_value=test_email.strip(),
        message="Sent SMTP test email",
    )
    return _redirect_with_message("success", f"Sent a test email to {test_email.strip()}.")


def _redirect_with_message(result: str, detail: str) -> RedirectResponse:
    params = urlencode({"result": result, "detail": detail})
    return RedirectResponse(url=f"/admin-accounts?{params}", status_code=status.HTTP_303_SEE_OTHER)

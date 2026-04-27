from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.settings import get_settings
import psycopg

from app.core.db import get_connection
from app.services.admin_accounts import get_smtp_settings
from app.services.audit import log_admin_event
from app.services.auth import (
    AUTH_COOKIE_NAME,
    authenticate_admin,
    clear_session_cookie,
    consume_password_reset_token,
    generate_password_reset_token,
    get_reset_token_record,
    has_admin_users,
    is_reset_token_usable,
    issue_session_cookie,
)
from app.services.mailer import send_password_reset_email, smtp_is_ready
from app.services.setup import get_system_settings, is_setup_complete
from app.web import render_template


router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    if not is_setup_complete(connection):
        return RedirectResponse(url="/setup", status_code=307)
    if not has_admin_users(connection):
        return RedirectResponse(url="/setup?result=error&detail=Create+the+first+admin+account+to+enable+login.", status_code=303)
    if getattr(request.state, "current_user", None):
        return RedirectResponse(url="/dashboard", status_code=303)
    error = request.query_params.get("error", "")
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    next_url = request.query_params.get("next", "/dashboard")
    return render_template(
        request,
        "auth/login.html",
        page_title="Login",
        page_description="Sign in to OmniPBX with the owner or admin account you created during setup.",
        active_nav="/login",
        show_shell=False,
        error=error,
        result=result,
        detail=detail,
        next_url=next_url,
        smtp_ready=smtp_is_ready(get_smtp_settings(connection)),
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next_url: str = Form(default="/dashboard"),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    if not is_setup_complete(connection):
        return RedirectResponse(url="/setup", status_code=307)

    admin = authenticate_admin(connection, username.strip(), password)
    if not admin:
        log_admin_event(
            connection,
            event_type="auth.login_failed",
            actor_username=username.strip() or None,
            target_kind="login",
            target_value=username.strip() or None,
            message="Invalid login attempt",
        )
        params = urlencode({"error": "Invalid username or password.", "next": next_url})
        return RedirectResponse(url=f"/login?{params}", status_code=303)

    response = RedirectResponse(url=_safe_next_path(next_url), status_code=303)
    session_cookie = issue_session_cookie(connection, admin)
    response.set_cookie(
        AUTH_COOKIE_NAME,
        session_cookie,
        httponly=True,
        samesite="lax",
        secure=_request_is_secure(request),
        max_age=60 * 60 * 12,
        path="/",
    )
    log_admin_event(
        connection,
        event_type="auth.login",
        actor_admin_id=int(admin["id"]),
        actor_username=admin["username"],
        target_kind="session",
        target_value=admin["username"],
        message="Admin logged in",
    )
    return response


@router.get("/logout")
def logout(request: Request, connection: psycopg.Connection = Depends(get_connection)) -> RedirectResponse:
    current_user = getattr(request.state, "current_user", None)
    if current_user:
        log_admin_event(
            connection,
            event_type="auth.logout",
            actor_admin_id=int(current_user["id"]),
            actor_username=current_user["username"],
            target_kind="session",
            target_value=current_user["username"],
            message="Admin logged out",
        )
    response = RedirectResponse(url="/login", status_code=303)
    clear_session_cookie(response)
    return response


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    if not is_setup_complete(connection):
        return RedirectResponse(url="/setup", status_code=307)
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    smtp_ready = smtp_is_ready(get_smtp_settings(connection))
    return render_template(
        request,
        "auth/forgot_password.html",
        page_title="Forgot Password",
        page_description="Request a one-time password reset link by email for an OmniPBX admin account.",
        active_nav="/forgot-password",
        show_shell=False,
        result=result,
        detail=detail,
        smtp_ready=smtp_ready,
    )


@router.post("/forgot-password")
def forgot_password_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    if not is_setup_complete(connection):
        return RedirectResponse(url="/setup", status_code=307)
    smtp_settings = get_smtp_settings(connection)
    if not smtp_is_ready(smtp_settings):
        params = urlencode({"result": "error", "detail": "Password reset email is not configured yet. Ask an owner admin to complete SMTP setup."})
        return RedirectResponse(url=f"/forgot-password?{params}", status_code=303)
    normalized_email = email.strip().lower()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, username, email
            FROM admin_users
            WHERE lower(email) = %(email)s
            """,
            {"email": normalized_email},
        )
        row = cursor.fetchone()
    if row:
        admin_id, username, recipient = row
        token = generate_password_reset_token(
            connection,
            admin_user_id=int(admin_id),
            requested_ip=request.client.host if request.client else None,
        )
        public_base_url = get_system_settings(connection).get("public_base_url") or str(request.base_url).rstrip("/")
        reset_url = f"{public_base_url}/reset-password?token={token}"
        background_tasks.add_task(_send_reset_email_task, recipient, username, reset_url)
        log_admin_event(
            connection,
            event_type="auth.password_reset_requested",
            actor_admin_id=int(admin_id),
            actor_username=username,
            target_kind="reset",
            target_value=username,
            message="Password reset email queued",
        )
    params = urlencode({"result": "success", "detail": "If that email matches an admin account, a reset link has been sent."})
    return RedirectResponse(url=f"/forgot-password?{params}", status_code=303)


@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(
    request: Request,
    token: str = "",
    connection: psycopg.Connection = Depends(get_connection),
) -> HTMLResponse:
    if not is_setup_complete(connection):
        return RedirectResponse(url="/setup", status_code=307)
    result = request.query_params.get("result", "")
    detail = request.query_params.get("detail", "")
    token_record = get_reset_token_record(connection, token) if token else None
    token_valid = is_reset_token_usable(token_record)
    return render_template(
        request,
        "auth/reset_password.html",
        page_title="Reset Password",
        page_description="Set a new OmniPBX admin password using the one-time reset link sent by email.",
        active_nav="/reset-password",
        show_shell=False,
        result=result,
        detail=detail,
        token=token,
        token_valid=token_valid,
        token_username=token_record["username"] if token_record else None,
    )


@router.post("/reset-password")
def reset_password_submit(
    token: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    connection: psycopg.Connection = Depends(get_connection),
) -> RedirectResponse:
    if new_password != confirm_password:
        params = urlencode({"result": "error", "detail": "New password and confirmation do not match.", "token": token})
        return RedirectResponse(url=f"/reset-password?{params}", status_code=303)
    updated = consume_password_reset_token(connection, token, new_password)
    if not updated:
        params = urlencode({"result": "error", "detail": "That reset link is invalid or has expired.", "token": token})
        return RedirectResponse(url=f"/reset-password?{params}", status_code=303)
    log_admin_event(
        connection,
        event_type="auth.password_reset_completed",
        actor_admin_id=int(updated["id"]),
        actor_username=updated["username"],
        target_kind="reset",
        target_value=updated["username"],
        message="Password reset completed",
    )
    params = urlencode({"result": "success", "detail": "Your password has been reset. You can sign in now."})
    return RedirectResponse(url=f"/login?{params}", status_code=303)


def _safe_next_path(next_url: str) -> str:
    if not next_url.startswith("/") or next_url.startswith("//"):
        return "/dashboard"
    return next_url


def _request_is_secure(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or forwarded_proto == "https"


async def _send_reset_email_task(recipient: str, username: str, reset_url: str) -> None:
    settings = get_settings()
    with psycopg.connect(settings.db_dsn, autocommit=True) as connection:
        await send_password_reset_email(
            connection,
            recipient=recipient,
            username=username,
            reset_url=reset_url,
        )

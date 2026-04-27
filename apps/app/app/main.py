from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.system import router as system_router
from app.core.db import initialize_schema
from app.core.settings import get_settings
from app.features.admin_accounts.ui import router as admin_accounts_ui_router
from app.features.api_push.api import router as api_push_api_router
from app.features.api_push.ui import router as api_push_ui_router
from app.features.audit_log.ui import router as audit_log_ui_router
from app.features.backup_restore.ui import router as backup_restore_ui_router
from app.features.auth.ui import router as auth_ui_router
from app.features.callbacks.api import router as callbacks_api_router
from app.features.callbacks.ui import router as callbacks_ui_router
from app.features.call_logs.api import router as call_logs_api_router
from app.features.call_logs.ui import router as call_logs_ui_router
from app.features.dashboard.ui import router as dashboard_ui_router
from app.features.extensions.api import router as extensions_api_router
from app.features.extensions.ui import router as extensions_ui_router
from app.features.inbound.api import router as inbound_api_router
from app.features.inbound.ui import router as inbound_ui_router
from app.features.ivrs.api import router as ivrs_api_router
from app.features.ivrs.ui import router as ivrs_ui_router
from app.features.queues.api import router as queues_api_router
from app.features.queues.ui import router as queues_ui_router
from app.features.ring_groups.api import router as ring_groups_api_router
from app.features.ring_groups.ui import router as ring_groups_ui_router
from app.features.setup.ui import router as setup_ui_router
from app.features.softphone.api import router as softphone_api_router
from app.features.softphone.ui import router as softphone_ui_router
from app.features.status.ui import router as status_ui_router
from app.features.trunks.api import router as trunks_api_router
from app.features.trunks.ui import router as trunks_ui_router
from app.features.welcome_messages.api import router as welcome_messages_api_router
from app.features.welcome_messages.ui import router as welcome_messages_ui_router
from app.features.working_hours.api import router as working_hours_api_router
from app.features.working_hours.ui import router as working_hours_ui_router
from app.services.asterisk import sync_asterisk_config
from app.services.api_push import start_api_push_worker
from app.services.auth import AUTH_COOKIE_NAME, has_admin_users, resolve_session
from app.services.setup import get_system_settings, is_setup_complete, render_caddyfile, write_caddyfile
import psycopg


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_schema()
    with psycopg.connect(settings.db_dsn, autocommit=True) as connection:
        sync_asterisk_config(connection, reload_config=True)
        write_caddyfile(render_caddyfile(get_system_settings(connection)))
    start_api_push_worker()
    yield

app = FastAPI(
    title="OmniPBX",
    version=settings.app_version,
    summary="Portable business PBX built with Asterisk and FastAPI.",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(setup_ui_router)
app.include_router(auth_ui_router)
app.include_router(admin_accounts_ui_router)
app.include_router(api_push_api_router)
app.include_router(api_push_ui_router)
app.include_router(audit_log_ui_router)
app.include_router(callbacks_api_router)
app.include_router(callbacks_ui_router)
app.include_router(call_logs_api_router)
app.include_router(call_logs_ui_router)
app.include_router(dashboard_ui_router)
app.include_router(extensions_api_router)
app.include_router(extensions_ui_router)
app.include_router(inbound_api_router)
app.include_router(inbound_ui_router)
app.include_router(ivrs_api_router)
app.include_router(ivrs_ui_router)
app.include_router(queues_api_router)
app.include_router(queues_ui_router)
app.include_router(ring_groups_api_router)
app.include_router(ring_groups_ui_router)
app.include_router(backup_restore_ui_router)
app.include_router(softphone_api_router)
app.include_router(softphone_ui_router)
app.include_router(status_ui_router)
app.include_router(system_router)
app.include_router(trunks_api_router)
app.include_router(trunks_ui_router)
app.include_router(welcome_messages_api_router)
app.include_router(welcome_messages_ui_router)
app.include_router(working_hours_api_router)
app.include_router(working_hours_ui_router)


@app.middleware("http")
async def setup_guard(request: Request, call_next):
    path = request.url.path
    public_prefixes = ("/static", "/health", "/login", "/forgot-password", "/reset-password")

    with psycopg.connect(settings.db_dsn, autocommit=True) as connection:
        setup_complete = is_setup_complete(connection)
        admin_ready = has_admin_users(connection)
        current_user = resolve_session(connection, request.cookies.get(AUTH_COOKIE_NAME))
        request.state.current_user = current_user

        if not setup_complete or not admin_ready:
            if path.startswith("/setup") or path.startswith(public_prefixes):
                return await call_next(request)
            return RedirectResponse(url="/setup", status_code=307)

        if path.startswith("/setup"):
            if current_user:
                return await call_next(request)
            return RedirectResponse(url=f"/login?next={path}", status_code=303)

        if path.startswith(public_prefixes):
            return await call_next(request)

        if current_user:
            if current_user.get("role") == "read_only" and request.method not in {"GET", "HEAD", "OPTIONS"}:
                if path not in {"/admin-accounts/change-password"}:
                    return PlainTextResponse("Read-only accounts cannot modify OmniPBX.", status_code=403)
            return await call_next(request)

    return RedirectResponse(url=f"/login?next={path}", status_code=303)


@app.get("/")
async def root(request: Request) -> RedirectResponse:
    with psycopg.connect(settings.db_dsn, autocommit=True) as connection:
        if not is_setup_complete(connection) or not has_admin_users(connection):
            target = "/setup"
        elif resolve_session(connection, request.cookies.get(AUTH_COOKIE_NAME)):
            target = "/dashboard"
        else:
            target = "/login"
    return RedirectResponse(url=target, status_code=307)


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "database_host": settings.db_host,
        "asterisk_generated_dir": settings.generated_config_dir,
    }

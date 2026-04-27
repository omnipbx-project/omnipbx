from fastapi import APIRouter, Depends, HTTPException, Request, status
import psycopg

from app.core.db import get_connection
from app.core.settings import get_settings
from app.services.asterisk import sync_asterisk_config
from app.services.audit import log_admin_event
from app.services.updates import get_update_overview, start_detached_update


router = APIRouter(prefix="/api/system", tags=["system"])


@router.post("/reload")
def reload_asterisk(
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str | int]:
    return sync_asterisk_config(connection)


@router.get("/update")
def update_status() -> dict[str, object]:
    return get_update_overview(get_settings())


@router.post("/update/check")
def check_for_update() -> dict[str, object]:
    return get_update_overview(get_settings(), force_refresh=True)


@router.post("/update/run", status_code=status.HTTP_202_ACCEPTED)
def run_update(
    request: Request,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    current_user = getattr(request.state, "current_user", None)
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    try:
        result = start_detached_update(get_settings())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    log_admin_event(
        connection,
        event_type="system.update_requested",
        actor_admin_id=int(current_user["id"]),
        actor_username=current_user["username"],
        target_kind="system",
        target_value="omnipbx",
        message=f"Requested OmniPBX update to {result['target_version']}",
        details={"job_container_id": result.get("job_container_id", ""), "target_version": result["target_version"]},
    )
    return result

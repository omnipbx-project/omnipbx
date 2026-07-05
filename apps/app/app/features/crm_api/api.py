from fastapi import APIRouter, Depends, Query
import psycopg
from psycopg.rows import dict_row

from app.core.db import get_connection
from app.models.callback import CallbackFollowupUpdate
from app.services.call_logs import (
    list_call_logs,
    list_callback_worklist,
    sync_cdr_from_asterisk,
    update_callback_followup,
    visible_cdr_condition,
)
from app.services.crm_api import require_crm_api_key
from app.services.date_ranges import resolve_date_range
from app.services.setup import get_system_settings


router = APIRouter(prefix="/crm-api", tags=["crm-api"], dependencies=[Depends(require_crm_api_key)])


@router.get("/health")
def crm_api_health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/call-data")
def get_crm_call_data(
    limit: int = Query(default=1000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    direction: str = "all",
    linkedid: str = "",
    uniqueid: str = "",
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    sync_cdr_from_asterisk(connection)
    where = [visible_cdr_condition()]
    params: dict[str, object] = {"limit": limit, "offset": offset}
    if direction != "all":
        where.append("COALESCE(direction, 'unknown') = %(direction)s")
        params["direction"] = direction
    if linkedid.strip():
        where.append("COALESCE(linkedid, '') = %(linkedid)s")
        params["linkedid"] = linkedid.strip()
    if uniqueid.strip():
        where.append("uniqueid = %(uniqueid)s")
        params["uniqueid"] = uniqueid.strip()

    where_sql = " AND ".join(where)
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(f"SELECT COUNT(*) AS total FROM cdr_raw WHERE {where_sql}", params)
        total = int(cursor.fetchone()["total"])
        cursor.execute(
            f"""
            SELECT
                id,
                TO_CHAR(calldate, 'YYYY-MM-DD HH24:MI:SS') AS calldate,
                uniqueid,
                linkedid,
                src,
                dst,
                clid,
                channel,
                dstchannel,
                dcontext,
                lastapp,
                lastdata,
                duration,
                billsec,
                disposition,
                amaflags,
                accountcode,
                peeraccount,
                userfield,
                sequence,
                recordingfile,
                direction,
                trunk_name,
                route_name,
                queue_name,
                ivr_name,
                caller_extension,
                callee_extension,
                TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI:SS') AS created_at,
                TO_CHAR(updated_at, 'YYYY-MM-DD HH24:MI:SS') AS updated_at
            FROM cdr_raw
            WHERE {where_sql}
            ORDER BY calldate DESC NULLS LAST, id DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            params,
        )
        rows = list(cursor.fetchall())
    return {
        "status": "ok",
        "total": total,
        "limit": limit,
        "offset": offset,
        "rows": rows,
    }


@router.get("/call-logs")
def get_crm_call_logs(
    search: str = "",
    direction: str = "all",
    category: str = "all",
    range: str = "7d",
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 250,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    timezone_name = str(get_system_settings(connection).get("timezone") or "UTC")
    resolved_range = resolve_date_range(
        range,
        date_from=date_from or "",
        date_to=date_to or "",
        default="7d",
        timezone_name=timezone_name,
    )
    return {
        "status": "ok",
        **list_call_logs(
            connection,
            search=search,
            direction=direction,
            category=category,
            date_from=resolved_range.date_from,
            date_to=resolved_range.date_to,
            timezone_name=timezone_name,
            limit=limit,
        ),
    }


@router.get("/callbacks")
def get_crm_callbacks(
    search: str = "",
    open_only: bool = True,
    limit: int = 500,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, object]:
    return {"status": "ok", **list_callback_worklist(connection, search=search, open_only=open_only, limit=limit)}


@router.post("/callbacks/{linkedid}")
def update_crm_callback(
    linkedid: str,
    payload: CallbackFollowupUpdate,
    connection: psycopg.Connection = Depends(get_connection),
) -> dict[str, str]:
    update_callback_followup(
        connection,
        linkedid,
        completed=payload.completed,
        callback_number=payload.callback_number,
        note=payload.note,
    )
    return {"status": "ok"}

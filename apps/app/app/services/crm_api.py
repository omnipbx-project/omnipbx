from __future__ import annotations

import secrets

from fastapi import Depends, Header, HTTPException
import psycopg
from psycopg.rows import dict_row
from starlette import status

from app.core.db import get_connection


def get_crm_api_key(connection: psycopg.Connection) -> str:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT api_key FROM api_push_settings WHERE id = 1")
        row = cursor.fetchone()
    return str(row.get("api_key") or "").strip() if row else ""


def is_valid_crm_api_key(connection: psycopg.Connection, supplied_key: str | None) -> bool:
    configured_key = get_crm_api_key(connection)
    candidate = str(supplied_key or "").strip()
    return bool(configured_key and candidate and secrets.compare_digest(configured_key, candidate))


def require_crm_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    connection: psycopg.Connection = Depends(get_connection),
) -> None:
    if not is_valid_crm_api_key(connection, x_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing CRM API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

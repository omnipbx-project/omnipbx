from fastapi import APIRouter, Depends, HTTPException, status
import psycopg

from app.core.db import get_connection
from app.models.inbound_route import InboundRouteCreate, InboundRouteRead
from app.services.asterisk import sync_asterisk_config
from app.services.inbound_routes import create_inbound_route, delete_inbound_route, list_inbound_routes


router = APIRouter(prefix="/api/inbound-routes", tags=["inbound-routes"])


@router.get("", response_model=list[InboundRouteRead])
def get_inbound_routes(
    connection: psycopg.Connection = Depends(get_connection),
) -> list[InboundRouteRead]:
    return list_inbound_routes(connection)


@router.post("", response_model=InboundRouteRead, status_code=status.HTTP_201_CREATED)
def post_inbound_route(
    payload: InboundRouteCreate,
    connection: psycopg.Connection = Depends(get_connection),
) -> InboundRouteRead:
    try:
        route = create_inbound_route(connection, payload)
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Inbound route {payload.name} already exists.",
        ) from exc

    sync_asterisk_config(connection)
    return route


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def remove_inbound_route(
    name: str,
    connection: psycopg.Connection = Depends(get_connection),
) -> None:
    deleted = delete_inbound_route(connection, name)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inbound route {name} was not found.",
        )
    sync_asterisk_config(connection)

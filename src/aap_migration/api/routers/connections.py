from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from aap_migration.api.dependencies import get_db
from aap_migration.api.models import Connection
from aap_migration.api.schemas import (
    ConnectionCreate,
    ConnectionResponse,
    ConnectionUpdate,
    TestResult,
)
from aap_migration.api.services.connection_service import ConnectionService
from aap_migration.api.services.token_crypto import TokenCryptoError

router = APIRouter(tags=["connections"])


def _mask_token(conn: Connection) -> ConnectionResponse:
    resp = ConnectionResponse.model_validate(conn)
    if conn.token:
        resp.token = "********"
    return resp


@router.post("/connections", response_model=ConnectionResponse, status_code=201)
def create_connection(data: ConnectionCreate, db: Session = Depends(get_db)) -> ConnectionResponse:
    svc = ConnectionService(db)
    try:
        conn = svc.create(data)
    except TokenCryptoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _mask_token(conn)


@router.get("/connections", response_model=list[ConnectionResponse])
def list_connections(db: Session = Depends(get_db)) -> list[ConnectionResponse]:
    svc = ConnectionService(db)
    return [_mask_token(c) for c in svc.list_all()]


@router.put("/connections/{connection_id}", response_model=ConnectionResponse)
def update_connection(
    connection_id: str, data: ConnectionUpdate, db: Session = Depends(get_db)
) -> ConnectionResponse:
    svc = ConnectionService(db)
    try:
        conn = svc.update(connection_id, data)
    except TokenCryptoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return _mask_token(conn)


@router.delete("/connections/{connection_id}", status_code=204)
def delete_connection(connection_id: str, db: Session = Depends(get_db)) -> None:
    svc = ConnectionService(db)
    if not svc.delete(connection_id):
        raise HTTPException(status_code=404, detail="Connection not found")


@router.post("/connections/{connection_id}/test", response_model=TestResult)
def test_connection(connection_id: str, db: Session = Depends(get_db)) -> TestResult:
    svc = ConnectionService(db)
    conn = svc.get(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        result = svc.test_connection(conn)
    except TokenCryptoError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from aap_migration.api.dependencies import get_db
from aap_migration.api.services.connection_service import ConnectionService

router = APIRouter(tags=["resources"])


@router.get("/connections/{connection_id}/resources")
def list_resource_types(connection_id: str, db: Session = Depends(get_db)) -> list[dict]:
    svc = ConnectionService(db)
    conn = svc.get(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    from aap_migration.api.services.platform_adapter import PlatformAdapter

    adapter = PlatformAdapter(conn)
    try:
        return adapter.discover_resource_types()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/connections/{connection_id}/resources/{resource_type}")
def list_resources(
    connection_id: str,
    resource_type: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str = Query(""),
    db: Session = Depends(get_db),
) -> dict:
    svc = ConnectionService(db)
    conn = svc.get(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    from aap_migration.api.services.platform_adapter import PlatformAdapter

    adapter = PlatformAdapter(conn)
    try:
        return adapter.list_resources(resource_type, page, page_size, search)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

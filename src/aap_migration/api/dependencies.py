from collections.abc import Generator
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from aap_migration.api.app import AppState

_app_state: "AppState | None" = None


def set_app_state(state: "AppState") -> None:
    global _app_state
    _app_state = state


def get_app_state() -> "AppState":
    if _app_state is None:
        raise RuntimeError("App state not initialized")
    return _app_state


def get_db() -> Generator[Session, None, None]:
    state = get_app_state()
    session = state.db_session_factory()
    try:
        yield session
    finally:
        session.close()

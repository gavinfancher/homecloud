from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from homecloud.config import settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def db_enabled() -> bool:
    """True when a DATABASE_URL is configured.

    With no URL the controller still serves the built-in image registry, so
    local dev and the test suite run without Postgres.
    """
    return bool(settings.database_url)


def get_engine() -> Engine:
    global _engine, _Session
    if _engine is None:
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is not set — the image database is unavailable")
        _engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session: commits on success, rolls back on error."""
    get_engine()
    assert _Session is not None
    session = _Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create tables and seed the built-in cloud image catalog.

    Safe to call on every startup: ``create_all`` is a no-op for existing
    tables and seeding skips catalog rows that are already present.
    """
    from homecloud.db.models import Base
    from homecloud.images.catalog import seed_catalog

    engine = get_engine()
    Base.metadata.create_all(engine)
    with session_scope() as session:
        seed_catalog(session)
    logger.info("Image database ready")

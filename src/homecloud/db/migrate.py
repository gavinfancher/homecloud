"""Apply the numbered SQL files in ``migrations/`` in order.

Each file runs once, in its own transaction, and is recorded in
``schema_migrations``. A Postgres advisory lock serializes concurrent
controllers starting at the same time. Migrations are forward-only: to change
the schema, add the next numbered file.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_LOCK_KEY = 0x686F6D65  # "home"


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def migrate(engine: Engine) -> list[str]:
    """Apply pending migrations; returns the versions applied."""
    applied_now: list[str] = []
    with engine.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _LOCK_KEY})
        conn.commit()
        try:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS schema_migrations ("
                    " version TEXT PRIMARY KEY,"
                    " applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
            )
            applied = set(conn.scalars(text("SELECT version FROM schema_migrations")))
            conn.commit()
            for path in migration_files():
                version = path.stem
                if version in applied:
                    continue
                # A parameterless execute on the raw psycopg cursor uses the
                # simple query protocol, which allows a file of many statements.
                with conn.connection.dbapi_connection.cursor() as cur:
                    cur.execute(path.read_text())
                conn.execute(
                    text("INSERT INTO schema_migrations (version) VALUES (:v)"), {"v": version}
                )
                conn.commit()
                applied_now.append(version)
                logger.info("Applied migration %s", version)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _LOCK_KEY})
            conn.commit()
    return applied_now

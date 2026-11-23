"""Run a service's Alembic migrations programmatically, serialised by an advisory lock.

Services migrate on start-up (``make connectors`` expects the outbox and its publication to exist
once a service has run). Several replicas starting together take a Postgres advisory lock so only
one runs the migration; the others wait and then find nothing to do.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

MIGRATION_LOCK_KEY = 7_201_100_001  # arbitrary, constant across services (each has its own DB)


def alembic_config(script_location: Path, url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(script_location))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def migrate(script_location: Path, url: str, revision: str = "head") -> None:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK_KEY})
            try:
                cfg = alembic_config(script_location, url)
                cfg.attributes["connection"] = conn
                command.upgrade(cfg, revision)
                conn.commit()
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK_KEY})
                conn.commit()
    finally:
        engine.dispose()

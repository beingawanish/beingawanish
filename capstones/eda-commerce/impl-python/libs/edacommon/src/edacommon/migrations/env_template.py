"""Shared body of every service's ``migrations/env.py``.

A service's env.py is two lines::

    from edacommon.migrations.env_template import run
    run()
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine


def run() -> None:
    config = context.config
    conn = config.attributes.get("connection")
    if conn is not None:
        context.configure(connection=conn, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    url = config.get_main_option("sqlalchemy.url")
    if context.is_offline_mode():
        context.configure(url=url, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(str(url))
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()

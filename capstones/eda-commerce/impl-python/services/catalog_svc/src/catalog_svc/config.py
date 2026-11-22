"""catalog-svc configuration (guide §7)."""

from __future__ import annotations

from edacommon.config import ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "catalog-svc"
    http_port: int = 8101
    db_name: str = "catalog_db"
    db_user: str = "catalog_svc"
    db_password: str = "catalog_svc"

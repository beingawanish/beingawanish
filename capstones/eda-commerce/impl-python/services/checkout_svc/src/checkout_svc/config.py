"""checkout-svc configuration (guide §7)."""

from __future__ import annotations

from edacommon.config import ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "checkout-svc"
    http_port: int = 8102
    db_name: str = "checkout_db"
    db_user: str = "checkout_svc"
    db_password: str = "checkout_svc"

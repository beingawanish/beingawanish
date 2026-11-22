"""inventory-svc configuration (guide §7)."""

from __future__ import annotations

from datetime import timedelta

from edacommon.config import Duration, ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "inventory-svc"
    http_port: int = 8105
    db_name: str = "inventory_db"
    db_user: str = "inventory_svc"
    db_password: str = "inventory_svc"
    reservation_ttl: Duration = timedelta(seconds=900)
    reservation_sweep_interval: Duration = timedelta(seconds=5)

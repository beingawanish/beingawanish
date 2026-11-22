"""notification-svc configuration (guide §7)."""

from __future__ import annotations

from edacommon.config import ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "notification-svc"
    http_port: int = 8108
    db_name: str = "notification_db"
    db_user: str = "notification_svc"
    db_password: str = "notification_svc"

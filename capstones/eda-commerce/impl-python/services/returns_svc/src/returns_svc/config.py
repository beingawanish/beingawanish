"""returns-svc configuration (guide §7)."""

from __future__ import annotations

from datetime import timedelta

from edacommon.config import ServiceSettings

from returns_svc.domain.saga import Policy


class Settings(ServiceSettings):
    service_name: str = "returns-svc"
    http_port: int = 8109
    db_name: str = "returns_db"
    db_user: str = "returns_svc"
    db_password: str = "returns_svc"
    return_window_days: int = 30
    return_auto_approve_limit_minor: int = 50000
    return_parcel_due_days: int = 14

    def policy(self) -> Policy:
        return Policy(
            auto_approve_limit_minor=self.return_auto_approve_limit_minor, parcel_due=timedelta(days=self.return_parcel_due_days)
        )

    @property
    def window(self) -> timedelta:
        return timedelta(days=self.return_window_days)

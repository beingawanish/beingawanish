"""order-svc configuration (guide §7). The projector process uses the same settings class with
SERVICE_NAME / CONSUMER_GROUP = order-history-projector."""

from __future__ import annotations

from datetime import timedelta

from edacommon.config import Duration, ServiceSettings

from order_svc.domain.saga import Timeouts


class Settings(ServiceSettings):
    service_name: str = "order-svc"
    http_port: int = 8103
    db_name: str = "order_db"
    db_user: str = "order_svc"
    db_password: str = "order_svc"
    saga_stock_timeout: Duration = timedelta(seconds=30)
    saga_payment_timeout: Duration = timedelta(seconds=180)
    saga_commit_timeout: Duration = timedelta(seconds=30)
    saga_fulfilment_ack_timeout: Duration = timedelta(seconds=600)
    saga_fulfilment_max_resends: int = 3
    saga_dispatch_timeout: Duration = timedelta(hours=24)
    saga_capture_timeout: Duration = timedelta(seconds=300)
    saga_compensation_timeout: Duration = timedelta(seconds=60)

    def timeouts(self) -> Timeouts:
        return Timeouts(
            stock=self.saga_stock_timeout,
            payment=self.saga_payment_timeout,
            commit=self.saga_commit_timeout,
            fulfilment_ack=self.saga_fulfilment_ack_timeout,
            fulfilment_max_resends=self.saga_fulfilment_max_resends,
            dispatch=self.saga_dispatch_timeout,
            capture=self.saga_capture_timeout,
            compensation=self.saga_compensation_timeout,
        )

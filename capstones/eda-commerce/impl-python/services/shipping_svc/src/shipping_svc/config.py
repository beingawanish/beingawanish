"""shipping-svc configuration (guide §7; fake knobs are admin.yaml FakeCarrierConfig in upper snake case)."""

from __future__ import annotations

from edacommon.config import ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "shipping-svc"
    http_port: int = 8107
    db_name: str = "shipping_db"
    db_user: str = "shipping_svc"
    db_password: str = "shipping_svc"
    carrier_webhook_secret: str = "dev-carrier-secret"
    carrier_webhook_url: str = "http://localhost:8107/webhooks/carrier"
    fake_carrier_duplicate_rate: float = 0.2
    fake_carrier_out_of_order_rate: float = 0.2
    fake_carrier_exception_rate: float = 0.02
    fake_carrier_step_delay_ms: int = 30000
    fake_carrier_booking_failure_rate: float = 0.02

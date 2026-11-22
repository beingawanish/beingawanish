"""payment-svc configuration (guide §7; fake knobs are admin.yaml FakePspConfig in upper snake case)."""

from __future__ import annotations

from edacommon.config import ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "payment-svc"
    http_port: int = 8104
    db_name: str = "payment_db"
    db_user: str = "payment_svc"
    db_password: str = "payment_svc"
    psp_webhook_secret: str = "dev-psp-secret"
    psp_webhook_url: str = "http://localhost:8104/webhooks/psp"
    fake_psp_decline_rate: float = 0.05
    fake_psp_timeout_rate: float = 0.02
    fake_psp_duplicate_webhook_rate: float = 0.1
    fake_psp_webhook_delay_ms: int = 300
    fake_psp_slow_webhook_ms: int = 90000
    fake_psp_api_latency_ms: int = 80

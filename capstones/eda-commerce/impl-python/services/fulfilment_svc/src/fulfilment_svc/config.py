"""fulfilment-svc configuration (guide §7; fake knobs are admin.yaml FakeWmsConfig in upper snake case)."""

from __future__ import annotations

from edacommon.config import ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "fulfilment-svc"
    http_port: int = 8106
    db_name: str = "fulfilment_db"
    db_user: str = "fulfilment_svc"
    db_password: str = "fulfilment_svc"
    fake_wms_drop_request_rate: float = 0.1
    fake_wms_accept_delay_ms: int = 2000
    fake_wms_pick_delay_ms: int = 20000
    fake_wms_pack_delay_ms: int = 20000
    fake_wms_fail_rate: float = 0.02
    fake_wms_manifest_lines: int = 2000
    fake_wms_inspection_damaged_rate: float = 0.2

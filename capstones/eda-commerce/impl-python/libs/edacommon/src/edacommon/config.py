"""Configuration from environment variables with the exact names of guide §7 (both builds).

Each service subclasses :class:`ServiceSettings`, overrides the defaults that differ (service name,
port, database) and adds its own variables (``SAGA_*``, ``RESERVATION_*``, ``FAKE_PSP_*``...).
Field ``foo_bar`` reads ``FOO_BAR``. Nothing else in a service reads ``os.environ``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from edacommon.durations import parse_duration

Duration = Annotated[timedelta, BeforeValidator(parse_duration)]


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False, extra="ignore", frozen=True)

    # identity
    service_name: str = "unnamed-svc"
    environment: str = "local"
    http_port: int = 8080
    consumer_group: str | None = None  # defaults to service_name

    # kafka (guide §7.1 holds the client settings that are not configurable)
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_security_protocol: Literal["PLAINTEXT", "SSL"] = "PLAINTEXT"
    kafka_ssl_ca_location: str | None = None
    kafka_ssl_cert_location: str | None = None
    kafka_ssl_key_location: str | None = None
    kafka_group_instance_id: str | None = Field(default=None, alias="POD_NAME")  # static membership in k8s
    schema_registry_url: str = "http://localhost:8081"

    # database
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "app_db"
    db_user: str = "app_svc"
    db_password: str = "app_svc"
    db_pool_size: int = 10

    # outbox relay (ADR-0003)
    outbox_relay: Literal["debezium", "polling"] = "debezium"
    outbox_poll_interval: Duration = timedelta(milliseconds=200)

    # object storage (ADR-0009)
    s3_endpoint: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_access_key: str = "claimcheck"
    s3_secret_key: str = "claimcheck-secret"

    # observability: the OTel SDK reads OTEL_* itself; these are for the resource and exporter wiring
    otel_service_name: str | None = None
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_exporter_otlp_protocol: Literal["grpc", "http/protobuf"] = "grpc"
    otel_resource_attributes: str = "service.namespace=edacommerce,eda.impl=python"
    otel_sdk_disabled: bool = False

    # auth (ADR-0013)
    auth_mode: Literal["none", "oidc"] = "none"
    oidc_issuer_url: str = "http://localhost:8180/realms/edacommerce"
    oidc_audience: str = "edacommerce-api"

    # logging (guide §6.4)
    log_format: Literal["json", "console"] = "json"
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _refuse_unsafe_auth(self) -> ServiceSettings:
        # ADR-0013: AUTH_MODE=none exists for local development only.
        if self.auth_mode == "none" and self.environment != "local":
            raise ValueError("AUTH_MODE=none is refused unless ENVIRONMENT=local (ADR-0013)")
        return self

    @property
    def group(self) -> str:
        return self.consumer_group or self.service_name

    @property
    def db_url(self) -> str:
        return f"postgresql+psycopg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    def resource_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        for part in self.otel_resource_attributes.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                attrs[k.strip()] = v.strip()
        attrs["service.name"] = self.otel_service_name or self.service_name
        attrs.setdefault("eda.impl", "python")
        return attrs

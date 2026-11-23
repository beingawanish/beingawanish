-- notification-svc private tables (architecture §3). V1 is contracts/sql/common-tables.sql.
-- contact holds personal data learnt from OrderPlaced, under this service's own retention
-- (ADR-0013): rows are deleted after retain_until. Nothing here is ever logged.
CREATE TABLE contact (
    order_id        text        PRIMARY KEY,
    customer_id     text        NOT NULL,
    email           text        NOT NULL,
    recipient_name  text        NOT NULL,
    retain_until    timestamptz NOT NULL,
    created_at      timestamptz NOT NULL
);
CREATE INDEX contact_retention_idx ON contact (retain_until);

-- One row per message sent. dedupe_key (template + business id) makes "one email per triggering
-- fact" hold even when a producer re-emits the fact with a new eventId.
CREATE TABLE notification (
    notification_id   text        PRIMARY KEY,
    dedupe_key        text        NOT NULL UNIQUE,
    source_event_id   text        NOT NULL,
    template          text        NOT NULL,
    order_id          text,
    customer_id       text        NOT NULL,
    channel           text        NOT NULL,
    attachment_count  int         NOT NULL DEFAULT 0,
    sent_at           timestamptz NOT NULL
);
CREATE INDEX notification_order_idx ON notification (order_id);

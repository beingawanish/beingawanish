#!/bin/sh
# One-shot: create the claim-check buckets and their lifecycle rules (ADR-009).
# Runs in the minio/mc image after MinIO is healthy.
set -eu
mc alias set local http://minio:9000 "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}"

# bucket            expiry   why
# invoices          none     legal retention (years); production uses object lock + versioning
# packing-manifests 90 days  covers the 30-day return window, inspection disputes and audits
# shipping-labels   30 days  a label is useless once the parcel is delivered
# notification-tmp  2 days   rendered email attachments, only needed until the send succeeds
for b in invoices packing-manifests shipping-labels notification-tmp; do
  mc mb --ignore-existing "local/${b}"
done
mc version enable local/invoices
mc ilm rule add --expire-days 90 local/packing-manifests || true
mc ilm rule add --expire-days 30 local/shipping-labels || true
mc ilm rule add --expire-days 2 local/notification-tmp || true

# Service account used by every service locally. Production: one key pair per service,
# with a bucket policy that lets only the producing service write to its bucket.
mc admin user add local claimcheck claimcheck-secret || true
mc admin policy attach local readwrite --user claimcheck || true
echo "minio buckets ready"

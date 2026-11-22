#!/usr/bin/env python3
"""Register every bundled schema under its TopicRecordNameStrategy subject.

For each message on each topic in contracts/topics.yaml the subject is
    <topic>-<record full name>          e.g. order.events.v1-com.edacommerce.order.OrderPlaced
The script sets the subject's compatibility to FULL_TRANSITIVE, checks compatibility of the new
version against what is registered, and only then registers it. Services run with
auto.register.schemas=false, so this script (or the CI job that calls it) is the only writer.

Standard library only, so it runs anywhere Python 3.10+ is installed.

    python3 infra/scripts/register-schemas.py [--url http://localhost:8081] [--dry-run]
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = ROOT / "contracts" / "topics.yaml"
BUNDLED = ROOT / "contracts" / "avro-bundled"
CT = "application/vnd.schemaregistry.v1+json"


def topics_and_messages():
    """Tiny parser for the parts of topics.yaml we need, to avoid a PyYAML dependency."""
    topic, in_messages, out = None, False, []
    for raw in CATALOGUE.read_text().splitlines():
        line = raw.split("#", 1)[0].rstrip()
        s = line.strip()
        if s.startswith("- name: "):
            topic, in_messages = s[len("- name: "):], False
        elif s.startswith("messages:"):
            rest = s[len("messages:"):].strip()
            if rest.startswith("["):
                for m in rest.strip("[]").split(","):
                    out.append((topic, m.strip()))
                in_messages = False
            else:
                in_messages = True
        elif in_messages and s.startswith("- "):
            out.append((topic, s[2:].strip()))
        elif in_messages and s and not s.startswith("- "):
            in_messages = False
    return out


def call(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": CT, "Accept": CT})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8081")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    failures = 0
    for topic, rel in topics_and_messages():
        ctx, _kind, name = rel.split("/")
        full = f"com.edacommerce.{ctx}.{name}"
        subject = f"{topic}-{full}"
        schema = (BUNDLED / f"{full}.avsc").read_text()
        if a.dry_run:
            print(f"would register {subject}")
            continue
        call("PUT", f"{a.url}/config/{subject}", {"compatibility": "FULL_TRANSITIVE"})
        payload = {"schemaType": "AVRO", "schema": schema}
        st, body = call("POST", f"{a.url}/compatibility/subjects/{subject}/versions/latest?verbose=true&normalize=true", payload)
        if st == 200 and not body.get("is_compatible", False):
            print(f"INCOMPATIBLE {subject}: {body.get('messages')}", file=sys.stderr)
            failures += 1
            continue
        st, body = call("POST", f"{a.url}/subjects/{subject}/versions?normalize=true", payload)
        if st == 200:
            print(f"registered {subject} id={body.get('id')}")
        else:
            print(f"FAILED {subject}: HTTP {st} {body}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

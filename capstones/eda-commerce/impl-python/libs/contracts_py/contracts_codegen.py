"""Code generator for contracts_py (guide §2: generated code is never committed).

Reads the self-contained schemas in ``contracts/avro-bundled/`` and the catalogue in
``contracts/topics.yaml`` and writes ``src/contracts_py/_generated/``:

* ``schemas/<full.name>.avsc``  the bundled schemas, byte-for-byte, as package data
* ``records.py``                one frozen dataclass per Avro record and one StrEnum per Avro enum,
                                with ``to_avro()`` / ``from_avro()`` converting to and from the dict
                                shape fastavro and confluent-kafka use (camelCase keys)
* ``topics.py``                 topic names, keys, partitions, message -> topic map, consumer groups
                                and the retry policy

It runs in three ways, all producing identical output:

* automatically, as a hatchling build hook, whenever uv builds or (re)installs ``contracts-py``;
* by hand: ``uv run python libs/contracts_py/contracts_codegen.py``;
* with ``--check`` in CI, which fails if the generated tree is stale.

The generator uses only the standard library plus PyYAML so it can run inside an isolated build env.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import keyword
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_CONTRACTS = HERE.parent.parent.parent / "contracts"
OUT = HERE / "src" / "contracts_py" / "_generated"

PRIMITIVES = {
    "string": "str",
    "int": "int",
    "long": "int",
    "boolean": "bool",
    "double": "float",
    "float": "float",
    "bytes": "bytes",
}


def contracts_dir() -> Path:
    return Path(os.environ.get("EDA_CONTRACTS_DIR", DEFAULT_CONTRACTS)).resolve()


def snake(name: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name).lower()
    return f"{s}_" if keyword.iskeyword(s) else s


@dataclass
class EnumDef:
    full: str
    name: str
    symbols: list[str]
    default: str | None
    doc: str | None


@dataclass
class FieldDef:
    avro: str
    py: str
    type_expr: str        # Python annotation
    to_expr: str          # expression template with {v}
    from_expr: str        # expression template with {v}
    default: str | None   # Python default literal or None when required
    pii: bool
    doc: str | None


@dataclass
class RecordDef:
    full: str
    name: str
    doc: str | None
    fields: list[FieldDef] = field(default_factory=list)
    top_level: bool = False


class Collector:
    """Walks bundled schemas and collects each named type exactly once."""

    def __init__(self) -> None:
        self.records: dict[str, RecordDef] = {}
        self.enums: dict[str, EnumDef] = {}
        self.order: list[str] = []
        self.simple_names: dict[str, str] = {}

    def class_name(self, full: str) -> str:
        simple = full.rsplit(".", 1)[-1]
        owner = self.simple_names.setdefault(simple, full)
        if owner != full:
            # Two different full names share a simple name: qualify with the context.
            ctx = full.split(".")[-2]
            return ctx.capitalize() + simple
        return simple

    def walk(self, t: Any, ns: str) -> tuple[str, str, str]:
        """Return (annotation, to_avro template, from_avro template) for an Avro type."""
        if isinstance(t, list):
            non_null = [x for x in t if x != "null"]
            if len(non_null) != 1 or len(t) != 2 or t[0] != "null":
                raise ValueError(f"only ['null', T] unions are supported, got {t}")
            ann, to_e, from_e = self.walk(non_null[0], ns)
            return (
                f"{ann} | None",
                f"(None if {{v}} is None else {to_e})",
                f"(None if {{v}} is None else {from_e})",
            )
        if isinstance(t, str):
            if t in PRIMITIVES:
                return PRIMITIVES[t], "{v}", "{v}"
            full = t if "." in t else f"{ns}.{t}"
            return self.ref(full)
        typ = t["type"]
        if typ in ("record", "error"):
            full = self.define_record(t, ns)
            return self.ref(full)
        if typ == "enum":
            full = self.define_enum(t, ns)
            return self.ref(full)
        if typ == "array":
            ann, to_e, from_e = self.walk(t["items"], ns)
            return (
                f"tuple[{ann}, ...]",
                f"[{to_e.format(v='x')} for x in {{v}}]",
                f"tuple({from_e.format(v='x')} for x in {{v}})",
            )
        if typ == "map":
            ann, to_e, from_e = self.walk(t["values"], ns)
            return (
                f"dict[str, {ann}]",
                f"{{{{k: {to_e.format(v='x')} for k, x in {{v}}.items()}}}}",
                f"{{{{k: {from_e.format(v='x')} for k, x in {{v}}.items()}}}}",
            )
        if t.get("logicalType") == "timestamp-millis" and typ == "long":
            return "datetime", "{v}", "_ts({v})"
        if typ in PRIMITIVES:
            return PRIMITIVES[typ], "{v}", "{v}"
        raise ValueError(f"unsupported Avro type {t}")

    def ref(self, full: str) -> tuple[str, str, str]:
        cls = self.class_name(full)
        if full in self.enums:
            return cls, "{v}.value", f"{cls}.parse({{v}})"
        return cls, "{v}.to_avro()", f"{cls}.from_avro({{v}})"

    def define_enum(self, t: dict[str, Any], ns: str) -> str:
        full = f"{t.get('namespace', ns)}.{t['name']}" if "." not in t["name"] else t["name"]
        if full not in self.enums:
            self.enums[full] = EnumDef(full, self.class_name(full), list(t["symbols"]), t.get("default"),
                                       t.get("doc"))
            self.order.append(full)
        return full

    def define_record(self, t: dict[str, Any], ns: str) -> str:
        own_ns = t.get("namespace", ns)
        full = t["name"] if "." in t["name"] else f"{own_ns}.{t['name']}"
        if full in self.records:
            return full
        rec = RecordDef(full, self.class_name(full), t.get("doc"))
        self.records[full] = rec  # reserve before walking fields (no recursion in our contracts)
        for f in t["fields"]:
            ann, to_e, from_e = self.walk(f["type"], own_ns)
            default = None
            if "default" in f:
                default = self.default_literal(f["default"], f["type"], own_ns)
            rec.fields.append(FieldDef(
                avro=f["name"], py=snake(f["name"]), type_expr=ann,
                to_expr=to_e.format(v=f"self.{snake(f['name'])}"),
                from_expr=from_e.format(v=f"d[{f['name']!r}]"),
                default=default, pii=bool(f.get("pii")), doc=f.get("doc"),
            ))
        self.order.append(full)
        return full

    def default_literal(self, value: Any, t: Any, ns: str) -> str:
        if value is None:
            return "None"
        if isinstance(t, dict) and t.get("type") == "array":
            if value != []:
                raise ValueError("only empty array defaults are supported")
            return "()"
        if isinstance(t, dict) and t.get("type") == "map":
            if value != {}:
                raise ValueError("only empty map defaults are supported")
            return "field(default_factory=dict)"
        if isinstance(t, str) and (t in self.enums or f"{ns}.{t}" in self.enums):
            full = t if t in self.enums else f"{ns}.{t}"
            return f"{self.class_name(full)}.{value}"
        if isinstance(value, bool):
            return repr(value)
        if isinstance(value, (int, float, str)):
            return repr(value)
        raise ValueError(f"unsupported default {value!r}")


HEADER = '''# GENERATED by libs/contracts_py/contracts_codegen.py from contracts/avro-bundled. DO NOT EDIT.
# Source digest: {digest}
'''


def render_records(col: Collector, digest: str, top_levels: dict[str, dict[str, Any]]) -> str:
    out = [HEADER.format(digest=digest), '''"""Typed views of every Avro record and enum in the contracts.

Records are immutable dataclasses with snake_case attributes. ``to_avro()`` returns the camelCase dict
that fastavro and confluent-kafka serialise; ``from_avro()`` accepts that dict (timestamps may be
``datetime`` or epoch milliseconds). Enums decode unknown symbols to ``UNKNOWN`` (guide §5 rule 9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar


def _ts(v: Any) -> datetime:
    if isinstance(v, datetime):
        if v.tzinfo is None:
            raise ValueError("naive datetime in an Avro timestamp-millis field")
        return v.astimezone(UTC)
    return datetime.fromtimestamp(int(v) / 1000, tz=UTC)

''']
    for full in col.order:
        if full in col.enums:
            e = col.enums[full]
            out.append(f"\nclass {e.name}(StrEnum):\n")
            out.append(f'    """{(e.doc or e.full).strip()}"""\n\n')
            for s in e.symbols:
                out.append(f"    {s} = {s!r}\n")
            out.append(f"\n    AVRO_NAME: ClassVar[str] = {e.full!r}\n")
            out.append(f"""
    @classmethod
    def parse(cls, value: str) -> {e.name}:
        \"\"\"Decode a symbol; anything unknown becomes the reader default ({e.default}).\"\"\"
        try:
            return cls(value)
        except ValueError:
            return cls.{e.default or e.symbols[-1]}

""")
            continue
        r = col.records[full]
        required = [f for f in r.fields if f.default is None]
        optional = [f for f in r.fields if f.default is not None]
        out.append("\n@dataclass(frozen=True, slots=True, kw_only=True)\n")
        out.append(f"class {r.name}:\n")
        out.append(f'    """{(r.doc or r.full).strip()}"""\n\n')
        out.append(f"    AVRO_NAME: ClassVar[str] = {r.full!r}\n")
        if full in top_levels:
            meta = top_levels[full]
            out.append(f"    TOPIC: ClassVar[str] = {meta['topic']!r}\n")
            out.append(f"    KEY_FIELD: ClassVar[str] = {meta['key']!r}\n")
            out.append(f"    AGGREGATE_TYPE: ClassVar[str] = {meta['aggregate']!r}\n")
            out.append(f"    KIND: ClassVar[str] = {meta['kind']!r}\n")
        pii = [f.avro for f in r.fields if f.pii]
        out.append(f"    PII_FIELDS: ClassVar[frozenset[str]] = frozenset({sorted(pii)!r})\n\n")
        for f in required + optional:
            line = f"    {f.py}: {f.type_expr}"
            if f.default is not None:
                line += f" = {f.default}"
            out.append(line + "\n")
        out.append("\n    def to_avro(self) -> dict[str, Any]:\n        return {\n")
        for f in r.fields:
            out.append(f"            {f.avro!r}: {f.to_expr},\n")
        out.append("        }\n")
        out.append(f"\n    @classmethod\n    def from_avro(cls, d: dict[str, Any]) -> {r.name}:\n")
        out.append("        return cls(\n")
        for f in r.fields:
            if f.default is not None:
                getter = f"d.get({f.avro!r})"
                expr = f.from_expr.replace(f"d[{f.avro!r}]", getter)
                if f.default == "()":
                    expr = f.from_expr.replace(f"d[{f.avro!r}]", f"d.get({f.avro!r}, ())")
                elif f.default == "field(default_factory=dict)":
                    expr = f.from_expr.replace(f"d[{f.avro!r}]", f"d.get({f.avro!r}, {{}})")
                elif f.default != "None":
                    expr = (f"({f.default} if {f.avro!r} not in d else "
                            f"{f.from_expr})")
                out.append(f"            {f.py}={expr},\n")
            else:
                out.append(f"            {f.py}={f.from_expr},\n")
        out.append("        )\n\n")
    names = sorted({col.records[f].name for f in col.records} | {col.enums[f].name for f in col.enums})
    out.append("\nMESSAGE_TYPES: dict[str, type[Any]] = {\n")
    for full in sorted(top_levels):
        out.append(f"    {full!r}: {col.records[full].name},\n")
    out.append("}\n\n__all__ = [\n")
    for n in [*names, "MESSAGE_TYPES"]:
        out.append(f"    {n!r},\n")
    out.append("]\n")
    return "".join(out)


def parse_duration_s(v: str) -> int:
    m = re.fullmatch(r"(\d+)([smhd])", v)
    if not m:
        raise ValueError(v)
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def render_topics(cat: dict[str, Any], digest: str) -> str:
    out = [HEADER.format(digest=digest), '''"""Topic catalogue from contracts/topics.yaml (ADR-0005, ADR-0007)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TopicSpec:
    name: str
    kind: str
    key: str
    partitions: int
    cleanup_policy: str
    producers: tuple[str, ...]
    consumers: tuple[str, ...]
    messages: tuple[str, ...]


''']
    consts: list[str] = []
    specs: list[str] = []
    msg_map: list[str] = []
    for t in cat["topics"]:
        const = re.sub(r"[^A-Z0-9]+", "_", t["name"].rsplit(".v", 1)[0].upper())
        consts.append(f"{const} = {t['name']!r}\n")
        fulls = []
        for rel in t["messages"]:
            ctx, kind, name = rel.split("/")
            full = f"com.edacommerce.{ctx}.{name}"
            fulls.append(full)
            msg_map.append(f"    {full!r}: {t['name']!r},\n")
        specs.append(
            f"    TopicSpec({t['name']!r}, {t['kind']!r}, {t['key']!r}, {t['partitions']}, "
            f"{t['cleanupPolicy']!r}, {tuple(t['producers'])!r}, {tuple(t['consumers'])!r}, "
            f"{tuple(fulls)!r}),\n"
        )
    out.extend(consts)
    out.append("\nTOPICS: tuple[TopicSpec, ...] = (\n")
    out.extend(specs)
    out.append(")\n\nTOPIC_BY_NAME: dict[str, TopicSpec] = {t.name: t for t in TOPICS}\n")
    out.append("\nMESSAGE_TOPIC: dict[str, str] = {\n")
    out.extend(msg_map)
    out.append("}\n")
    rp = cat["retryPolicy"]
    delays = [d for d in rp["delays"]]
    out.append(f"\nCONSUMER_GROUPS: tuple[str, ...] = {tuple(cat['consumerGroups'])!r}\n")
    out.append(f"RETRY_DELAYS: tuple[str, ...] = {tuple(delays)!r}\n")
    out.append(f"RETRY_DELAY_SECONDS: tuple[int, ...] = {tuple(parse_duration_s(d) for d in delays)!r}\n")
    out.append(f"RETRY_PARTITIONS: int = {rp['retryPartitions']}\nDLQ_PARTITIONS: int = {rp['dlqPartitions']}\n")
    out.append('''

def retry_topics(group: str) -> tuple[str, ...]:
    """<group>.retry.10s, <group>.retry.1m, <group>.retry.10m (ADR-0007)."""
    return tuple(f"{group}.retry.{d}" for d in RETRY_DELAYS)


def dlq_topic(group: str) -> str:
    return f"{group}.dlq"
''')
    return "".join(out)


INIT = '''# GENERATED by libs/contracts_py/contracts_codegen.py. DO NOT EDIT.
"""Generated package: bundled Avro schemas, typed records and the topic catalogue."""
'''


def source_digest(cdir: Path) -> str:
    h = hashlib.sha256()
    for p in sorted((cdir / "avro-bundled").glob("*.avsc")) + [cdir / "topics.yaml"]:
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def generate(cdir: Path) -> dict[Path, bytes]:
    import yaml  # build-time dependency only

    cat = yaml.safe_load((cdir / "topics.yaml").read_text())
    top_levels: dict[str, dict[str, Any]] = {}
    for t in cat["topics"]:
        for rel in t["messages"]:
            ctx, _kind, name = rel.split("/")
            top_levels[f"com.edacommerce.{ctx}.{name}"] = {
                "topic": t["name"], "key": t["key"], "aggregate": t["aggregate"], "kind": t["kind"],
            }
    digest = source_digest(cdir)
    col = Collector()
    files: dict[Path, bytes] = {}
    bundled = sorted((cdir / "avro-bundled").glob("*.avsc"))
    # Common types first so they keep their simple names.
    bundled.sort(key=lambda p: (".common." not in p.name, p.name))
    for p in bundled:
        raw = p.read_bytes()
        files[OUT / "schemas" / p.name] = raw
        schema = json.loads(raw)
        full = col.define_record(schema, schema.get("namespace", ""))
        if full in top_levels:
            col.records[full].top_level = True
    missing = set(top_levels) - set(col.records)
    if missing:
        raise SystemExit(f"topics.yaml names messages without bundled schemas: {sorted(missing)}")
    files[OUT / "__init__.py"] = INIT.encode()
    files[OUT / "schemas" / "__init__.py"] = b""
    files[OUT / "records.py"] = render_records(col, digest, top_levels).encode()
    files[OUT / "topics.py"] = render_topics(cat, digest).encode()
    return files


def write(files: dict[Path, bytes]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = set(files)
    for old in OUT.rglob("*"):
        if old.is_file() and old not in wanted and "__pycache__" not in old.parts:
            old.unlink()
    for path, data in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the generated tree is stale")
    args = ap.parse_args(argv)
    files = generate(contracts_dir())
    if args.check:
        stale = [str(p) for p, d in files.items() if not p.exists() or p.read_bytes() != d]
        if stale:
            print("stale generated files:\n  " + "\n  ".join(stale), file=sys.stderr)
            return 1
        print("contracts_py is up to date")
        return 0
    write(files)
    print(f"generated {len(files)} files into {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

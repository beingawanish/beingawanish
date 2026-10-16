"""Code-level fixes to the MCP guide, found by running every code block against mcp 2.3.0.

guides/guide.py applies these on load(), right after prose_fixes.py.

CODE edits are (block_id, old_lines, new_lines) on the block's *plain* text (tags stripped,
entities unescaped). old_lines must match a run of whole lines exactly once in that block.
Lines shared by old and new at the start/end keep their original highlighted HTML; changed
lines become plain escaped text. Line ids/hrefs are renumbered 1..n inside each edited block.

PROSE edits are (old, new) on whitespace-normalised inner HTML of <p>, <li> or <td> blocks,
and RAW edits are exact substrings of the document; every old string must match exactly once.
"""
import html
import re

CODE = [
    # Module 1: pass an httpx2 client, as Module 4 says (the parameter is typed httpx2.AsyncClient).
    ("cb16",
     'from mcp.client.streamable_http import streamable_http_client  # 2.x; 1.x: streamablehttp_client',
     'import httpx2  # the SDK\'s HTTP layer; pass an httpx2 client, not httpx\n'
     'from mcp.client.streamable_http import streamable_http_client  # 2.x; 1.x: streamablehttp_client'),
    ("cb16",
     '    http_client=httpx.AsyncClient(headers={"Authorization": "Bearer ..."}),',
     '    http_client=httpx2.AsyncClient(headers={"Authorization": "Bearer ..."}),'),

    # D3: the schema the SDK really publishes (amount, reason, currency still omitted).
    ("cb35",
     '{\n'
     '  "properties": {\n'
     '    "order_id": {\n'
     '      "description": "Order identifier, e.g. ORD-004213.",\n'
     '      "pattern": "^ORD-\\\\d{6}$",\n'
     '      "type": "string"\n'
     '    },\n'
     '    "idempotency_key": {\n'
     '      "description": "Unique key for this refund. Reuse the SAME key when retrying — a new key would create a second refund. Generated automatically when omitted.",\n'
     '      "type": ["string", "null"]\n'
     '    }\n'
     '  },\n'
     '  "required": ["order_id", "amount", "reason"],\n'
     '  "type": "object"\n'
     '}',
     '{\n'
     '  "properties": {\n'
     '    "order_id": {\n'
     '      "description": "Order identifier, e.g. ORD-004213.",\n'
     '      "pattern": "^ORD-\\\\d{6}$",\n'
     '      "title": "Order Id",\n'
     '      "type": "string"\n'
     '    },\n'
     '    "idempotency_key": {\n'
     '      "anyOf": [\n'
     '        {"maxLength": 64, "minLength": 8, "type": "string"},\n'
     '        {"type": "null"}\n'
     '      ],\n'
     '      "default": null,\n'
     '      "description": "Unique key for this refund. Reuse the SAME key when retrying — a new key would create a second refund. Generated automatically when omitted.",\n'
     '      "title": "Idempotency Key"\n'
     '    }\n'
     '  },\n'
     '  "required": ["order_id", "amount", "reason"],\n'
     '  "type": "object",\n'
     '  "title": "issue_refundArguments"\n'
     '}'),

    # Minor: a model-level (cross-field) error has an empty loc; don't render ": Value error".
    ("cb37",
     "    parts = [f\"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}\" for e in exc.errors()]",
     "    parts = [\n"
     "        f\"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}\" if e[\"loc\"] else e[\"msg\"]\n"
     "        for e in exc.errors()\n"
     "    ]"),

    # D2: the wire method is notifications/tools/list_changed.
    ("cb41",
     "2. ``list_tools()`` results are cached with a TTL. ``tools/listChanged``",
     "2. ``list_tools()`` results are cached with a TTL. ``tools/list_changed``"),
    ("cb42",
     "    wired to ``message_handler`` so ``tools/listChanged`` invalidates it.",
     "    wired to ``message_handler`` so ``tools/list_changed`` invalidates it."),
    ("cb43",
     "    ``notifications/tools/listChanged`` handler below can invalidate eagerly.",
     "    ``notifications/tools/list_changed`` handler below can invalidate eagerly."),
    ("cb43",
     '    """ClientSession message_handler: invalidate the tool cache on listChanged.',
     '    """ClientSession message_handler: invalidate the tool cache on list_changed.'),
    ("cb43",
     "    that gains or loses tools notifies ``notifications/tools/listChanged``;",
     "    that gains or loses tools notifies ``notifications/tools/list_changed``;"),
    ("cb43",
     '    if getattr(root, "method", None) == "notifications/tools/listChanged":',
     '    if getattr(root, "method", None) == "notifications/tools/list_changed":'),

    # D1: 2.x models expose snake_case attributes; isError is only the wire alias.
    ("cb46",
     '        print("isError:", result.isError)',
     '        print("isError:", result.is_error)'),

    # D2 (comments naming the wire method).
    ("cb49",
     '        """Re-aggregate. Called at startup and on tools/listChanged."""',
     '        """Re-aggregate. Called at startup and on tools/list_changed."""'),
    ("cb58",
     "        # tools/listChanged) and drive the mounted MCP app's lifespan, which",
     "        # tools/list_changed) and drive the mounted MCP app's lifespan, which"),
    ("cb59",
     "        # refresh endpoint reports new/removed tools (tools/listChanged).",
     "        # refresh endpoint reports new/removed tools (tools/list_changed)."),
    ("cb61",
     "# Control plane: registry refresh picks up tools/listChanged",
     "# Control plane: registry refresh picks up tools/list_changed"),

    # Minor: the Redis sketch uses dataclasses and skips one Protocol method.
    ("cb55",
     '#     challenges expire without a reaper process."""',
     '#     challenges expire without a reaper process."""\n'
     '#     # Needs `import dataclasses`; find_pending() (a SCAN over\n'
     '#     # mcp:approval:*) is left out of this sketch.'),

    # D4: the SDK's replay callback takes an EventMessage, not a dict; skip priming events.
    ("cb65",
     "from mcp.server.streamable_http import EventCallback, EventId, EventStore, StreamId\n"
     "from mcp.types import JSONRPCMessage",
     "from mcp.server.streamable_http import EventCallback, EventId, EventMessage, EventStore, StreamId\n"
     "from mcp.types import JSONRPCMessage, jsonrpc_message_adapter"),
    ("cb65",
     '                            "payload": message.model_dump() if message else None})',
     '                            "payload": message.model_dump(mode="json", by_alias=True, exclude_unset=True)\n'
     '                            if message else None})'),
    ("cb65",
     '            frame = json.loads(raw)\n'
     '            await send_callback(frame["payload"])',
     '            frame = json.loads(raw)\n'
     '            if frame["payload"] is None:\n'
     '                continue  # priming event: nothing to resend\n'
     '            message = jsonrpc_message_adapter.validate_python(frame["payload"])\n'
     '            await send_callback(EventMessage(message, frame["id"]))'),

    # D6: a parser directive only works on line 1; build the venv at the path it runs from
    # (console-script shebangs are absolute, so a venv moved from /build breaks `uvicorn`).
    ("cb67",
     "# Dockerfile — billing-mcp",
     "# syntax=docker/dockerfile:1\n# Dockerfile — billing-mcp"),
    ("cb67",
     "# > Run docker build on a Docker-equipped machine — not in a sandbox.\n"
     "# syntax=docker/dockerfile:1",
     "# > Run docker build on a Docker-equipped machine — not in a sandbox."),
    ("cb67",
     "WORKDIR /build",
     "# Same path as the runtime stage: venv console scripts hard-code it.\n"
     "WORKDIR /app"),
    ("cb67",
     "COPY pyproject.toml uv.lock ./",
     "# uv.lock: run `uv lock` next to pyproject.toml once, and commit it.\n"
     "COPY pyproject.toml uv.lock ./"),
    ("cb67",
     "# /build/.venv now holds byte-compiled third-party packages. Nothing else",
     "# /app/.venv now holds byte-compiled third-party packages. Nothing else"),
    ("cb67",
     "COPY --from=builder --chown=appuser:appuser /build/.venv /app/.venv",
     "COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv"),

    # D5: default host checking only accepts localhost Host headers -> 421 behind the Ingress.
    ("cb69",
     "from mcp.server.mcpserver import MCPServer  # 2.x name; 1.x called this FastMCP",
     "from mcp.server.mcpserver import MCPServer  # 2.x name; 1.x called this FastMCP\n"
     "from mcp.server.transport_security import TransportSecuritySettings"),
    ("cb69",
     "    max_sessions=10000,\n)",
     "    max_sessions=10000,\n"
     "    # The default only accepts localhost Host headers (421 behind an Ingress).\n"
     "    transport_security=TransportSecuritySettings(allowed_hosts=[\n"
     "        \"mcp.example.com\", \"billing-mcp\", \"billing-mcp:*\", \"localhost:*\", \"127.0.0.1:*\"]),\n"
     ")"),

    # D8: compose peers call the MCP servers by service name, which the default rejects (421).
    ("cb84",
     "from mcp.server.mcpserver.exceptions import ToolError",
     "from mcp.server.mcpserver.exceptions import ToolError\n"
     "from mcp.server.transport_security import TransportSecuritySettings"),
    ("cb84",
     "    app = server.streamable_http_app()",
     "    # The gateway calls us as commerce-mcp:8101; the default accepts only localhost.\n"
     "    app = server.streamable_http_app(transport_security=TransportSecuritySettings(\n"
     "        allowed_hosts=[\"commerce-mcp:*\", \"localhost:*\", \"127.0.0.1:*\"]))"),
    ("cb85",
     "from mcp.server.mcpserver.exceptions import ToolError",
     "from mcp.server.mcpserver.exceptions import ToolError\n"
     "from mcp.server.transport_security import TransportSecuritySettings"),
    ("cb85",
     "    app = server.streamable_http_app()",
     "    # The gateway calls us as finance-mcp:8102; the default accepts only localhost.\n"
     "    app = server.streamable_http_app(transport_security=TransportSecuritySettings(\n"
     "        allowed_hosts=[\"finance-mcp:*\", \"localhost:*\", \"127.0.0.1:*\"]))"),

    # D9: a rejected request must not count against the window (same semantics as in-memory).
    ("cb88",
     "        _, _, count, _ = await pipe.execute()\n"
     "        return count <= self.max_requests",
     "        _, _, count, _ = await pipe.execute()\n"
     "        if count > self.max_requests:\n"
     "            undo = self.redis.pipeline()\n"
     "            undo.zremrangebyscore(key, now, now)  # drop this hit: rejected calls use no budget\n"
     "            await undo.execute()\n"
     "            return False\n"
     "        return True"),

    # D7: `pip install .` cannot build a wheel from pyproject.toml alone; install the deps.
    ("cb94",
     "# Install the project (runtime deps only) before copying source for layer caching.\n"
     "COPY pyproject.toml ./\n"
     "RUN pip install --no-cache-dir .",
     "# Install the runtime dependencies before copying source for layer caching.\n"
     "COPY pyproject.toml ./\n"
     "RUN python -c \"import tomllib; print('\\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))\" > requirements.txt \\\n"
     "    && pip install --no-cache-dir -r requirements.txt"),

    # D11b: the approver command the challenge prints must exist.
    ("cb111",
     '                    "sre-approve --challenge-id {cid} --action {action} "',
     '                    "python -m sre_mcp.host approve --secret $SRE_APPROVAL_SECRET "\n'
     '                    "--challenge-id {cid} --action {action} "'),
    # D13: HttpObservability (compose) has no probe endpoints; keep the probes simulated.
    ("cb111",
     '        stages = [\n'
     '            ("database-pool", obs.check_database_pool),\n'
     '            ("redis-slots", obs.check_redis_slots),\n'
     '            ("kafka-lag", obs.check_kafka_lag),\n'
     '        ]',
     '        # HttpObservability (compose) has no probe endpoints: probes stay simulated.\n'
     '        probes = obs if isinstance(obs, MockObservability) else MockObservability()\n'
     '        stages = [\n'
     '            ("database-pool", probes.check_database_pool),\n'
     '            ("redis-slots", probes.check_redis_slots),\n'
     '            ("kafka-lag", probes.check_kafka_lag),\n'
     '        ]'),
    # D12: wake on shutdown instead of sleeping out a whole rotation interval.
    ("cb111",
     "    while not stop.is_set():\n"
     "        await asyncio.sleep(interval)",
     "    while not stop.is_set():\n"
     "        try:  # wake at once on shutdown instead of sleeping out the interval\n"
     "            await asyncio.wait_for(stop.wait(), timeout=interval)\n"
     "            break\n"
     "        except asyncio.TimeoutError:\n"
     "            pass"),

    # Minor: the mock report gave the total as the top exception's count; off-by-one line count.
    ("cb112",
     '        + f"\\n\\n2. LIKELY ROOT CAUSE\\nThe dominant failure is {top} ({total} occurrences). "',
     '        + f"\\n\\n2. LIKELY ROOT CAUSE\\nThe dominant failure is {top} "\n'
     '        f"({counts[top]} of {total} exceptions). "'),
    ("cb112",
     '    trace("sampling_callback_invoked", lines_analyzed=log_section.count("\\n"),',
     '    trace("sampling_callback_invoked", lines_analyzed=len(log_section.strip("\\n").splitlines()),'),
    # D11: the next rotation can be more than 10 s away (compose and §8.9 use 15 s).
    ("cb112",
     '            with _timeout(10):\n'
     '                async for event in sub:\n'
     '                    trace("resource_updated", uri=event.uri)\n'
     '                    break',
     '            try:\n'
     '                with _timeout(60):  # longer than any rotation interval in use\n'
     '                    async for event in sub:\n'
     '                        trace("resource_updated", uri=event.uri)\n'
     '                        break\n'
     '            except TimeoutError:\n'
     '                trace("resource_updated_timeout")'),

    # D10: without --transport the server serves stdio and nothing listens on :8000.
    ("cb114",
     'CMD ["python", "-m", "sre_mcp.server"]',
     'CMD ["python", "-m", "sre_mcp.server", "--transport", "streamable-http"]'),
    ("cb115",
     '    command: ["python", "-m", "sre_mcp.server"]',
     '    command: ["python", "-m", "sre_mcp.server", "--transport", "streamable-http"]'),
]

PROSE = [
    # D2: name the wire method correctly.
    ("<code>message_handler</code> watches for <code>notifications/tools/listChanged</code> and invalidates eagerly.",
     "<code>message_handler</code> watches for <code>notifications/tools/list_changed</code> and invalidates eagerly."),
    ("call, a <code>tools/listChanged</code> notification.",
     "call, a <code>tools/list_changed</code> notification."),
    ("again whenever a domain server emits <code>tools/listChanged</code>",
     "again whenever a domain server emits <code>tools/list_changed</code>"),
    ("a newly added upstream tool (the <code>tools/listChanged</code> path)",
     "a newly added upstream tool (the <code>tools/list_changed</code> path)"),
    # Minor: the configuration constants are in the §4.5 listing, not here.
    ("The module header, configuration, and lifespan:",
     "The module header and lifespan (the configuration constants they read open the listing in §4.5):"),
    # Minor: what the model actually receives.
    ("The mapping, in full:",
     "The mapping, in full. The SDK prefixes each message with <code>Error executing tool &lt;name&gt;: </code>, and it rejects schema violations (an <code>order_id</code> that misses the pattern) itself, before the wrapper runs:"),
    ("\"Invalid arguments — nothing was sent downstream: order_id: String should match pattern '^ORD-\\d{6}$'\"",
     "\"Invalid arguments for issue_refund — nothing was sent downstream. Fix these and call again: Value error, refunds over 1000 require a reason of at least 30 characters (audit rule)\""),
    # D11b: give the two commands the reader has to type.
    ("Terminal two runs the triage loop against <code>http://localhost:8000/mcp</code>. When it proposes the rollback, mint the token in terminal three as the on-call engineer and paste it at the prompt.",
     "Terminal two runs the triage loop against <code>http://localhost:8000/mcp</code> with <code>PYTHONPATH=$PWD ../../.venv/bin/python -m sre_mcp.host triage</code>. When it proposes the rollback, mint the token in terminal three as the on-call engineer with <code>python -m sre_mcp.host approve --secret dev-secret --challenge-id … --action rollback_deployment --target payments-api --expires-at …</code> (the pending challenge prints the exact values) and paste it at the prompt."),
]

RAW = [
    # Minor: cb24 prints six spaces after "reduction:".
    ("reduction:       92% of context reclaimed", "reduction:      92% of context reclaimed"),
]

_BLOCK = r'(<div class="sourceCode" id="{cid}"><pre\s+class="sourceCode \w+"><code class="sourceCode \w+">)(.*?)(</code></pre></div>)'
_LINE = r'<span id="{cid}-[^"]+"><a href="#{cid}-[^"]+" aria-hidden="true" tabindex="-1"></a>(.*)</span>'


def _plain(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))


def _code(text: str, cid: str, old: str, new: str) -> str:
    blocks = list(re.finditer(_BLOCK.format(cid=cid), text, flags=re.S))
    assert len(blocks) == 1, f"{cid}: {len(blocks)} blocks"
    b = blocks[0]
    rows = []
    for ln in b.group(2).split("\n"):
        m = re.fullmatch(_LINE.format(cid=cid), ln)
        assert m, f"{cid}: unexpected line markup {ln[:60]}"
        rows.append(m.group(1))
    plain = [_plain(r) for r in rows]
    old_l, new_l = old.split("\n"), new.split("\n")
    hits = [i for i in range(len(plain) - len(old_l) + 1) if plain[i:i + len(old_l)] == old_l]
    assert len(hits) == 1, f"{cid}: {len(hits)} matches for {old_l[0][:60]!r}"
    i = hits[0]
    head = 0
    while head < min(len(old_l), len(new_l)) and old_l[head] == new_l[head]:
        head += 1
    tail = 0
    while tail < min(len(old_l), len(new_l)) - head and old_l[-1 - tail] == new_l[-1 - tail]:
        tail += 1
    span = rows[i:i + len(old_l)]
    middle = [html.escape(s) for s in new_l[head:len(new_l) - tail]]
    rows[i:i + len(old_l)] = span[:head] + middle + span[len(span) - tail:]
    body = "\n".join(f'<span id="{cid}-{k}"><a href="#{cid}-{k}" aria-hidden="true" tabindex="-1"></a>{r}</span>'
                     for k, r in enumerate(rows, 1))
    return text[:b.start(2)] + body + text[b.end(2):]


def _prose(text: str, old: str, new: str) -> str:
    hits = [m for m in re.finditer(r"<(p|li|td)>(.*?)</\1>", text, flags=re.S)
            if old in re.sub(r"\s+", " ", m.group(2))]
    assert len(hits) == 1, f"{len(hits)} prose matches for {old[:60]!r}"
    m = hits[0]
    inner = re.sub(r"\s+", " ", m.group(2))
    assert inner.count(old) == 1, f"repeated in block: {old[:60]!r}"
    block = f"<{m.group(1)}>{inner.replace(old, new)}</{m.group(1)}>"
    return text[:m.start()] + block + text[m.end():]


def apply(text: str) -> str:
    for cid, old, new in CODE:
        text = _code(text, cid, old, new)
    for old, new in PROSE:
        text = _prose(text, old, new)
    for old, new in RAW:
        assert text.count(old) == 1, f"{text.count(old)} raw matches for {old[:60]!r}"
        text = text.replace(old, new)
    return text

"""Sentence-level edits to the MCP guide: split the longest sentences (over 35 words).

guides/guide.py applies these to the source on load in load().
Each edit is (old, new) on whitespace-normalised paragraph text; every old string must match once.
"""
import pathlib
import re

FIXES = [
    ("Handing such a caller a contract written for a compiler is like handing a tourist a subway map in a language they cannot read: all the information is there, and none of it is usable under time pressure.",
     "Handing such a caller a contract written for a compiler is like handing a tourist a subway map in a language they cannot read. All the information is there. None of it is usable under time pressure."),
    ("Shaving 5 ms off a tool is pointless if the agent needs five turns to do the job; one coarse intent that finishes in a single 800 ms call beats five 40 ms CRUD calls wrapped in four extra reasoning turns.",
     "Shaving 5 ms off a tool is pointless if the agent needs five turns to do the job. One coarse intent that finishes in a single 800 ms call beats five 40 ms CRUD calls wrapped in four extra reasoning turns."),
    ("Prefer flat markdown or a flat model over nested JSON: models parse prose more reliably than they traverse trees, and flat shapes survive truncation gracefully (a cut-off nested object is garbage; a cut-off bullet list is still half the facts).",
     "Prefer flat markdown or a flat model over nested JSON. Models parse prose more reliably than they traverse trees. Flat shapes also survive truncation: a cut-off nested object is garbage, while a cut-off bullet list is still half the facts."),
    ("Notice what the pruning deliberately destroyed: the full UUIDs (replaced by an 8-character prefix the agent can quote back to a human, but cannot join on), the <code>total_cents</code> minor-unit convention (dollars, like the business talks), and the entire <code>audit</code> and <code>internal_flags</code> blocks.",
     "Notice what the pruning deliberately destroyed:</p><ul><li>the full UUIDs, replaced by an 8-character prefix the agent can quote back to a human but cannot join on;</li><li>the <code>total_cents</code> minor-unit convention, replaced by dollars, the way the business talks;</li><li>the entire <code>audit</code> and <code>internal_flags</code> blocks.</li></ul><p>"),
    ("You will build one MCP server the way an enterprise would run it — pooled connections, strict timeouts, retries with backoff, validated inputs, errors the model can act on — and one client that talks to it over Streamable HTTP with auth, caching, and timeout guards.",
     "You will build one MCP server the way an enterprise would run it: pooled connections, strict timeouts, retries with backoff, validated inputs, and errors the model can act on. You will also build one client that talks to it over Streamable HTTP, with auth, caching, and timeout guards."),
    ("In a real enterprise the agent never talks to microservices directly — the MCP server is the integration point, which means it owns the HTTP policy (pooling, timeouts, retries), the validation policy, and the error-translation policy in one place.",
     "In a real enterprise the agent never talks to microservices directly. The MCP server is the integration point. So it owns three policies in one place: HTTP (pooling, timeouts, retries), validation, and error translation."),
    ("This module names each failure mode, then builds the fix: an enterprise MCP gateway in FastAPI and the <code>mcp</code> 2.x SDK, with a federated tool registry, claim-aware tool filtering, zero-trust on-behalf-of identity, human-in-the-loop interception, and governance baked into the hot path.",
     "This module names each failure mode, then builds the fix: an enterprise MCP gateway in FastAPI and the <code>mcp</code> 2.x SDK. The gateway has a federated tool registry, claim-aware tool filtering, zero-trust on-behalf-of identity, human-in-the-loop interception, and governance baked into the hot path."),
    ("The <strong>control plane</strong> answers \"what is allowed\": the federated tool registry (which tools exist, where they route), the policy store (which scopes each tool needs, which tools need human approval), the approval store (pending challenges), and the audit configuration.",
     "The <strong>control plane</strong> answers \"what is allowed\". It holds four things:</p><ul><li>the federated tool registry: which tools exist, and where they route;</li><li>the policy store: which scopes each tool needs, and which tools need human approval;</li><li>the approval store: pending challenges;</li><li>the audit configuration.</li></ul><p>"),
    ("Instead it performs an OAuth 2.0 Token Exchange (RFC 8693): it presents the user's JWT as the <em>subject token</em> to the corporate authorization server and receives a fresh <em>downstream token</em> minted for this exact hop — short-lived, audience-bound to the downstream microservice, carrying only the scopes the gateway authorizes for this tool.",
     "Instead it performs an OAuth 2.0 Token Exchange (RFC 8693). It presents the user's JWT as the <em>subject token</em> to the corporate authorization server. It receives a fresh <em>downstream token</em> minted for this exact hop. That token is short-lived, audience-bound to the downstream microservice, and carries only the scopes the gateway authorizes for this tool."),
    ("A pure-ASGI auth middleware validates the JWT before the MCP app sees the request and stashes the claims, subject token, and traceparent in contextvars — so each generated tool runs the <em>full</em> pipeline (scope check, HITL, OBO exchange, audit), not a bypass around it.",
     "A pure-ASGI auth middleware validates the JWT before the MCP app sees the request. It stashes the claims, subject token, and traceparent in contextvars. So each generated tool runs the <em>full</em> pipeline (scope check, HITL, OBO exchange, audit), not a bypass around it."),
    ("Notice the ordering inside the handler: the idempotency check runs before any money moves, and the key is derived from <code>(order, sku, reason)</code> so a retry of the same ticket reuses it while a genuinely new refund gets a fresh key.",
     "Notice the ordering inside the handler: the idempotency check runs before any money moves. The key is derived from <code>(order, sku, reason)</code>. A retry of the same ticket reuses it, while a genuinely new refund gets a fresh key."),
    ("<code>Annotated</code> + <code>Field</code> constraints become the tool's JSON Schema, so Pydantic rejects a negative amount or a short idempotency key before any downstream call happens — a bad call fails fast as an <code>isError</code> result, never as a half-executed refund.",
     "<code>Annotated</code> + <code>Field</code> constraints become the tool's JSON Schema. Pydantic rejects a negative amount or a short idempotency key before any downstream call happens. A bad call fails fast as an <code>isError</code> result, never as a half-executed refund."),
    ("It builds a full incident-triage system — an MCP server that watches logs and metrics, digs through 5,000 lines of stack traces, probes the database, Redis, and Kafka — and then stops cold at the one action that matters.",
     "It builds a full incident-triage system: an MCP server that watches logs and metrics, digs through 5,000 lines of stack traces, and probes the database, Redis, and Kafka. Then it stops cold at the one action that matters."),
    ("Verification is four checks in order: signature via <code>hmac.compare_digest</code> (constant time, no oracle), expiry, store lookup with single-use enforcement (consume <em>before</em> executing, so a crash cannot double-apply), and action/target binding (a token minted for a scale cannot authorize a rollback).",
     "Verification is four checks in order:</p><ol><li>signature, via <code>hmac.compare_digest</code> (constant time, no oracle);</li><li>expiry;</li><li>store lookup with single-use enforcement (consume <em>before</em> executing, so a crash cannot double-apply);</li><li>action/target binding (a token minted for a scale cannot authorize a rollback).</li></ol><p>"),
    ("Two things the suite deliberately does not cover, because the sandbox cannot: the Redis challenge store (needs a Redis server — the sketch is in <code>approvals.py</code>, exercised by <code>docker compose up</code>) and the live Streamable HTTP transport (the tests use in-process and memory-stream transports, which exercise the same protocol handlers).",
     "Two things the suite deliberately does not cover, because the sandbox cannot:</p><ul><li>the Redis challenge store, which needs a Redis server (the sketch is in <code>approvals.py</code>, exercised by <code>docker compose up</code>);</li><li>the live Streamable HTTP transport (the tests use in-process and memory-stream transports, which exercise the same protocol handlers).</li></ul><p>"),
]



def apply(text: str) -> str:
    for old, new in FIXES:
        hits = []
        for m in re.finditer(r"<(p|li)>(.*?)</\1>", text, flags=re.S):
            if old in re.sub(r"\s+", " ", m.group(2)):
                hits.append(m)
        assert len(hits) == 1, f"{len(hits)} matches for: {old[:60]}"
        m = hits[0]
        assert m.group(1) == "p" or "</p>" not in new, f"block markup in <li>: {old[:60]}"
        inner = re.sub(r"\s+", " ", m.group(2)).replace(old, new)
        block = f"<{m.group(1)}>{inner}</{m.group(1)}>".replace("<p></p>", "")
        text = text[:m.start()] + block + text[m.end():]
    return text


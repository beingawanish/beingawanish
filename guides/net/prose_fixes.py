"""Factual corrections to the Networking Mastery Guide source, found while writing the deep dives.

guides/guide.py applies these on load. Each (old, new) must match exactly once.
"""

FIXES = [
    # Module 12: RFC 9258 is the TLS external-PSK importer, not Encrypted ClientHello.
    ("(Encrypted ClientHello exists — RFC 9258 — but deployment is still early.)",
     "(Encrypted ClientHello, ECH, fixes this, but deployment is still early.)"),
    # Module 12: num_connects counts new connections; a reused connection reports 0.
    ("One connection serving two requests shows <code>num_connects</code> as 1.</li>",
     "The first transfer prints 1 and the second prints 0. <code>num_connects</code> counts new connections, so 0 on the second request means it reused the first connection.</li>"),
    # Module 16: WireGuard rekeys with a fresh 1-RTT handshake at least every 120 s.
    ("WireGuard rotates data-path keys every couple of minutes, continuously, with no handshake involved: each side just starts using the next key derived from the ongoing chain.",
     "WireGuard rotates data-path keys every couple of minutes: it runs a fresh 1-RTT handshake at least every 120 seconds, and both sides switch to the new keys without dropping traffic."),
]


def apply(text: str) -> str:
    for old, new in FIXES:
        assert text.count(old) == 1, f"{text.count(old)} matches for: {old[:60]}"
        text = text.replace(old, new)
    return text

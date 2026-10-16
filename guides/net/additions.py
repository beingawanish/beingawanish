"""Merge the deep dives and new modules into the Networking Mastery Guide (run by guide.py load()).

deep/NN.html  -> appended to the end of module NN (inserted before the next <h1>), TOC entries
                 nested under module NN.
new/NN-*.html -> new modules, inserted in order before the back matter, which is renumbered.
Every edit asserts its match count.
"""
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
OLD_BACK = ("module-19--back-matter", "Module 19 — Back Matter")


def _toc(fragment: str, levels: str = "12") -> str:
    out, open_h1 = [], False
    for m in re.finditer(r'<h([12]) id="([^"]+)">(.*?)</h\1>', fragment):
        level, hid, inner = m.groups()
        if level not in levels:
            continue
        link = f'<a href="#{hid}" id="toc-{hid}">{inner}</a>'
        if level == "1":
            if open_h1:
                out.append("</ul></li>")
            out.append(f"<li>{link} <ul>")
            open_h1 = True
        else:
            out.append(f"<li>{link}</li>")
    if open_h1:
        out.append("</ul></li>")
    return "\n".join(out)


def _module_h1(text: str, n: int) -> re.Match:
    m = re.search(rf'<h1 id="module-{n:02d}--[^"]*">', text)
    assert m, f"module {n:02d} heading not found"
    return m


def _toc_close(text: str, n: int) -> int:
    """Index of the </ul> that closes module n's TOC sub-list."""
    start = text.index(f'id="toc-module-{n:02d}--')
    nxt = text.index('<li><a href="#module-', start + 1)
    return text.rindex("</ul>", start, nxt)


def apply(text: str) -> str:
    deep = sorted((HERE / "deep").glob("[0-9][0-9].html"))
    new = sorted((HERE / "new").glob("[0-9][0-9]-*.html"))

    # Deep dives: body before the next module's h1; TOC inside module NN's list.
    for f in deep:
        n = int(f.stem)
        frag = f.read_text().strip()
        nxt = _module_h1(text, n + 1)
        text = text[:nxt.start()] + frag + "\n" + text[nxt.start():]
        close = _toc_close(text, n)
        text = text[:close] + _toc(frag, "2") + "\n" + text[close:]

    total = 18 + len(new)
    back_n = total + 1
    new_back = (f"module-{back_n}--back-matter", f"Module {back_n} — Back Matter")
    if new:
        body = "\n".join(f.read_text().strip() for f in new)
        old_h1 = f'<h1 id="{OLD_BACK[0]}">{OLD_BACK[1]}</h1>'
        assert text.count(old_h1) == 1
        text = text.replace(old_h1, f'{body}\n<h1 id="{new_back[0]}">{new_back[1]}</h1>')
        old_toc = f'<li><a href="#{OLD_BACK[0]}" id="toc-{OLD_BACK[0]}">{OLD_BACK[1]}</a>'
        assert text.count(old_toc) == 1
        toc = "\n".join(_toc(f.read_text()) for f in new)
        text = text.replace(old_toc, f'{toc}\n<li><a href="#{new_back[0]}" id="toc-{new_back[0]}">{new_back[1]}</a>')
        text = text.replace(f'href="#{OLD_BACK[0]}"', f'href="#{new_back[0]}"')
        text = re.sub(r"Module (\d+) of 18\b", rf"Module \1 of {total}", text)

    for old, new_text, count in TEXT_EDITS(len(new)):
        assert text.count(old) == count, f"expected {count} of: {old[:70]}"
        text = text.replace(old, new_text)
    return text


WORDS = {18: "eighteen", 19: "nineteen", 20: "twenty", 21: "twenty-one", 22: "twenty-two", 23: "twenty-three"}
NEW_LIST = [
    ("Load Balancing", "L4 vs L7, algorithms from round robin to Maglev, health checks, draining, global load balancing"),
    ("QUIC &amp; HTTP/3", "streams without head-of-line blocking, connection IDs and migration, 0-RTT, discovery and fallback"),
    ("BGP &amp; How the Internet Routes", "autonomous systems, peering and transit, best-path selection, hijacks and RPKI"),
    ("Cloud Networking", "VPCs as overlays, route tables, NAT gateways, security groups, peering, Transit Gateway, PrivateLink"),
    ("Container &amp; Kubernetes Networking", "namespaces and veth, CNI, Services and kube-proxy vs eBPF, CoreDNS, NetworkPolicy, service mesh"),
]


def TEXT_EDITS(new_count: int) -> list[tuple[str, str, int]]:
    if not new_count:
        return []
    word = WORDS[18 + new_count]
    items = "\n".join(f"<li>{t} — {d}</li>" for t, d in NEW_LIST[:new_count])
    return [
        ('<li><a href="#the-eighteen-modules" id="toc-the-eighteen-modules">The eighteen modules</a></li>',
         f'<li><a href="#the-eighteen-modules" id="toc-the-eighteen-modules">The {word} modules</a></li>', 1),
        ("— eighteen modules,", f"— {word} modules,", 1),
        ('<h2 id="the-eighteen-modules">The eighteen modules</h2>', f'<h2 id="the-eighteen-modules">The {word} modules</h2>', 1),
        ("<p>Back matter: glossary,",
         "<p>Then five modules for the systems you meet in production today:</p>\n<ol start=\"19\">\n" + items
         + "\n</ol>\n<p>Every module from 01 to 18 also ends with a set of <strong>Deep dive</strong> sections. They replace the analogy with the real machine: the state it keeps, what the wire and the kernel actually do, the numbers that matter, how it fails in production and how to prove it, and the questions a senior interviewer asks.</p>\n<p>Back matter: glossary,", 1),
    ]

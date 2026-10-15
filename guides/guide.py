#!/usr/bin/env python3
"""Rewrite pipeline for the CCAR-P prep guide.

    python3 guides/guide.py ccar-p extract 01   # dump chapter 01's prose blocks to guides/ccar-p/work/ch01.json
    python3 guides/guide.py ccar-p check        # fact-check every rewrite against its original
    python3 guides/guide.py ccar-p build        # apply rewrites + layout -> dist/ccar-p-prep-guide.html

Each guide lives in guides/<name>/: source/<name>-prep-guide.original.html and rewrites/chNN.json.
The readability layer (layout.css, layout.js) is shared by all guides.

Only prose is rewritten: single-line <p> and <li> blocks outside code, SVG and tables.
Figures, tables, code, formulas and headings are copied byte-for-byte.

A rewrite map (rewrites/chNN.json) is {block_id: new_inner_html}. Block ids are a hash
of the original block, so maps stay valid if unrelated parts of the guide change.
A block left out of the map is kept as written ("don't rewrite for the sake of it").

`check` enforces the skill's rule 7 (keep every fact) mechanically, per block:
every number, every <code> span, every link target and every bold term in the
original must still be present in the rewrite.
"""

from __future__ import annotations

import hashlib
import html
import json
import pathlib
import re
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
NAME = sys.argv[1] if len(sys.argv) > 1 else "ccar-p"
GUIDE = HERE / NAME
SOURCE = GUIDE / "source" / f"{NAME}-prep-guide.original.html"
REWRITES = GUIDE / "rewrites"
WORK = GUIDE / "work"
OUT = ROOT / "dist" / f"{NAME}-prep-guide.html"

H1 = re.compile(r'^<h1 id="(\d\d)--')
BLOCK = re.compile(r"^(<(p|li)(?: class=\"[^\"]*\")?>)(.*)(</\2>)\s*$")
PROTECT_OPEN = re.compile(r"<(pre|svg|table|code class=\"sourceCode)")
PROTECT_CLOSE = {"pre": "</pre>", "svg": "</svg>", "table": "</table>", "code class=\"sourceCode": "</code>"}


def load() -> list[str]:
    return SOURCE.read_text().split("\n")


def chapters(lines: list[str]) -> dict[str, tuple[int, int]]:
    starts = [(i, H1.match(l).group(1)) for i, l in enumerate(lines) if H1.match(l)]
    spans = {}
    for k, (i, num) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        spans[num] = (i, end)
    return spans


def blocks(lines: list[str], start: int, end: int):
    """Yield (line_no, open_tag, inner, close_tag) for rewritable prose blocks."""
    depth: list[str] = []
    for i in range(start, end):
        line = lines[i]
        if depth:
            if depth[-1] in line:
                depth.pop()
            continue
        m = PROTECT_OPEN.search(line)
        if m and not line.lstrip().startswith(("<p", "<li")):
            close = PROTECT_CLOSE[m.group(1)]
            if close not in line[m.end():]:
                depth.append(close)
            continue
        b = BLOCK.match(line)
        if not b or 'dg-callout-title' in b.group(1) or 'dg-caption' in b.group(1):
            continue
        inner = b.group(3)
        if len(re.sub(r"<[^>]+>", "", inner).split()) < 12:  # too short to need a rewrite
            continue
        yield i, b.group(1), inner, b.group(4)


def block_id(inner: str) -> str:
    return hashlib.sha1(inner.encode()).hexdigest()[:10]


# --- fact guard ------------------------------------------------------------------------

NUM = re.compile(r"(?<![\w.])[$€£]?\d[\d,]*(?:\.\d+)?%?(?![\w])")


def facts(inner: str) -> dict[str, Counter]:
    text = html.unescape(re.sub(r"<code>.*?</code>", " ", inner))
    plain = re.sub(r"<[^>]+>", " ", text)
    return {
        "numbers": Counter(n.rstrip(",") for n in NUM.findall(plain)),
        "code": Counter(re.findall(r"<code>(.*?)</code>", inner)),
        "links": Counter(re.findall(r'href="([^"]+)"', inner)),
        "bold": Counter(re.sub(r"<[^>]+>", "", b).strip() for b in re.findall(r"<b>(.*?)</b>", inner)),
    }


def missing(orig: str, new: str) -> list[str]:
    fo, fn = facts(orig), facts(new)
    out = []
    for kind in ("numbers", "code", "links"):
        lost = fo[kind] - fn[kind]
        if lost:
            out.append(f"{kind} lost: {sorted(lost)}")
    lost_bold = [b for b in fo["bold"] if b not in fn["bold"] and len(b.split()) <= 6]
    if lost_bold:
        out.append(f"bold terms lost: {lost_bold}")
    return out


def all_rewrites() -> dict[str, str]:
    merged: dict[str, str] = {}
    for f in sorted(REWRITES.glob(f"ch{only or '*'}.json")):
        merged.update(json.loads(f.read_text()))
    return merged


# --- commands ----------------------------------------------------------------------------

def cmd_extract(num: str) -> None:
    lines = load()
    s, e = chapters(lines)[num]
    WORK.mkdir(exist_ok=True)
    data = {block_id(inner): {"tag": open_tag[1:3].strip(">"), "html": inner}
            for _, open_tag, inner, _ in blocks(lines, s, e)}
    path = WORK / f"ch{num}.json"
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    words = sum(len(re.sub(r"<[^>]+>", "", v["html"]).split()) for v in data.values())
    print(f"{path.relative_to(ROOT)}: {len(data)} blocks, {words} words")


def cmd_check(only: str | None = None) -> int:
    lines = load()
    originals = {block_id(inner): inner for num, (s, e) in chapters(lines).items()
                 for _, _, inner, _ in blocks(lines, s, e)}
    problems = 0
    for f in sorted(REWRITES.glob(f"ch{only or '*'}.json")):
        rw = json.loads(f.read_text())
        bad = 0
        for bid, new in rw.items():
            if bid not in originals:
                print(f"{f.name} {bid}: unknown block id"); bad += 1; continue
            for msg in missing(originals[bid], new):
                print(f"{f.name} {bid}: {msg}"); bad += 1
        print(f"{f.name}: {len(rw)} rewritten blocks, {bad} problems")
        problems += bad
    return 1 if problems else 0


LAYOUT_CSS = (HERE / "layout.css")
LAYOUT_JS = (HERE / "layout.js")


def cmd_build() -> None:
    lines = load()
    rw = all_rewrites()
    spans = chapters(lines)
    applied = 0
    for num, (s, e) in spans.items():
        for i, open_tag, inner, close in list(blocks(lines, s, e)):
            new = rw.get(block_id(inner))
            if new is not None:
                lines[i] = f"{open_tag}{new}{close}".replace(f"{open_tag}</p>", "").replace("<p></p>", "")
                applied += 1
    doc = "\n".join(lines)
    # Answer options are lettered A-D in every answer key: show them as letters.
    doc = re.sub(r"<ol>(\n<li>(?:(?!</ol>).)*?</ol>\n<aside class=\"dg-callout dg-callout-info\">\n"
                 r"<p class=\"dg-callout-title\">Answer: )", r'<ol class="options">\1', doc, flags=re.S)
    # Hide answers until the reader asks for them.
    doc = re.sub(r'<aside class="dg-callout dg-callout-info">\n<p class="dg-callout-title">(Answer: [^<]+)</p>'
                 r'(.*?)</aside>',
                 lambda m: (f'<details class="answer"><summary>Show answer</summary>'
                            f'<p class="dg-callout-title">{m.group(1)}</p>{m.group(2)}</details>'),
                 doc, flags=re.S)
    doc = doc.replace("</head>", f"<style>\n{LAYOUT_CSS.read_text()}\n</style>\n</head>", 1)
    doc = doc.replace("</body>", f"<script>\n{LAYOUT_JS.read_text()}\n</script>\n</body>", 1)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(doc)
    print(f"wrote {OUT.relative_to(ROOT)}: {applied} prose blocks rewritten, "
          f"{doc.count('class=\"answer\"')} answers collapsed, {doc.count('class=\"options\"')} option lists lettered")


if __name__ == "__main__":
    cmd, *rest = sys.argv[2:] or ["build"]
    if cmd == "extract":
        cmd_extract(rest[0])
    elif cmd == "check":
        sys.exit(cmd_check(rest[0] if rest else None))
    else:
        cmd_build()

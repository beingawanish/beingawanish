#!/usr/bin/env python3
"""Build dist/system-design-patterns.html: the course with deep-dive sections added.

Each guides/sdp/deep/<slug>.html is inserted into <template id="t-<slug>">, just before the
lesson's "TL;DR" h2 (or at the end of the template when the lesson has none). The course's own
script builds the "On this page" outline from the h2/h3 headings, so new sections appear there.
Checks: every fragment matches a lesson; deep-dive ids are unique and new.
"""
import collections
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "source" / "system-design-patterns.original.html"
OUT = HERE.parent.parent / "dist" / "system-design-patterns.html"


def _ids(html: str) -> list[str]:
    return [a or b for a, b in re.findall(r'\sid=(?:"([^"]+)"|([^\s>]+))', html)]


# The uploaded course has 16 places where a pair of dollar amounts ("$40 ... $45") was rendered
# by MathJax as one italic formula, losing the "$" signs and the spaces. Restore the prose.
MATH_FIXES = [
    "$48,200. Summing the event store's <code>CheckedOut</code> events gives $",
    "$40, and write B changes it to $",
    "$45 is the correct price. However, network timing can make A's <code>SET $40</code> reach the cache after B's <code>SET $45</code>. The cache then reports $",
    None,  # covered by the previous entry
    "$15. Each chargeback also counts against your record with your payment processor. With the refunds and the harm to your record included, call the total about $",
    "$4/hour, or $",
    "$5.6M to $",
    "$20 per hour (about $",
    "$4 per hour, or roughly <strong>$",
    "$500 budget and alerts its owner within its first hour, instead of spending $",
    "$500 hard cap on Friday night, within its first hour, and alerts its owner. The maximum loss falls from $",
    '$0.0001. An approximate-nearest-neighbor search across cached embeddings follows, which finds close points without checking every point. A single-node index supports millions of entries, and the <a href="#vector-database-sharding">next lesson covers larger indexes</a>. A cache check costs a hundredth of a cent, but it is 20x cheaper than the $',
    "$2,000/day is about $",
    "$100, so the net saving is <strong>about $",
    "$0.0002 per question, compared with $",
    "$60 payouts reach a $",
]


def fix_math(text: str) -> str:
    ms = list(re.finditer(r"<span[^>]*>\s*<mjx-container.*?</mjx-container>\s*</span>", text, re.S))
    assert len(ms) == len(MATH_FIXES), len(ms)
    spans = [(m.start(), m.end()) for m in ms]
    spans[2] = (spans[2][0], spans[3][1])
    for (a, b), new in reversed([(sp, f) for sp, f in zip(spans, MATH_FIXES) if f]):
        text = text[:a] + new + text[b:]
    for old, new in (("idleness**.", "idleness</strong>."), ("440/day**,", "440/day</strong>,")):
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    return text


def build() -> str:
    text = fix_math(SRC.read_text())
    source_ids = set(_ids(text))
    new_ids: list[str] = []
    # <slug>.html is a lesson's deep dive; <slug>--<part>.html adds further parts after it.
    for frag_path in sorted((HERE / "deep").glob("*.html"), key=lambda p: (p.stem.split("--")[0], p.stem)):
        slug = frag_path.stem.split("--")[0]
        frag = frag_path.read_text().strip()
        new_ids += _ids(frag)
        m = re.search(rf'<template id="t-{re.escape(slug)}">(.*?)</template>', text, re.S)
        assert m, f"no lesson template for {slug}"
        body = m.group(1)
        tldr = None
        for h in re.finditer(r"<h2\b[^>]*>(.*?)</h2>", body):
            if "TL;DR" in h.group(1):
                tldr = h
        at = m.start(1) + (tldr.start() if tldr else len(body))
        # A later part for the same lesson goes after the parts already inserted (they sit right
        # before the TL;DR too, so inserting at the TL;DR keeps file order).
        text = text[:at] + frag + "\n" + text[at:]
    # The course reuses ids across lessons (one lesson renders at a time), so only the new
    # sections' ids are checked: unique among themselves and absent from the course.
    dups = [k for k, v in collections.Counter(new_ids).items() if v > 1 or k in source_ids]
    assert not dups, f"duplicate ids in deep dives: {dups[:10]}"
    return text


if __name__ == "__main__":
    out = build()
    OUT.write_text(out)
    n = len(list((HERE / "deep").glob("*.html")))
    print(f"wrote {OUT.relative_to(HERE.parent.parent)} with {n} deep dives")
    sys.exit(0)

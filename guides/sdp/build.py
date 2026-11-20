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


def build() -> str:
    text = SRC.read_text()
    source_ids = set(_ids(text))
    new_ids: list[str] = []
    for frag_path in sorted((HERE / "deep").glob("*.html")):
        slug = frag_path.stem
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

"""Unwrap pandoc's hard-wrapped prose so every <p>, <li> and heading sits on one line.

The rewrite pipeline works on single-line blocks. This only joins lines inside those tags
(outside <pre>, <svg>, <table>, <style>, <script>); rendered output is unchanged.

    python3 guides/python/normalize.py   # upload.html -> original.html
"""
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent / "source"
SRC = HERE / "python-study-guide.upload.html"
OUT = HERE / "python-study-guide.original.html"

PROTECTED = re.compile(r"<(pre|svg|table|style|script)\b.*?</\1>", re.S)
BLOCK = re.compile(r"<(p|li|h[1-6])(\s[^>]*)?>.*?</\1>", re.S)


def unwrap(segment: str) -> str:
    return BLOCK.sub(lambda m: re.sub(r"\s*\n\s*", " ", m.group(0)), segment)


def normalize(text: str) -> str:
    out, pos = [], 0
    for m in PROTECTED.finditer(text):
        out.append(unwrap(text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(unwrap(text[pos:]))
    return "".join(out)


if __name__ == "__main__":
    OUT.write_text(normalize(SRC.read_text()))
    print(f"wrote {OUT.name}")

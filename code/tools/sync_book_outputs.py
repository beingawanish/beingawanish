#!/usr/bin/env python3
"""Fill every tagged console block in book/*.md from the recorded expected output.

    python3 code/tools/sync_book_outputs.py

A block looks like:

    <!-- expected-output: code/patterns/routing/main.py -->
    ```text
    ...replaced...
    ```

Run this only after `verify.py` is green for the code; `verify.py` then checks the
book quotes stay in sync.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
TAG = re.compile(r"(<!--\s*expected-output:\s*(\S+)\s*-->\s*\n```text\n)(.*?)(```)", re.DOTALL)


def expected_for(target: str) -> str:
    script = ROOT / target
    name = "exercise_expected.txt" if script.name == "exercise_solution.py" else "expected_output.txt"
    return (script.parent / name).read_text()


def main() -> None:
    for md in sorted((ROOT / "book").rglob("*.md")):
        text = md.read_text()
        new = TAG.sub(lambda m: m.group(1) + expected_for(m.group(2)) + m.group(4), text)
        if new != text:
            md.write_text(new)
            print(f"synced {md.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

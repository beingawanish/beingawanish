#!/usr/bin/env python3
"""Run every pattern example, exercise solution and capstone; fail loudly on any drift.

    python3 code/verify.py            # verify everything (exit 1 on any failure)
    python3 code/verify.py routing    # only targets whose path contains "routing"
    python3 code/verify.py --bless    # rewrite expected-output files from passing runs (review the diff!)

For each target script it checks that:
  1. the script exits 0 (every example also asserts its own invariants);
  2. stdout matches the expected-output file byte for byte;
  3. the folder README quotes that expected output verbatim (docs cannot drift);
and for the book it checks that every block tagged
``<!-- expected-output: code/... -->`` matches the named expected-output file.
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CODE = ROOT / "code"
BOOK = ROOT / "book"

# (script glob, expected-output filename next to the script)
TARGETS = [
    ("patterns/*/main.py", "expected_output.txt"),
    ("patterns/*/exercise_solution.py", "exercise_expected.txt"),
    ("capstones/*/main.py", "expected_output.txt"),
]
BOOK_TAG = re.compile(r"<!--\s*expected-output:\s*(\S+)\s*-->\s*\n```text\n(.*?)```", re.DOTALL)


def run(script: pathlib.Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(script)], cwd=ROOT, capture_output=True,
                          text=True, timeout=120, env=env)


def main(argv: list[str]) -> int:
    bless = "--bless" in argv
    filters = [a for a in argv if not a.startswith("--")]
    failures: list[str] = []
    count = 0

    for pattern, expected_name in TARGETS:
        for script in sorted(CODE.glob(pattern)):
            rel = script.relative_to(ROOT)
            if filters and not any(f in str(rel) for f in filters):
                continue
            count += 1
            proc = run(script)
            expected_file = script.parent / expected_name
            if proc.returncode != 0:
                failures.append(f"{rel}: exit {proc.returncode}\n{proc.stderr.strip()[-1500:]}")
                print(f"FAIL  {rel}  (exit {proc.returncode})")
                continue
            if bless:
                expected_file.write_text(proc.stdout)
            if not expected_file.exists():
                failures.append(f"{rel}: missing {expected_file.name}")
                print(f"FAIL  {rel}  (no {expected_file.name})")
                continue
            expected = expected_file.read_text()
            if proc.stdout != expected:
                failures.append(f"{rel}: output differs from {expected_file.name}")
                print(f"FAIL  {rel}  (output drift)")
                continue
            readme = script.parent / ("README.md" if script.parent.parent.name == "patterns" else "brief.md")
            if expected_name == "expected_output.txt" and readme.name == "README.md":
                if not readme.exists() or expected.strip() not in readme.read_text():
                    failures.append(f"{rel}: README.md does not quote the current expected output")
                    print(f"FAIL  {rel}  (README drift)")
                    continue
            print(f"ok    {rel}")

    if not filters and BOOK.exists():
        for md in sorted(BOOK.rglob("*.md")):
            for target, block in BOOK_TAG.findall(md.read_text()):
                count += 1
                script = ROOT / target
                expected_file = script.parent / ("exercise_expected.txt" if script.name == "exercise_solution.py"
                                                 else "expected_output.txt")
                rel = md.relative_to(ROOT)
                if not expected_file.exists() or block != expected_file.read_text():
                    failures.append(f"{rel}: quoted output for {target} is stale")
                    print(f"FAIL  {rel} -> {target}  (book drift)")
                else:
                    print(f"ok    {rel} -> {target}")

    print(f"\n{count - len(failures)}/{count} checks passed")
    for f in failures:
        print(f"\n--- {f}")
    return 1 if failures or count == 0 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""A virtual repository and the tools agents use on it. Tests really execute."""

from __future__ import annotations

import sys
import types

from agentkit import ToolError, ToolRegistry

INITIAL = {
    "cli.py": (
        'USAGE = "usage: report [--verbose]"\n\n'
        "def build_report(rows):\n"
        '    return {"total": sum(r["amount"] for r in rows), "count": len(rows)}\n\n'
        "def main(argv, rows):\n"
        "    rep = build_report(rows)\n"
        '    if "--verbose" in argv:\n'
        "        return f\"count={rep['count']} total={rep['total']}\"\n"
        "    return f\"total={rep['total']}\"\n"
    ),
    "test_cli.py": (
        "from cli import main\n"
        'ROWS = [{"amount": 5}, {"amount": 7}]\n\n'
        "def test_text():\n"
        '    assert main([], ROWS) == "total=12"\n\n'
        "def test_verbose():\n"
        '    assert main(["--verbose"], ROWS) == "count=2 total=12"\n'
    ),
}


def run_tests(files: dict[str, str]) -> dict:
    """Load non-test modules, then run every test_* function in every test_*.py file."""
    modules = {p[:-3]: p for p in files if p.endswith(".py") and not p.startswith("test_")}
    saved = {name: sys.modules.get(name) for name in modules}
    passed, failed = [], []
    try:
        for name, path in modules.items():  # make `from cli import main` resolve to the virtual file
            mod = types.ModuleType(name)
            exec(compile(files[path], path, "exec"), mod.__dict__)
            sys.modules[name] = mod
        for path in sorted(p for p in files if p.startswith("test_")):
            ns: dict = {}
            exec(compile(files[path], path, "exec"), ns)
            for fn in sorted(k for k in ns if k.startswith("test_")):
                try:
                    ns[fn]()
                    passed.append(f"{path}::{fn}")
                except Exception as exc:  # a failing test is data, not a crash
                    failed.append(f"{path}::{fn}: {type(exc).__name__} {exc}")
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
    return {"passed": len(passed), "failed": failed}


def make_tools(files: dict[str, str]) -> ToolRegistry:
    tools = ToolRegistry()

    @tools.register("read_file", "Read a file from the repository", path=str)
    def read_file(path: str) -> str:
        if path not in files:
            raise ToolError(f"no such file {path}; files: {sorted(files)}")
        return files[path]

    @tools.register("write_file", "Create or replace a file", path=str, content=str)
    def write_file(path: str, content: str) -> dict:
        files[path] = content
        return {"written": path, "lines": content.count("\n") + 1}

    @tools.register("run_tests", "Run the whole test suite")
    def run_tests_tool() -> dict:
        return run_tests(files)

    return tools


TOOL_DOCS = {  # one-liners always visible; full docs disclosed on request (context management)
    "read_file": ("read a file", "read_file(path: str) -> str. Paths are repo-relative, e.g. 'cli.py'."),
    "write_file": ("write a whole file", "write_file(path: str, content: str). Replaces the file; write complete content."),
    "run_tests": ("run all tests", "run_tests() -> {passed, failed}. Runs every test_* function in test_*.py."),
}

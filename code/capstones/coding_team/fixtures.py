"""Mock models for the coding-team capstone. Each policy reads only what its agent can see."""

from __future__ import annotations

import json

from agentkit import MockLLM
from capstones.coding_team.repo import INITIAL

REQUEST = "Add a --json flag that prints the report as JSON. Text output must not change."

CLI_V2 = INITIAL["cli.py"].replace(
    "def build_report", "import json\n\ndef build_report").replace(
    '    if "--verbose" in argv:', '    if "--json" in argv:\n        return json.dumps(rep, sort_keys=True)\n'
                                  '    if "--verbose" in argv:')
CLI_V3 = CLI_V2.replace('USAGE = "usage: report [--verbose]"', 'USAGE = "usage: report [--verbose] [--json]"')
TEST_JSON = ("import json\nfrom cli import main\n\n"
             "def test_json():\n"
             '    assert json.loads(main(["--json"], [{"amount": 5}])) == {"count": 1, "total": 5}\n')


def _call(tool, **args):
    return json.dumps({"tool": tool, "args": args})


def developer(prompt: str, system: str) -> str:
    done = prompt.split("TOOLS:", 1)[1]  # summary + recent turns: what the developer can see
    tests_ok = '"failed": []' in done or "tests passed" in done
    if "Address review findings" in prompt:
        if tests_ok and ("wrote cli.py" in done or '"written": "cli.py"' in done):
            return json.dumps({"final": "Added test_cli_json.py; USAGE now lists --json; all tests pass."})
        if "wrote cli.py" in done or '"written": "cli.py"' in done:
            return _call("run_tests")
        if 'USAGE = \\"usage: report [--verbose]\\"' in done or 'USAGE = "usage: report [--verbose]"' in done:
            return _call("write_file", path="cli.py", content=CLI_V3)
        if "wrote test_cli_json.py" in done or '"written": "test_cli_json.py"' in done:
            return _call("read_file", path="cli.py")
        return _call("write_file", path="test_cli_json.py", content=TEST_JSON)
    if tests_ok:
        return json.dumps({"final": "Implemented --json in cli.py; existing tests pass."})
    if "wrote cli.py" in done or '"written": "cli.py"' in done:
        return _call("run_tests")
    if "def build_report" in done:
        return _call("write_file", path="cli.py", content=CLI_V2)
    return _call("read_file", path="cli.py")


def summarizer(prompt: str, system: str) -> str:
    """Folds turns into terse facts; keeps what the developer needs to know it already did."""
    prev = prompt.split("Summary so far: ", 1)[1].split("\n", 1)[0]
    facts = [] if prev == "(none)" else [prev.rstrip(".")]
    for line in prompt.split("New turns:\n", 1)[1].splitlines():
        if line.startswith("ASSISTANT:") and '"tool"' in line:
            call = json.loads(line[len("ASSISTANT: "):])
            verb = {"read_file": "read", "write_file": "wrote", "run_tests": "ran tests"}[call["tool"]]
            facts.append(f"{verb} {call['args'].get('path', '')}".strip())
        elif line.startswith("TOOL:") and '"passed"' in line:
            facts.append("tests passed" if '"failed": []' in line else "tests FAILED")
        elif line.startswith("USER:"):
            facts.append("task received")
    return "; ".join(facts) + "."


def qa(prompt: str, system: str) -> str:
    findings = []
    if "failed=[]" not in prompt:
        findings.append({"id": "F0", "severity": "blocking", "issue": "tests are failing"})
    if "no test mentions --json" in prompt:
        findings.append({"id": "F1", "severity": "blocking", "issue": "no test covers --json output"})
    if "USAGE line does not mention --json" in prompt:
        findings.append({"id": "F2", "severity": "nit", "issue": "USAGE text does not list --json"})
    return json.dumps(findings)


def sequence_lead(order):
    """A lead that delegates in a fixed order, then finishes with the last report it received."""
    def decide(prompt, system):
        history = prompt.split("History:\n", 1)[1]
        for name, instruction in order:
            if f"[{name}]" not in history:
                return json.dumps({"next": name, "instruction": instruction})
        reports = [ln.split(" -> ", 1)[1] for ln in history.splitlines() if " -> " in ln]
        return json.dumps({"next": "FINISH", "final": " | ".join(reports)})
    return decide


def make_models():
    return {
        "dev": MockLLM(developer, name="developer"),
        "summarizer": MockLLM(summarizer, name="summarizer", price=(0.25, 1.25)),
        "qa": MockLLM(qa, name="qa-reviewer"),
        "leads": {
            "tech": MockLLM(sequence_lead([("dev_team", "Implement: " + REQUEST),
                                           ("qa_team", "Review the --json change and get blocking findings fixed")]),
                            name="tech-lead"),
            "dev": MockLLM(sequence_lead([("developer", "Implement: " + REQUEST)]), name="dev-lead"),
            "qa": MockLLM(sequence_lead([("reviewer", "Review the --json change against: " + REQUEST)]), name="qa-lead"),
        },
    }

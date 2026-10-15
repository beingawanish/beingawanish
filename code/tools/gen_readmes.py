#!/usr/bin/env python3
"""Regenerate each pattern folder's README.md from metadata + its expected output.

    python3 code/tools/gen_readmes.py

READMEs are generated (not hand-edited) so the run command and expected output can
never drift from what verify.py checks.
"""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
PATTERNS = ROOT / "code" / "patterns"

META = {
    "prompt_chaining": ("Prompt chaining", 1, "part-1-workflow/01-prompt-chaining.md", "chain.py",
                        "A fixed, linear sequence of LLM calls with code gates between steps."),
    "routing": ("Routing", 2, "part-1-workflow/02-routing.md", "router.py",
                "Classify an input once, then dispatch it to exactly one specialised path."),
    "parallelization": ("Parallelization (fan-out/fan-in)", 3, "part-1-workflow/03-parallelization.md",
                        "fanout.py", "Run independent calls concurrently on a split known in advance; aggregate in code."),
    "orchestrator_workers": ("Orchestrator–workers", 4, "part-1-workflow/04-orchestrator-workers.md",
                             "orchestrator.py", "An LLM decomposes the task at runtime, workers execute, one synthesis merges."),
    "evaluator_optimizer": ("Evaluator–optimizer", 5, "part-1-workflow/05-evaluator-optimizer.md",
                            "optimizer.py", "A generator and a separate rubric-driven evaluator loop until pass, budget, or stall."),
    "guardrailed_generation": ("Guardrailed generation", 11, None, "guardrails.py",
                               "Generate → validate with deterministic code → repair with targeted errors; safe fallback."),
    "human_in_the_loop": ("Human-in-the-loop", 17, None, "hitl.py",
                          "Pause risky actions at a policy checkpoint, persist state, resume exactly once."),
    "eval_harness": ("Eval harness", 21, None, "harness.py",
                     "Fixed cases + scorers → report; per-case comparison decides ship or block."),
}

TEMPLATE = """# Pattern {num} — {title}

{intent}

| | |
|---|---|
| Implementation | [`{module}`]({module}) |
| Demo | [`main.py`](main.py) |
| Exercise solution | {exercise} |
| Chapter | {chapter} |

Python 3.10+, standard library only, offline. The model is `agentkit.MockLLM`, so output is deterministic.

## Run

```
python3 code/patterns/{slug}/main.py
```

## Expected output

```text
{expected}```
{canonical}
Verified by `python3 code/verify.py {slug}`.
"""


def main() -> None:
    for slug, (title, num, chapter, module, intent) in META.items():
        folder = PATTERNS / slug
        expected = (folder / "expected_output.txt").read_text()
        has_ex = (folder / "exercise_solution.py").exists()
        canonical = ""
        if num in (11, 17, 21):
            canonical = ("\n> **Canonical module.** Built early for the support-triage capstone, which imports it. "
                         "Its chapter is written in its assigned part.\n")
        (folder / "README.md").write_text(TEMPLATE.format(
            num=num, title=title, intent=intent, module=module, slug=slug, expected=expected,
            exercise="[`exercise_solution.py`](exercise_solution.py)" if has_ex else "— (with its chapter)",
            chapter=f"[`book/{chapter}`](../../../book/{chapter})" if chapter else "— (written in its assigned part)",
            canonical=canonical,
        ))
        print(f"wrote {folder.relative_to(ROOT)}/README.md")


if __name__ == "__main__":
    main()

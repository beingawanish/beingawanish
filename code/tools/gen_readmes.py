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
    "react": ("ReAct", 6, "part-2-single-agent/06-react.md", "react.py",
              "Interleave Thought → Action → Observation so every step is grounded in what was observed."),
    "plan_and_execute": ("Plan-and-execute", 7, "part-2-single-agent/07-plan-and-execute.md", "planner.py",
                         "Write an explicit plan, execute it step by step, re-plan when results invalidate it."),
    "reflection": ("Reflection / self-critique", 8, "part-2-single-agent/08-reflection.md", "reflect.py",
                   "The same model critiques and revises its own output — no external judge."),
    "tool_use_loop": ("Tool-use loop", 9, "part-2-single-agent/09-tool-use-loop.md", "loop.py",
                      "Structured tool calls, host-side validation and execution, explicit stop conditions."),
    "agentic_rag": ("Agentic RAG", 10, "part-2-single-agent/10-agentic-rag.md", "rag.py",
                    "Decide whether and what to retrieve, grade evidence, reformulate, cite — or abstain."),
    "guardrailed_generation": ("Guardrailed generation", 11, "part-2-single-agent/11-guardrailed-generation.md",
                               "guardrails.py", "Generate → validate with deterministic code → repair with targeted errors; safe fallback."),
    "supervisor": ("Supervisor", 12, "part-3-multi-agent/12-supervisor.md", "supervisor.py",
                   "One coordinator repeatedly picks the next specialist agent and decides when the job is done."),
    "hierarchical_teams": ("Hierarchical teams", 13, "part-3-multi-agent/13-hierarchical-teams.md", "teams.py",
                           "Supervisors of supervisors, with scoped context per team and summaries flowing up."),
    "sequential_handoffs": ("Sequential handoffs", 14, "part-3-multi-agent/14-sequential-handoffs.md", "handoff.py",
                            "Agents transfer ownership of a live conversation via an explicit handoff object."),
    "debate": ("Debate / peer critique", 15, "part-3-multi-agent/15-debate.md", "debate.py",
               "Peer agents argue over rounds; a judge resolves; early agreement stops the debate."),
    "critic_reviewer": ("Critic–reviewer loop", 16, "part-3-multi-agent/16-critic-reviewer.md", "review.py",
                        "An author agent and a tool-using reviewer agent iterate on itemised findings until approval."),
    "human_in_the_loop": ("Human-in-the-loop", 17, "part-3-multi-agent/17-human-in-the-loop.md", "hitl.py",
                          "Pause risky actions at a policy checkpoint, persist state, resume exactly once."),
    "swarm": ("Swarm", 18, "part-3-multi-agent/18-swarm.md", "swarm.py",
              "Peer agents coordinate through a shared blackboard with no central controller."),
    "memory_tiers": ("Memory tiers", 19, "part-4-cross-cutting/19-memory-tiers.md", "memory.py",
                     "Working, episodic and semantic memory with a code-owned write policy and history."),
    "context_management": ("Context management", 20, "part-4-cross-cutting/20-context-management.md", "context.py",
                           "Budget each call's context: pin, progressively disclose, compact, evict."),
    "eval_harness": ("Eval harness", 21, "part-4-cross-cutting/21-eval-harness.md", "harness.py",
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
        if not (folder / "expected_output.txt").exists():
            continue
        expected = (folder / "expected_output.txt").read_text()
        has_ex = (folder / "exercise_solution.py").exists()
        canonical = ""
        users = {11: "support-triage", 17: "support-triage", 21: "support-triage", 3: "support-triage",
                 2: "support-triage", 7: "deep-research", 10: "deep-research", 8: "deep-research",
                 5: "deep-research", 19: "deep-research", 12: "coding-team", 13: "coding-team",
                 16: "coding-team", 9: "coding-team", 20: "coding-team"}
        if num in users:
            canonical = f"\n> **Reused, not copied:** the {users[num]} capstone imports this module.\n"
        (folder / "README.md").write_text(TEMPLATE.format(
            num=num, title=title, intent=intent, module=module, slug=slug, expected=expected,
            exercise="[`exercise_solution.py`](exercise_solution.py)" if has_ex else "— (with its chapter)",
            chapter=f"[`book/{chapter}`](../../../book/{chapter})",
            canonical=canonical,
        ))
        print(f"wrote {folder.relative_to(ROOT)}/README.md")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Hand-placed editorial diagrams, written as plain SVG.

    python3 book/diagrams/draw.py            # (re)writes every diagram defined below

Every coordinate below is placed by hand; the helpers only remove repetition
(colours, arrowheads, text styling). The output .svg files are ordinary,
human-editable SVG — edit them directly or edit the spec here and re-run.

Colour key used across the book: terracotta = model call, sage = deterministic code,
ochre = human, dashed outline = data or external system.
"""

from __future__ import annotations

import pathlib
from html import escape

HERE = pathlib.Path(__file__).resolve().parent
FONT = "'Source Sans 3','Helvetica Neue',Arial,sans-serif"
INK, MUTED, LINE = "#3B2F2A", "#7A6A5E", "#5A4636"
KIND = {  # fill, stroke, dash
    "llm": ("#F6E3D3", "#B5562E", None),
    "code": ("#E7EDE1", "#6B7F5E", None),
    "human": ("#F7E9C4", "#B88A1E", None),
    "data": ("#FFFDF8", "#8C7B70", "5 4"),
    "plain": ("#FFFDF8", "#B5562E", None),
}
ARROW = {"normal": (LINE, None), "fail": ("#B5562E", "4 3"), "ok": ("#6B7F5E", None),
         "muted": ("#8C7B70", "4 3"), "loop": ("#B5562E", None)}


class Diagram:
    def __init__(self, slug: str, w: int, h: int, title: str, desc: str) -> None:
        self.slug, self.w, self.h = slug, w, h
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" '
            f'aria-labelledby="{slug}-t {slug}-d" font-family="{FONT}">',
            f'  <title id="{slug}-t">{escape(title)}</title>',
            f'  <desc id="{slug}-d">{escape(desc)}</desc>',
            "  <defs>",
            f'    <marker id="{slug}-ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{LINE}"/></marker>',
            "  </defs>",
            f'  <rect width="{w}" height="{h}" fill="#FBF5EA"/>',
        ]

    def text(self, x, y, s, size=12, color=INK, anchor="middle", weight=None):
        wt = f' font-weight="{weight}"' if weight else ""
        self.parts.append(f'  <text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" fill="{color}"{wt}>'
                          f'{escape(s)}</text>')

    def box(self, x, y, w, h, kind, title, sub=None, size=13):
        fill, stroke, dash = KIND[kind]
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" '
                          f'stroke="{stroke}" stroke-width="1.5"{d}/>')
        cx = x + w / 2
        if sub:
            self.text(cx, y + h / 2 - 3, title, size, weight="600" if kind != "data" else None)
            self.text(cx, y + h / 2 + 13, sub, 11, MUTED)
        else:
            self.text(cx, y + h / 2 + 5, title, size, weight="600" if kind != "data" else None)

    def diamond(self, cx, cy, r, label, kind="code"):
        fill, stroke, _ = KIND[kind]
        pts = f"{cx},{cy - r} {cx + r},{cy} {cx},{cy + r} {cx - r},{cy}"
        self.parts.append(f'  <polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        self.text(cx, cy + 4, label, 10)

    def arrow(self, pts, kind="normal", label=None, at=None, anchor="middle", head=True):
        color, dash = ARROW[kind]
        d = "M" + " L".join(f"{x},{y}" for x, y in pts)
        dd = f' stroke-dasharray="{dash}"' if dash else ""
        mk = f' marker-end="url(#{self.slug}-ah)"' if head else ""
        self.parts.append(f'  <path d="{d}" fill="none" stroke="{color}" stroke-width="1.5"{dd}{mk}/>')
        if label and at:
            self.text(at[0], at[1], label, 10, color if kind != "normal" else MUTED, anchor)

    def tag(self, x, y, s):
        self.text(x, y, s, 11, "#6B7F5E", weight="700")

    def legend(self, s):
        self.text(16, self.h - 10, s, 11, MUTED, "start")

    def save(self):
        path = HERE / f"{self.slug}.svg"
        path.write_text("\n".join(self.parts + ["</svg>", ""]))
        return path


KEY = "Terracotta = model call · Sage = deterministic code · Dashed = data / failure path"
KEY_H = "Terracotta = model call · Sage = code · Ochre = human · Dashed = data / failure path"


def react():
    d = Diagram("react", 760, 262, "ReAct structure",
                "A question enters a loop: the model writes a Thought and an Action; code runs the tool and appends "
                "an Observation to the growing trace; the loop ends at a Final Answer or a step/repeat guard.")
    d.box(16, 96, 88, 52, "data", "Question")
    d.arrow([(104, 122), (128, 122)])
    d.box(130, 90, 154, 64, "llm", "Thought + Action", "model reads whole trace")
    d.arrow([(284, 122), (344, 122)], label="tool[input]", at=(314, 112))
    d.box(346, 96, 120, 52, "code", "run tool", "validate, execute")
    d.arrow([(466, 122), (494, 122)])
    d.box(496, 96, 120, 52, "data", "Observation", "appended to trace")
    d.arrow([(556, 148), (556, 200), (207, 200), (207, 156)], "loop", "next step sees every prior observation", (380, 194))
    d.arrow([(207, 90), (207, 46), (690, 46), (690, 94)], "ok", "Final Answer", (450, 40))
    d.box(636, 96, 108, 52, "data", "Answer")
    d.arrow([(600, 148), (600, 194)], "fail")
    d.box(586, 196, 158, 44, "code", "stop: max steps", "or repeated action", size=12)
    d.legend(KEY)
    return d.save()


def plan_and_execute():
    d = Diagram("plan_and_execute", 760, 240, "Plan-and-execute structure",
                "A planner model writes an explicit multi-step plan. An executor runs steps one at a time. When a step "
                "fails, an optional local repair is tried in code, otherwise the planner re-plans the remaining steps "
                "within a re-plan budget.")
    d.box(16, 46, 80, 52, "data", "Goal")
    d.arrow([(96, 72), (124, 72)])
    d.box(126, 40, 128, 64, "llm", "planner", "writes plan v1, v2…")
    d.arrow([(254, 72), (282, 72)])
    d.box(284, 40, 136, 64, "data", "plan (JSON)", "s1 → s2 → s3 → s4")
    d.arrow([(420, 72), (448, 72)])
    d.box(450, 40, 126, 64, "code", "executor", "one step at a time")
    d.arrow([(576, 72), (626, 72)], "ok", "all ok", (601, 64))
    d.box(628, 46, 116, 52, "data", "Result")
    d.diamond(513, 156, 22, "fail?")
    d.arrow([(513, 104), (513, 132)], "fail")
    d.box(572, 136, 150, 40, "code", "local repair (cheap)", size=12)
    d.arrow([(535, 156), (570, 156)], "fail")
    d.arrow([(647, 136), (647, 118), (560, 118), (560, 106)], "ok", "retry", (610, 112))
    d.arrow([(491, 156), (190, 156), (190, 106)], "loop", "else re-plan remaining steps (≤ budget)", (340, 150))
    d.text(190, 192, "planner sees all results so far", 10, MUTED)
    d.legend(KEY)
    return d.save()


def reflection():
    d = Diagram("reflection", 760, 250, "Reflection structure",
                "One model drafts an answer, critiques its own draft, and revises. The loop stops when the critique "
                "reports no issues or after a small number of rounds. No external judge is involved.")
    d.box(16, 88, 80, 52, "data", "Task")
    d.arrow([(96, 114), (124, 114)])
    d.box(126, 82, 130, 64, "llm", "draft", "same model")
    d.arrow([(256, 114), (296, 114)])
    d.box(298, 82, 150, 64, "llm", "self-critique", "same model, own draft")
    d.diamond(500, 114, 24, "issues?")
    d.arrow([(448, 114), (474, 114)])
    d.arrow([(524, 114), (610, 114)], "ok", "NO ISSUES", (566, 106))
    d.box(612, 88, 132, 52, "data", "Answer")
    d.box(298, 178, 150, 46, "llm", "revise", "fix every point", size=12)
    d.arrow([(500, 138), (500, 201), (450, 201)], "loop", "yes", (512, 172), "start")
    d.arrow([(298, 201), (191, 201), (191, 148)], "loop")
    d.text(620, 200, "shares the drafter's blind spots", 11, "#B5562E")
    d.legend("Terracotta = model call (all the same model) · Sage = code · Dashed = data")
    return d.save()


def tool_use_loop():
    d = Diagram("tool_use_loop", 760, 290, "Tool-use loop structure",
                "The model emits one structured call. The host validates it, asks for confirmation if the tool has side "
                "effects, executes it, and appends the result or the error as an observation. The host owns all stop "
                "conditions: final answer, step limit, and consecutive errors.")
    d.box(16, 106, 84, 52, "data", "Task")
    d.arrow([(100, 132), (126, 132)])
    d.box(128, 100, 140, 64, "llm", "model", '{"tool","args"} or final')
    d.arrow([(268, 132), (300, 132)])
    d.diamond(326, 132, 26, "valid?")
    d.arrow([(352, 132), (384, 132)], "ok")
    d.diamond(410, 132, 26, "confirm?", "human")
    d.text(410, 176, "side effects only", 10, MUTED)
    d.arrow([(436, 132), (466, 132)], "ok")
    d.box(468, 106, 120, 52, "code", "execute", "tool registry")
    d.arrow([(528, 158), (528, 220), (198, 220), (198, 166)], "loop")
    d.text(363, 240, "result — or ERROR text — appended to the transcript", 10, "#B5562E")
    d.arrow([(326, 158), (326, 220)], "fail", head=False)
    d.arrow([(198, 100), (198, 52), (640, 52), (640, 104)], "ok", "final", (420, 46))
    d.box(600, 106, 144, 52, "data", "Answer")
    d.box(600, 186, 144, 50, "code", "host stops at", "steps · errors · budget", size=12)
    d.legend(KEY_H)
    return d.save()


def agentic_rag():
    d = Diagram("agentic_rag", 760, 320, "Agentic RAG structure",
                "The agent decides whether retrieval is needed. If so it writes a query, retrieves, and grades the "
                "passages. Insufficient evidence leads to a reformulated query; sufficient evidence leads to an answer "
                "whose citations are checked in code. After the query budget the agent abstains.")
    d.box(16, 70, 84, 52, "data", "Question")
    d.arrow([(100, 96), (126, 96)])
    d.diamond(156, 96, 28, "retrieve?", "llm")
    d.arrow([(156, 68), (156, 30), (296, 30)], "ok", "no", (168, 46), "start")
    d.box(298, 12, 150, 36, "data", "direct answer", size=12)
    d.arrow([(184, 96), (218, 96)], label="yes", at=(200, 88))
    d.box(220, 70, 112, 52, "llm", "write query", "uses 'missing'")
    d.arrow([(332, 96), (362, 96)])
    d.box(364, 70, 104, 52, "code", "retrieve", "top-k")
    d.arrow([(468, 96), (498, 96)])
    d.box(500, 70, 100, 52, "llm", "grade", "relevant? enough?")
    d.arrow([(550, 122), (550, 170), (276, 170), (276, 124)], "loop", "insufficient → reformulate", (415, 164))
    d.arrow([(600, 96), (636, 96)], "ok", "enough", (618, 88))
    d.box(638, 70, 106, 52, "llm", "answer", "cite [ids]")
    d.diamond(691, 176, 28, "cites ok?")
    d.arrow([(691, 122), (691, 146)])
    d.box(620, 236, 124, 44, "data", "Cited answer")
    d.arrow([(691, 204), (691, 234)], "ok")
    d.arrow([(240, 122), (240, 234)], "fail", "query budget spent", (248, 214), "start")
    d.box(170, 236, 200, 44, "code", "abstain", "never guess", size=12)
    d.legend(KEY)
    return d.save()


def guardrailed_generation():
    d = Diagram("guardrailed_generation", 760, 280, "Guardrailed generation structure",
                "A model generates structured output. Deterministic validators check schema, policy and safety rules. "
                "Failures are sent back as targeted repair instructions up to a repair budget, after which a safe "
                "fallback is returned and flagged.")
    d.box(16, 96, 84, 52, "data", "Request")
    d.arrow([(100, 122), (126, 122)])
    d.box(128, 90, 140, 64, "llm", "generate", "JSON output")
    d.arrow([(268, 122), (300, 122)])
    d.box(302, 74, 176, 96, "code", "")
    d.text(390, 98, "validators", 13, weight="600")
    d.text(390, 118, "schema · types", 11, MUTED)
    d.text(390, 134, "policy limits", 11, MUTED)
    d.text(390, 150, "PII · length", 11, MUTED)
    d.arrow([(478, 122), (618, 122)], "ok", "all pass", (548, 114))
    d.box(620, 96, 124, 52, "data", "Valid output")
    d.arrow([(390, 170), (390, 214), (198, 214), (198, 156)], "loop", "repair: your output + exact errors", (294, 208))
    d.text(198, 236, "≤ max repairs", 10, MUTED)
    d.arrow([(478, 150), (560, 150), (560, 211), (618, 211)], "fail", "budget spent", (566, 182), "start")
    d.box(620, 188, 124, 46, "code", "safe fallback", "flagged", size=12)
    d.legend(KEY)
    return d.save()


def deep_research():
    d = Diagram("deep_research", 760, 360, "Deep-research capstone architecture",
                "A planner decomposes the question into sub-questions. For each, the agent first checks long-term "
                "memory; on a miss it runs agentic RAG and stores the cited finding. An unanswerable sub-question "
                "triggers a re-plan. The writer drafts, critiques its own draft, then a separate evaluator drives "
                "rubric revisions.")
    d.box(16, 70, 90, 52, "data", "Question")
    d.arrow([(106, 96), (130, 96)])
    d.tag(196, 40, "#7 PLAN-AND-EXECUTE")
    d.box(132, 64, 128, 64, "llm", "planner", "sub-questions")
    d.arrow([(260, 96), (290, 96)])
    d.diamond(318, 96, 28, "memory?")
    d.tag(318, 40, "#19 MEMORY")
    d.arrow([(344, 96), (470, 96)], "ok", "hit: reuse finding", (406, 88))
    d.arrow([(318, 122), (318, 160)], label="miss", at=(336, 146))
    d.tag(318, 232, "#10 AGENTIC RAG")
    d.box(250, 162, 136, 56, "llm", "query · grade", "retrieve · cite")
    d.arrow([(386, 190), (470, 190), (470, 124)], "ok", "store finding", (430, 182))
    d.box(472, 70, 110, 52, "data", "findings", "topic → cited text")
    d.arrow([(250, 190), (196, 190), (196, 130)], "fail")
    d.text(16, 160, "abstain → re-plan", 10, "#B5562E", "start")
    d.arrow([(582, 96), (608, 96)])
    d.tag(676, 40, "#8 REFLECTION")
    d.box(610, 64, 134, 64, "llm", "writer", "draft → self-critique")
    d.arrow([(677, 128), (677, 168)])
    d.text(600, 202, "#5 EVAL–OPTIMIZER", 11, "#6B7F5E", "end", "700")
    d.box(610, 170, 134, 56, "llm", "evaluator", "rubric · feedback")
    d.arrow([(677, 226), (677, 262)], "ok")
    d.box(610, 264, 134, 46, "data", "Cited report")
    d.text(380, 290, "code checks: every number cited · every cited id exists · all topics covered", 11, MUTED)
    d.legend(KEY)
    return d.save()


def supervisor():
    d = Diagram("supervisor", 760, 300, "Supervisor structure",
                "A supervisor model delegates one instruction at a time to specialist worker agents. Every result "
                "returns to the supervisor, which decides again: another worker, or FINISH. Code enforces a turn "
                "budget, valid worker names and loop detection.")
    d.box(16, 80, 84, 52, "data", "Task")
    d.arrow([(100, 106), (138, 106)])
    d.box(140, 90, 150, 80, "llm", "supervisor", "re-decides every turn")
    d.arrow([(290, 130), (400, 130)], label="one instruction", at=(345, 122))
    d.arrow([(400, 47), (400, 183)], head=False)
    for y, name, sub in ((24, "researcher", "finds facts"), (92, "analyst", "computes"), (160, "writer", "drafts")):
        d.arrow([(400, y + 23), (468, y + 23)])
        d.box(470, y, 150, 46, "llm", name, sub, size=12)
        d.arrow([(620, y + 23), (650, y + 23)], "loop", head=False)
    d.arrow([(650, 47), (650, 226), (250, 226), (250, 172)], "loop", "every result returns to the supervisor", (450, 220))
    d.arrow([(140, 160), (58, 160), (58, 194)], "ok", "FINISH", (100, 154))
    d.box(16, 196, 84, 44, "data", "Answer")
    d.box(130, 240, 220, 32, "code", "turn budget · valid worker · loop guard", size=11)
    d.legend(KEY)
    return d.save()


def hierarchical_teams():
    d = Diagram("hierarchical_teams", 760, 320, "Hierarchical teams structure",
                "A top-level lead delegates to team leads. Each team lead supervises its own workers with private "
                "state. Only a short summary flows back up, so the top lead's context stays small.")
    d.box(300, 20, 160, 52, "llm", "launch lead", "sees summaries only")
    d.arrow([(340, 72), (180, 118)])
    d.arrow([(420, 72), (580, 118)])
    d.text(160, 94, "instruction ↓  summary ↑", 10, MUTED)
    d.text(610, 94, "instruction ↓  summary ↑", 10, MUTED)
    d.box(100, 120, 160, 52, "llm", "research lead", "own loop + state")
    d.box(500, 120, 160, 52, "llm", "content lead", "own loop + state")
    for x, names in ((40, ("researcher", "analyst")), (440, ("writer", "editor"))):
        for k, n in enumerate(names):
            bx = x + k * 150
            d.box(bx, 220, 130, 44, "llm", n, size=12)
        d.arrow([(x + 140, 172), (x + 65, 218)])
        d.arrow([(x + 140, 172), (x + 215, 218)])
    d.text(380, 290, "team-internal detail and state never leave the team", 11, MUTED)
    d.legend(KEY)
    return d.save()


def sequential_handoffs():
    d = Diagram("sequential_handoffs", 760, 250, "Sequential handoffs structure",
                "One agent owns the conversation at a time. The owner replies, or hands off with an explicit handoff "
                "object of target, reason and summary. There is no coordinator. The runtime enforces the allowed "
                "handoff graph and a ping-pong guard that escalates to a human.")
    d.box(16, 90, 84, 52, "data", "User")
    d.arrow([(100, 116), (128, 116)])
    xs = [(130, "triage"), (330, "billing"), (530, "technical")]
    for x, n in xs:
        d.box(x, 86, 130, 60, "llm", n, "owns while active")
    d.arrow([(260, 116), (328, 116)], label="handoff", at=(294, 108))
    d.arrow([(460, 116), (528, 116)], label="handoff", at=(494, 108))
    d.box(262, 160, 266, 40, "data", "Handoff {target, reason, summary}", size=11)
    d.arrow([(395, 146), (395, 158)], "muted", head=False)
    d.arrow([(595, 86), (595, 40), (58, 40), (58, 88)], "ok", "owner replies to the user", (330, 34))
    d.box(600, 180, 144, 44, "human", "escalate", "ping-pong / bad target", size=12)
    d.arrow([(640, 146), (640, 178)], "fail")
    d.legend(KEY_H)
    return d.save()


def debate():
    d = Diagram("debate", 760, 270, "Debate structure",
                "Two peer debaters with assigned positions argue over rounds, each seeing the other's latest "
                "argument. If all agree, the debate stops early. Otherwise a judge reads the transcript and decides "
                "with a rationale.")
    d.box(16, 100, 90, 52, "data", "Question")
    d.arrow([(106, 116), (148, 70)])
    d.arrow([(106, 136), (148, 182)])
    d.box(150, 40, 150, 60, "llm", "debater A", "position: for")
    d.box(150, 160, 150, 60, "llm", "debater B", "position: against")
    d.arrow([(240, 100), (240, 158)], "loop", head=True)
    d.arrow([(210, 160), (210, 102)], "loop", head=True)
    d.text(225, 240, "each sees the other's latest argument", 10, "#B5562E")
    d.box(330, 96, 130, 64, "data", "transcript", "rounds 1…R")
    d.arrow([(300, 70), (330, 110)])
    d.arrow([(300, 190), (330, 146)])
    d.diamond(500, 128, 26, "agree?")
    d.arrow([(460, 128), (474, 128)])
    d.arrow([(500, 102), (500, 40), (610, 40)], "ok", "yes → stop", (552, 34))
    d.box(612, 18, 132, 44, "data", "consensus", size=12)
    d.arrow([(526, 128), (580, 128)], label="no", at=(552, 120))
    d.box(582, 100, 162, 56, "llm", "judge", "decision + rationale")
    d.box(582, 180, 162, 46, "code", "check: order-stable?", "swap order, re-judge", size=12)
    d.arrow([(663, 156), (663, 178)], "muted")
    d.legend(KEY)
    return d.save()


def critic_reviewer():
    d = Diagram("critic_reviewer", 760, 280, "Critic–reviewer loop structure",
                "An author agent produces an artefact. A reviewer agent with its own tools runs tests and checks and "
                "files itemised findings with severities. The author answers each finding, fixed or won't fix with a "
                "reason. Code tracks findings: blocking ones must be fixed; approval means none remain open.")
    d.box(16, 96, 84, 52, "data", "Task")
    d.arrow([(100, 122), (128, 122)])
    d.box(130, 90, 140, 64, "llm", "author agent", "writes / revises")
    d.arrow([(270, 122), (318, 122)], label="artefact", at=(294, 114))
    d.box(320, 80, 170, 84, "llm", "")
    d.text(405, 104, "reviewer agent", 13, weight="600")
    d.text(405, 124, "tools: run tests, lint", 11, MUTED)
    d.text(405, 140, "never edits the code", 11, MUTED)
    d.arrow([(490, 122), (536, 122)])
    d.box(538, 90, 120, 64, "data", "findings", "F1 blocking · F2 nit")
    d.arrow([(598, 154), (598, 214), (200, 214), (200, 156)], "loop", "author answers each: fixed | won't fix + reason", (400, 208))
    d.diamond(700, 122, 28, "blocking?")
    d.arrow([(658, 122), (674, 122)])
    d.arrow([(700, 96), (700, 46), (560, 46)], "ok", "none: approve", (640, 40))
    d.box(430, 24, 128, 40, "data", "Approved", size=12)
    d.text(400, 248, "code tracks finding ids: blocking cannot be waived, nits can (with a reason)", 10, MUTED)
    d.legend(KEY)
    return d.save()


def human_in_the_loop():
    d = Diagram("human_in_the_loop", 760, 300, "Human-in-the-loop structure",
                "An agent proposes an action. A code policy decides whether it needs a human. Safe actions execute. "
                "Risky ones go to a durable review queue. A reviewer approves, edits or rejects, possibly in a later "
                "process. Resume executes approved actions exactly once; undecided requests expire to rejected.")
    d.box(16, 100, 92, 52, "llm", "agent", "proposes action")
    d.arrow([(108, 126), (152, 126)])
    d.diamond(182, 126, 30, "policy")
    d.text(182, 172, "refund > $100? irreversible?", 10, MUTED)
    d.text(182, 185, "low confidence?", 10, MUTED)
    d.arrow([(182, 96), (182, 46), (600, 46)], "ok", "no rule fired → execute", (380, 40))
    d.arrow([(212, 126), (262, 126)], "fail", "risky", (237, 118))
    d.box(264, 96, 150, 60, "data", "review queue", "JSON on disk")
    d.arrow([(414, 126), (452, 126)])
    d.box(454, 96, 120, 60, "human", "reviewer", "approve·edit·reject")
    d.arrow([(574, 126), (602, 126)])
    d.box(604, 90, 140, 72, "code", "")
    d.text(674, 116, "resume", 13, weight="600")
    d.text(674, 134, "write-ahead mark", 11, MUTED)
    d.text(674, 150, "execute exactly once", 11, MUTED)
    d.box(604, 26, 140, 40, "data", "side effect", size=12)
    d.arrow([(674, 90), (674, 68)], "ok")
    d.box(264, 210, 310, 44, "code", "deadline passed, undecided → expired (default deny)", size=11)
    d.arrow([(339, 156), (339, 208)], "muted")
    d.legend(KEY_H)
    return d.save()


def swarm():
    d = Diagram("swarm", 760, 300, "Swarm structure",
                "Peer agents with different skills read and write a shared blackboard. Each claims open tasks that "
                "match its skill, posts results and follow-up tasks. No agent is in charge. Code provides the only "
                "global controls: de-duplication, a task cap and a tick budget.")
    d.box(250, 86, 260, 120, "data", "")
    d.text(380, 108, "blackboard", 13, weight="600")
    for i, (t, st) in enumerate((("T1 report", "done"), ("T5 repro", "done"), ("T6 repro", "claimed"),
                                 ("T7 estimate", "open"))):
        d.text(380, 130 + i * 18, f"{t} · {st}", 11, MUTED)
    for x, y, n, sk in ((40, 40, "triager", "skill: report"), (40, 170, "reproducer", "skill: repro"),
                        (580, 100, "estimator", "skill: estimate")):
        d.box(x, y, 140, 56, "llm", n, sk, size=12)
    d.arrow([(180, 68), (248, 110)], "normal", head=True)
    d.arrow([(180, 198), (248, 180)], "normal", head=True)
    d.arrow([(578, 128), (512, 146)], "normal", head=True)
    d.text(232, 64, "claim · post", 10, MUTED, "start")
    d.text(650, 174, "claim · post", 10, MUTED)
    d.box(250, 228, 260, 40, "code", "dedupe · task cap · tick budget", "the only global controls", size=12)
    d.text(640, 220, "no controller", 12, "#B5562E", weight="600")
    d.text(640, 236, "behaviour emerges", 11, "#B5562E")
    d.legend(KEY)
    return d.save()


def memory_tiers():
    d = Diagram("memory_tiers", 760, 300, "Memory tiers structure",
                "Each user turn enters bounded working memory. An extractor model proposes memory candidates. A code "
                "write policy sends stable, confident facts to semantic memory, transient facts to episodic memory, "
                "and drops the rest. Long-term tiers persist to disk; recall is by tag.")
    d.box(16, 110, 84, 52, "data", "User turn")
    d.arrow([(100, 136), (128, 136)])
    d.box(130, 30, 150, 52, "code", "working memory", "last N turns, verbatim", size=12)
    d.arrow([(115, 136), (115, 56), (128, 56)], head=True)
    d.box(130, 110, 150, 52, "llm", "extract", "candidate facts")
    d.arrow([(280, 136), (318, 136)])
    d.diamond(350, 136, 32, "policy")
    d.text(350, 190, "code decides", 10, MUTED)
    d.arrow([(382, 136), (420, 136), (420, 60), (468, 60)], "ok", "stable", (430, 52), "start")
    d.box(470, 34, 170, 52, "data", "semantic memory", "facts + history + source", size=12)
    d.arrow([(420, 136), (468, 136)], "normal", "transient", (444, 128))
    d.box(470, 110, 170, 52, "data", "episodic memory", "session notes", size=12)
    d.arrow([(350, 168), (350, 222), (468, 222)], "fail", "low confidence", (360, 238), "start")
    d.box(470, 200, 170, 44, "code", "dropped", size=12)
    d.box(660, 34, 84, 128, "data", "JSON", "on disk")
    d.arrow([(640, 60), (658, 60)], "muted", head=False)
    d.arrow([(640, 136), (658, 136)], "muted", head=False)
    d.text(555, 274, "recall by tag · newer value supersedes, history kept", 10, MUTED)
    d.legend(KEY)
    return d.save()


def context_management():
    d = Diagram("context_management", 760, 326, "Context management structure",
                "Each model call's context is assembled under a token budget in priority order: pinned system rules "
                "and task, a one-line tool index with full docs only on request, a running summary of old turns plus "
                "recent turns verbatim, and reference documents by relevance until the budget is reached.")
    sections = [("pin", "system rules + task", "always, verbatim", "code"),
                ("disclose", "tool index", "full docs on request", "code"),
                ("compact", "summary + recent turns", "old turns summarised", "llm"),
                ("evict", "reference docs", "by relevance, to budget", "code")]
    for i, (lever, title, sub, kind) in enumerate(sections):
        y = 24 + i * 58
        d.text(70, y + 30, lever, 12, "#6B7F5E", weight="700")
        d.box(120, y, 220, 48, kind, title, sub, size=12)
        d.arrow([(340, y + 24), (420, y + 24)])
    d.box(422, 24, 150, 252, "data", "")
    d.text(497, 50, "prompt", 13, weight="600")
    d.text(497, 70, "≤ budget", 11, MUTED)
    for k, (lbl, h) in enumerate((("pinned", 26), ("tools", 26), ("summary", 22), ("recent", 46), ("docs", 34))):
        pass
    y = 84
    for lbl, h, fill in (("pinned", 30, "#E7EDE1"), ("tools", 28, "#E7EDE1"), ("summary", 24, "#F6E3D3"),
                         ("recent", 50, "#F6E3D3"), ("docs", 36, "#FFFDF8")):
        d.parts.append(f'  <rect x="440" y="{y}" width="114" height="{h}" rx="4" fill="{fill}" stroke="#8C7B70"/>')
        d.text(497, y + h / 2 + 4, lbl, 10)
        y += h + 4
    d.box(600, 100, 144, 70, "code", "report", "kept · compacted · evicted", size=12)
    d.arrow([(572, 135), (598, 135)])
    d.text(380, 296, "naive prompt 924 tokens → managed 190–285 tokens in the example", 11, MUTED)
    d.legend("Terracotta = model call (summarizer) · Sage = deterministic code · Dashed = data")
    return d.save()


def eval_harness():
    d = Diagram("eval_harness", 760, 280, "Eval harness structure",
                "A fixed case set runs through two versions of the system. Deterministic and model-judge scorers "
                "produce per-case scores. Reports aggregate by scorer and tag. A per-case comparison finds fixes and "
                "regressions, and a gate decides ship or block, blocking on any critical regression.")
    d.box(16, 100, 100, 60, "data", "cases", "input · tags")
    d.arrow([(116, 116), (158, 76)])
    d.arrow([(116, 144), (158, 184)])
    d.box(160, 50, 120, 52, "plain", "system v1", size=12)
    d.box(160, 158, 120, 52, "plain", "system v2", size=12)
    d.arrow([(280, 76), (318, 110)])
    d.arrow([(280, 184), (318, 150)])
    d.box(320, 96, 140, 68, "code", "scorers", "exact · budget · judge")
    d.arrow([(460, 130), (496, 130)])
    d.box(498, 96, 110, 68, "data", "reports", "mean · by tag · fails")
    d.arrow([(608, 130), (638, 130)])
    d.diamond(672, 130, 32, "gate")
    d.text(672, 186, "per-case diff:", 10, MUTED)
    d.text(672, 199, "critical regression", 10, MUTED)
    d.text(672, 212, "→ BLOCK", 10, "#B5562E", weight="700")
    d.text(390, 232, "LLM-judge scorers use a different model from the system under test", 10, MUTED)
    d.legend("Terracotta = model call · Sage = deterministic code · Plain outline = system under test · Dashed = data")
    return d.save()


def coding_team():
    d = Diagram("coding_team", 760, 360, "Coding-team capstone architecture",
                "A tech lead supervises a dev team and a QA team. The dev team's developer is a tool-use loop whose "
                "prompts are assembled by a context manager under a token budget. The QA team runs a critic-reviewer "
                "loop with its own tools and calls back to the developer to fix findings. Only summaries reach the "
                "tech lead.")
    d.tag(380, 18, "#12 SUPERVISOR")
    d.box(300, 26, 160, 50, "llm", "tech lead", "summaries only")
    d.tag(170, 100, "#13 HIERARCHICAL TEAMS")
    d.arrow([(340, 76), (200, 116)])
    d.arrow([(420, 76), (560, 116)])
    d.box(120, 118, 160, 46, "llm", "dev lead", size=12)
    d.box(480, 118, 160, 46, "llm", "qa lead", size=12)
    d.arrow([(200, 164), (200, 190)])
    d.arrow([(560, 164), (560, 190)])
    d.box(100, 192, 200, 60, "llm", "developer", "tool-use loop (#9)")
    d.box(460, 192, 200, 60, "llm", "reviewer", "critic–reviewer loop (#16)")
    d.arrow([(460, 222), (302, 222)], "loop", "findings → fix", (380, 214))
    d.box(40, 280, 150, 44, "code", "context manager", "#20 · budget 300", size=12)
    d.arrow([(140, 252), (115, 278)], "muted")
    d.box(230, 280, 180, 44, "data", "virtual repo", "read · write · run_tests", size=12)
    d.arrow([(240, 252), (290, 278)])
    d.box(470, 280, 190, 44, "code", "run tests + checks", "QA's own tools", size=12)
    d.arrow([(560, 252), (560, 278)])
    d.legend(KEY)
    return d.save()


ALL = [react, plan_and_execute, reflection, tool_use_loop, agentic_rag, guardrailed_generation, deep_research,
       supervisor, hierarchical_teams, sequential_handoffs, debate, critic_reviewer, human_in_the_loop, swarm,
       memory_tiers, context_management, eval_harness, coding_team]

if __name__ == "__main__":
    for fn in ALL:
        print("wrote", fn().name)

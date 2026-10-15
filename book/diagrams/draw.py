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


ALL = [react, plan_and_execute, reflection, tool_use_loop, agentic_rag, guardrailed_generation, deep_research]

if __name__ == "__main__":
    for fn in ALL:
        print("wrote", fn().name)

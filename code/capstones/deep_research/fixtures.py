"""Fixtures for the deep-research capstone: the corpus and the mock models' behaviour."""

from __future__ import annotations

import json

from agentkit import MockLLM, rules

CORPUS = {
    "src-pricing": "Managed Postgres sized for 500 GB (8 vCPU, 64 GB RAM) lists at about $1,450 per month including "
                   "backups. Equivalent self-managed VMs cost about $900 per month, plus an estimated 10 engineer-hours "
                   "per month of operations.",
    "src-migration": "Migrating with logical replication needs about 5-15 minutes of write downtime at cutover. A "
                     "dump-and-restore of 500 GB takes several hours of downtime.",
    "src-compliance": "The managed service offers EU-region hosting, is SOC 2 Type II and ISO 27001 certified, and "
                      "data residency can be pinned to eu-west.",
    "src-portability": "Leaving the managed service uses standard pg_dump exports or logical replication out, the "
                       "same tools used to arrive.",
    "src-replicas": "Read replicas use asynchronous replication with lag typically under one second.",
}

QUESTION = ("Should we move our 500 GB Postgres to the managed service? "
            "Cover cost, migration downtime, compliance and lock-in.")
FOLLOW_UP = "For the Postgres move, what downtime and cost should we expect?"
TOPICS = {"cost": "src-pricing", "downtime": "src-migration", "compliance": "src-compliance", "lockin": "src-portability"}


def _step(i, topic, q):
    return {"id": f"q{i}", "action": "research", "args": {"topic": topic, "question": q}, "purpose": topic}


PLAN_1 = [
    _step(1, "cost", "What does the managed service cost compared with self-managed?"),
    _step(2, "downtime", "How much downtime does migrating 500 GB need?"),
    _step(3, "compliance", "Does the managed service meet our EU compliance needs?"),
    _step(4, "lockin", "What exit fees or contract lock-in apply?"),
]
REPLAN = [_step(5, "lockin", "How portable is our data if we leave the managed service?")]
PLAN_FOLLOW_UP = [PLAN_1[1], PLAN_1[0]]


def make_planner() -> MockLLM:
    return MockLLM(rules([
        (lambda p, s: p.startswith("REPLAN") and "exit fees" in p, json.dumps(REPLAN)),
        (lambda p, s: p.startswith("PLAN") and "what downtime and cost" in p, json.dumps(PLAN_FOLLOW_UP)),
        (lambda p, s: p.startswith("PLAN"), json.dumps(PLAN_1)),
    ]), name="planner")


QUERIES = {
    "cost compared": "managed postgres month cost self-managed",
    "downtime does migrating": "migration cutover downtime logical replication",
    "EU compliance": "EU region residency SOC certified",
    "exit fees": "vendor lock-in exit fee",
    "portable": "leaving export pg_dump replication",
}
FINDINGS = {
    "src-pricing": "Managed costs about $1,450/month vs about $900/month self-managed plus an estimated 10 "
                   "engineer-hours/month of operations [src-pricing].",
    "src-migration": "Logical-replication cutover needs about 5-15 minutes of write downtime; dump-and-restore of "
                     "500 GB takes hours [src-migration].",
    "src-compliance": "EU-region hosting, SOC 2 Type II and ISO 27001 certified; residency can be pinned to eu-west "
                      "[src-compliance].",
    "src-portability": "Leaving uses standard pg_dump or logical replication out, the same tools as arriving "
                       "[src-portability].",
}


def _query(prompt, system):
    q = prompt.split("QUERY for: ", 1)[1].split("\n", 1)[0]
    if "exit fees" in q and "Previous queries: []" not in prompt:
        return "contract termination penalty"
    return next(v for k, v in QUERIES.items() if k in q)


def _grade(prompt, system):
    q = prompt.split("GRADE passages for: ", 1)[1].split("\n", 1)[0]
    want = {"cost": "src-pricing", "downtime": "src-migration", "EU": "src-compliance", "portable": "src-portability"}
    hit = next((src for key, src in want.items() if key in q and f"[{src}]" in prompt), None)
    if hit:
        return json.dumps({"relevant": [hit], "sufficient": True, "missing": ""})
    return json.dumps({"relevant": [], "sufficient": False, "missing": "nothing about exit fees or contract terms"})


def _answer(prompt, system):
    return next(f for src, f in FINDINGS.items() if f"[{src}]" in prompt.split("Question:")[0])


def make_rag_llm() -> MockLLM:
    return MockLLM(rules([
        (lambda p, s: p.startswith("QUERY"), _query),
        (lambda p, s: p.startswith("GRADE"), _grade),
        (lambda p, s: p.startswith("ANSWER using"), _answer),
    ]), name="retrieval-agent", price=(0.25, 1.25))


COST = ("Cost: managed runs about $1,450/month versus about $900/month self-managed plus an estimated 10 "
        "engineer-hours/month of operations [src-pricing].")
COMPLIANCE = "Compliance: EU-region hosting with SOC 2 Type II and ISO 27001, pinned to eu-west [src-compliance]."
LOCKIN = "Lock-in: low, because leaving uses pg_dump or logical replication, the same tools as arriving [src-portability]."
DOWNTIME_BAD = "Downtime: logical replication makes the move near-zero downtime."
DOWNTIME_OK = ("Downtime: plan for 5-15 minutes of write downtime at cutover with logical replication; "
               "dump-and-restore would take hours [src-migration].")
UNCERTAIN = ("Uncertainty: the operations-hours figure is the vendor's estimate, not our measurement; check it "
             "against our on-call logs.")
HEAD = "Recommendation: move, using logical replication and a scheduled cutover window."

DRAFT_1 = " ".join([HEAD, COST, DOWNTIME_BAD, COMPLIANCE, LOCKIN])
DRAFT_2 = " ".join([HEAD, COST, DOWNTIME_OK, COMPLIANCE, LOCKIN])
DRAFT_3 = " ".join([HEAD, COST, DOWNTIME_OK, COMPLIANCE, LOCKIN, UNCERTAIN])
FOLLOW_UP_ANSWER = " ".join([DOWNTIME_OK, COST, UNCERTAIN])


def make_writer() -> MockLLM:
    return MockLLM(rules([
        (lambda p, s: "what downtime and cost" in p and "CRITIQUE" in p, "NO ISSUES"),
        (lambda p, s: "what downtime and cost" in p, FOLLOW_UP_ANSWER),
        (lambda p, s: p.startswith("WRITE:") and "REVISE your previous draft" in p, DRAFT_3),
        (lambda p, s: "CRITIQUE your answer" in p and "near-zero" in p,
         "Overclaim: 'near-zero downtime' is not in the findings, which say about 5-15 minutes of write "
         "downtime [src-migration]. Replace it and cite."),
        (lambda p, s: "CRITIQUE your answer" in p, "NO ISSUES"),
        (lambda p, s: "REVISE the answer" in p, DRAFT_2),
        (lambda p, s: p.startswith("TASK:"), DRAFT_1),
    ]), name="writer")


def _judge(prompt, system):
    draft = prompt.split("Draft:\n", 1)[1]
    if "estimate, not our measurement" not in draft and "vendor's estimate" not in draft:
        return json.dumps({"pass": False, "feedback": [
            "State that the operations-hours figure is a vendor estimate we have not measured"]})
    return json.dumps({"pass": True, "feedback": []})


def make_evaluator() -> MockLLM:
    return MockLLM(_judge, name="evaluator")

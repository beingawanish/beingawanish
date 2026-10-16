"""New-content layer for the Python study guide, applied last by guides/guide.py load().

Inserts Chapter 8, "Python for AI Applications" (the fragment in ai_chapter.html, next to
this file), and renumbers the old Chapter 8 (Capstone Project and Back Matter) as Chapter 9:
its heading, anchor, TOC entry, code paths and every mention of it. The new chapter also
gets TOC entries, intro mentions and a coverage-checklist entry.

Every edit asserts how many times its target occurs, so a change to the source fails loudly
instead of silently skipping an edit.
"""

import hashlib
import inspect
import json
import pathlib
import re

HERE = pathlib.Path(inspect.currentframe().f_code.co_filename).resolve().parent
FRAGMENT = HERE / "ai_chapter.html"

OLD_ID = "chapter-8-capstone-project-and-back-matter"
NEW_ID = "chapter-9-capstone-project-and-back-matter"
OLD_TITLE = "Chapter 8: Capstone Project and Back Matter"
NEW_TITLE = "Chapter 9: Capstone Project and Back Matter"
AI_ID = "chapter-8-python-for-ai-applications"
AI_TITLE = "Chapter 8: Python for AI Applications"


def _replace(text: str, old: str, new: str, count: int = 1) -> str:
    found = text.count(old)
    assert found == count, f"additions.py: expected {count} x {old[:70]!r}, found {found}"
    return text.replace(old, new)


def _adopt_rewrites(text: str, markers: tuple[str, ...], expected: int) -> str:
    """Swap in the rewrites/ version of the prose blocks this layer is about to edit.

    guide.py applies rewrites/chNN.json after this layer, keyed by a hash of the original
    block. Editing a block here changes that hash, so its rewrite would silently stop
    applying. Taking the rewrite first keeps the reviewed prose and then edits it.
    """
    rewrites: dict[str, str] = {}
    for f in sorted((HERE / "rewrites").glob("ch*.json")):
        rewrites.update(json.loads(f.read_text(encoding="utf-8")))
    lines, adopted = text.split("\n"), 0
    for i, line in enumerate(lines):
        m = re.fullmatch(r"<p>(.*)</p>", line)
        if m and any(k in line for k in markers):
            new = rewrites.get(hashlib.sha1(m.group(1).encode()).hexdigest()[:10])
            if new is not None:
                lines[i], adopted = f"<p>{new}</p>", adopted + 1
    assert adopted == expected, f"additions.py: adopted {adopted} rewritten blocks, expected {expected}"
    return "\n".join(lines)


def _toc_entries(fragment: str) -> str:
    """TOC <li> for the new chapter: the h1 with a nested list of its h2s."""
    h2s = re.findall(r'^<h2 id="([^"]+)">(.*)</h2>$', fragment, flags=re.M)
    assert len(h2s) == 12, f"additions.py: expected 12 h2 sections in ai_chapter.html, found {len(h2s)}"
    items = [f'<li><a href="#{i}" id="toc-{i}">{t}</a></li>' for i, t in h2s]
    return (f'<li><a href="#{AI_ID}" id="toc-{AI_ID}">{AI_TITLE}</a> <ul> '
            + "\n".join(items) + "\n</ul></li>\n")


def apply(text: str) -> str:
    fragment = FRAGMENT.read_text(encoding="utf-8").rstrip("\n") + "\n"
    assert f'<h1 id="{AI_ID}">{AI_TITLE}</h1>' in fragment, "additions.py: fragment h1 missing"

    # 0. Blocks edited below that also have a reviewed rewrite: take the rewrite first.
    text = _adopt_rewrites(text, ("code/ch08", "Chapter 7 is the testing and concurrency chapter."), 3)

    # 1. Old Chapter 8 -> Chapter 9, before the new chapter (which uses code/ch08) goes in.
    anchor_and_h1 = f'<p><a id="ch08"></a></p>\n<h1 id="{OLD_ID}">{OLD_TITLE}</h1>'
    text = _replace(text, anchor_and_h1, f'<p><a id="ch09"></a></p>\n<h1 id="{NEW_ID}">{NEW_TITLE}</h1>')
    text = _replace(text, "code/ch08", "code/ch09", count=7)          # capstone file paths
    text = _replace(text, "The capstone in Chapter 8 ties", "The capstone in Chapter 9 ties")

    # 2. TOC: new chapter entry, then the renumbered capstone entry.
    old_toc = f'<li><a href="#{OLD_ID}" id="toc-{OLD_ID}">{OLD_TITLE}</a>'
    text = _replace(text, old_toc,
                    _toc_entries(fragment) + f'<li><a href="#{NEW_ID}" id="toc-{NEW_ID}">{NEW_TITLE}</a>')

    # 3. Insert the chapter immediately before the capstone's anchor + heading.
    text = _replace(text, '<p><a id="ch09"></a></p>\n', fragment + '<p><a id="ch09"></a></p>\n')

    # 4. Intro and back matter that describe the guide's contents.
    text = _replace(
        text,
        "errors, testing, and concurrency — and ends with a working project you build yourself.",
        "errors, testing, and concurrency. It then puts all of that to work in AI applications"
        " built on a language model's API — and ends with a working project you build yourself.")
    text = _replace(
        text,
        "and reason about threads, processes, and async code at the level interviews expect.</p>",
        "and reason about threads, processes, and async code at the level interviews expect."
        " You will also call Claude from Python with retries, streaming, validated structured"
        " output, tools and concurrency, retrieve documents with vector similarity, and test"
        " model-calling code without a network.</p>")
    text = _replace(text, "Chapter 7 is the testing and concurrency chapter.</p>",
                    "Chapter 7 is the testing and concurrency chapter. Chapter 8 applies them to AI"
                    " applications, and Chapter 9 is the capstone.</p>")
    checklist_tail = "<li>eval / pickle safety</li>\n</ul>\n"
    text = _replace(text, checklist_tail, checklist_tail + (
        "<p><strong>10. Python for AI applications — ✓ Chapter 8</strong></p>\n<ul>\n"
        "<li>HTTP/JSON APIs / timeouts / retries with backoff and jitter / idempotency</li>\n"
        "<li>anthropic SDK: messages, system, max_tokens, content blocks, usage, typed errors</li>\n"
        "<li>streaming / structured output with validation / strict tools</li>\n"
        "<li>tool use and the agent loop with a step budget</li>\n"
        "<li>asyncio concurrency with Semaphore and TaskGroup / rate limits</li>\n"
        "<li>NumPy, cosine similarity, retrieval (RAG) / chunking / token counting / JSONL / batching</li>\n"
        "<li>fake clients, recorded fixtures, evals / secrets, prompt injection, logging, cost control</li>\n"
        "</ul>\n"))
    return text

#!/usr/bin/env python3
"""Assemble the book: Markdown chapters -> one HTML file + one combined Markdown file.

    python3 book/build.py                 # writes dist/agentic-design-patterns.{html,md}
    python3 book/build.py --out NAME      # custom output basename

Standard library only. The Markdown subset is the one this book uses: ATX headings,
paragraphs, lists, pipe tables, fenced code, blockquotes, images (SVG figures are
inlined so they stay editable in the output), links, `code`, **bold**, *italic*.

Cross-links between chapters (`../part-2-single-agent/07-plan-and-execute.md`) become
in-page anchors. Links to chapters not yet written render as "planned" references,
so the HTML never contains a dead link.
"""

from __future__ import annotations

import html
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BOOK = ROOT / "book"
DIST = ROOT / "dist"

TITLE = "Agentic Design Patterns"
SUBTITLE = "A pattern catalog for systems built on language models — with runnable code"

# (section id, section title, [(path relative to book/, nav label)])
CATALOG = [
    ("front", "Front matter", [("00-front/preface.md", "Preface — How to read this book")]),
    ("part-1", "Part 1 — Workflow patterns", [
        ("part-1-workflow/00-part-intro.md", "Introduction"),
        ("part-1-workflow/01-prompt-chaining.md", "1. Prompt chaining"),
        ("part-1-workflow/02-routing.md", "2. Routing"),
        ("part-1-workflow/03-parallelization.md", "3. Parallelization"),
        ("part-1-workflow/04-orchestrator-workers.md", "4. Orchestrator–workers"),
        ("part-1-workflow/05-evaluator-optimizer.md", "5. Evaluator–optimizer"),
    ]),
    ("part-2", "Part 2 — Single-agent reasoning", [
        ("part-2-single-agent/00-part-intro.md", "Introduction"),
        ("part-2-single-agent/06-react.md", "6. ReAct"),
        ("part-2-single-agent/07-plan-and-execute.md", "7. Plan-and-execute"),
        ("part-2-single-agent/08-reflection.md", "8. Reflection"),
        ("part-2-single-agent/09-tool-use-loop.md", "9. Tool-use loop"),
        ("part-2-single-agent/10-agentic-rag.md", "10. Agentic RAG"),
        ("part-2-single-agent/11-guardrailed-generation.md", "11. Guardrailed generation"),
    ]),
    ("part-3", "Part 3 — Multi-agent coordination", [
        ("part-3-multi-agent/00-part-intro.md", "Introduction"),
        ("part-3-multi-agent/12-supervisor.md", "12. Supervisor"),
        ("part-3-multi-agent/13-hierarchical-teams.md", "13. Hierarchical teams"),
        ("part-3-multi-agent/14-sequential-handoffs.md", "14. Sequential handoffs"),
        ("part-3-multi-agent/15-debate.md", "15. Debate / peer critique"),
        ("part-3-multi-agent/16-critic-reviewer.md", "16. Critic–reviewer loop"),
        ("part-3-multi-agent/17-human-in-the-loop.md", "17. Human-in-the-loop"),
        ("part-3-multi-agent/18-swarm.md", "18. Swarm"),
    ]),
    ("part-4", "Part 4 — Cross-cutting", [
        ("part-4-cross-cutting/00-part-intro.md", "Introduction"),
        ("part-4-cross-cutting/19-memory-tiers.md", "19. Memory tiers"),
        ("part-4-cross-cutting/20-context-management.md", "20. Context management"),
        ("part-4-cross-cutting/21-eval-harness.md", "21. Eval harness"),
    ]),
    ("capstones", "Capstones", [
        ("capstones/support-triage.md", "1. Support triage"),
        ("capstones/deep-research.md", "2. Deep-research agent"),
        ("capstones/coding-team.md", "3. Multi-agent coding team"),
    ]),
    ("solutions", "Appendix — Exercise solutions", [
        (f"solutions/{n}", label) for n, label in [
            ("01-prompt-chaining.md", "1. Prompt chaining"), ("02-routing.md", "2. Routing"),
            ("03-parallelization.md", "3. Parallelization"), ("04-orchestrator-workers.md", "4. Orchestrator–workers"),
            ("05-evaluator-optimizer.md", "5. Evaluator–optimizer"), ("06-react.md", "6. ReAct"),
            ("07-plan-and-execute.md", "7. Plan-and-execute"), ("08-reflection.md", "8. Reflection"),
            ("09-tool-use-loop.md", "9. Tool-use loop"), ("10-agentic-rag.md", "10. Agentic RAG"),
            ("11-guardrailed-generation.md", "11. Guardrailed generation"), ("12-supervisor.md", "12. Supervisor"),
            ("13-hierarchical-teams.md", "13. Hierarchical teams"), ("14-sequential-handoffs.md", "14. Sequential handoffs"),
            ("15-debate.md", "15. Debate"), ("16-critic-reviewer.md", "16. Critic–reviewer"),
            ("17-human-in-the-loop.md", "17. Human-in-the-loop"), ("18-swarm.md", "18. Swarm"),
            ("19-memory-tiers.md", "19. Memory tiers"), ("20-context-management.md", "20. Context management"),
            ("21-eval-harness.md", "21. Eval harness"),
        ]
    ]),
]


def chapter_id(rel: str) -> str:
    folder, name = rel.split("/")
    stem = re.sub(r"^\d+-", "", name[:-3])
    if folder == "solutions":
        return f"solution-{stem}"
    if folder == "capstones":
        return f"capstone-{stem}"
    if stem == "part-intro":
        return folder.split("-")[0] + "-" + folder.split("-")[1]  # part-1 ...
    return stem


def slugify(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", text).strip("-")


# --- Markdown -> HTML (the subset this book uses) ------------------------------------

class Renderer:
    def __init__(self, rel: str, existing: set[str]) -> None:
        self.rel, self.existing = rel, existing
        self.cid = chapter_id(rel)
        self.headings: list[tuple[int, str, str]] = []

    def resolve(self, href: str) -> tuple[str | None, bool]:
        """Return (href, exists). Chapter .md links become #anchors."""
        if re.match(r"^[a-z]+:", href) or href.startswith("#"):
            return href, True
        target = (BOOK / pathlib.Path(self.rel).parent / href).resolve()
        try:
            rel = target.relative_to(BOOK).as_posix()
        except ValueError:
            return None, False
        if rel.endswith(".md"):
            return f"#{chapter_id(rel)}", rel in self.existing
        return None, False

    def inline(self, text: str) -> str:
        codes: list[str] = []

        def stash(m):
            codes.append(f"<code>{html.escape(m.group(1))}</code>")
            return f"\x00{len(codes) - 1}\x00"

        text = re.sub(r"`([^`]+)`", stash, text)
        text = html.escape(text, quote=False)

        def link(m):
            label, href = m.group(1), html.unescape(m.group(2))
            url, ok = self.resolve(href)
            if url and ok:
                ext = ' rel="noopener"' if url.startswith("http") else ""
                return f'<a href="{html.escape(url)}"{ext}>{label}</a>'
            return f'<span class="xref-planned" title="Chapter not yet written">{label}</span>'

        text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
        text = text.replace("→", "→")
        return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)

    def figure(self, alt: str, src: str) -> str:
        path = (BOOK / pathlib.Path(self.rel).parent / src).resolve()
        if path.suffix == ".svg" and path.exists():
            svg = path.read_text().strip()
            return f'<figure class="diagram">{svg}<figcaption>{html.escape(alt)}</figcaption></figure>'
        return f'<figure><img src="{html.escape(src)}" alt="{html.escape(alt)}"><figcaption>{html.escape(alt)}</figcaption></figure>'

    def render(self, md: str) -> str:
        lines = md.splitlines()
        out: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            if line.lstrip().startswith("<!--"):
                while "-->" not in lines[i]:
                    i += 1
                i += 1
                continue
            if line.startswith("```"):
                lang = line[3:].strip()
                buf = []
                i += 1
                while i < len(lines) and not lines[i].startswith("```"):
                    buf.append(lines[i])
                    i += 1
                i += 1
                cls = "console" if lang == "text" else ("cmd" if not lang else f"lang-{lang}")
                out.append(f'<pre class="{cls}"><code>{html.escape(chr(10).join(buf))}</code></pre>')
                continue
            m = re.match(r"^(#{1,4})\s+(.*)$", line)
            if m:
                level, text = len(m.group(1)), m.group(2).strip()
                hid = f"{self.cid}--title" if level == 1 else f"{self.cid}--{slugify(text)}"
                self.headings.append((level, hid, text))
                out.append(f'<h{level} id="{hid}">{self.inline(text)}</h{level}>')
                i += 1
                continue
            m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", line)
            if m:
                out.append(self.figure(m.group(1), m.group(2)))
                i += 1
                continue
            if line.startswith(">"):
                buf = []
                while i < len(lines) and lines[i].startswith(">"):
                    buf.append(lines[i].lstrip(">").strip())
                    i += 1
                out.append("<blockquote><p>" + "<br>".join(self.inline(b) for b in buf if b) + "</p></blockquote>")
                continue
            if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|\s*$", lines[i + 1]):
                head = self._cells(line)
                i += 2
                rows = []
                while i < len(lines) and lines[i].startswith("|"):
                    rows.append(self._cells(lines[i]))
                    i += 1
                th = "".join(f"<th>{self.inline(c)}</th>" for c in head)
                trs = "".join("<tr>" + "".join(f"<td>{self.inline(c)}</td>" for c in r) + "</tr>" for r in rows)
                out.append(f'<div class="table-wrap"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>')
                continue
            if re.match(r"^(\s*)([-*]|\d+\.)\s+", line):
                ordered = bool(re.match(r"^\s*\d+\.", line))
                items: list[str] = []
                while i < len(lines) and lines[i].strip():
                    m = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*)$", lines[i])
                    if m:
                        items.append(m.group(1))
                    else:
                        items[-1] += " " + lines[i].strip()
                    i += 1
                tag = "ol" if ordered else "ul"
                out.append(f"<{tag}>" + "".join(f"<li>{self.inline(it)}</li>" for it in items) + f"</{tag}>")
                continue
            buf = []
            while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,4}\s|```|>|\||\s*[-*]\s|\s*\d+\.\s|!\[|<!--)", lines[i]):
                buf.append(lines[i].strip())
                i += 1
            if buf:
                out.append(f"<p>{self.inline(' '.join(buf))}</p>")
            else:
                i += 1
        return "\n".join(out)

    @staticmethod
    def _cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]


# --- Assembly --------------------------------------------------------------------------

CSS = r"""
:root{--paper:#FBF5EA;--card:#FFFDF8;--ink:#3B2F2A;--muted:#7A6A5E;--rule:#E6D9C6;--accent:#B5562E;
--accent-soft:#F6E3D3;--sage:#6B7F5E;--sage-soft:#E7EDE1;--ochre:#B88A1E;--code-bg:#F3EADB;--console-bg:#2E2621;--console-ink:#F3E9DA;
--serif:'Source Serif 4',Georgia,'Iowan Old Style',serif;--sans:'Source Sans 3','Helvetica Neue',Arial,sans-serif;--mono:'JetBrains Mono',ui-monospace,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#221C18;--card:#2B2420;--ink:#EFE4D4;--muted:#B9A897;--rule:#43382F;
--accent:#E08A5F;--accent-soft:#3D2C22;--sage:#A3B795;--sage-soft:#2F3529;--code-bg:#332A24;--console-bg:#16110E}}
:root[data-theme="dark"]{--paper:#221C18;--card:#2B2420;--ink:#EFE4D4;--muted:#B9A897;--rule:#43382F;--accent:#E08A5F;--accent-soft:#3D2C22;
--sage:#A3B795;--sage-soft:#2F3529;--code-bg:#332A24;--console-bg:#16110E}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:16px}
body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.65 var(--serif);-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:2px}
.layout{display:grid;grid-template-columns:290px minmax(0,1fr);max-width:1240px;margin:0 auto}
nav.toc{position:sticky;top:0;height:100vh;overflow:auto;padding:28px 18px 40px 24px;border-right:1px solid var(--rule);font:14px/1.45 var(--sans)}
nav.toc .brand{font:600 18px/1.25 var(--serif);margin:0 0 4px}
nav.toc .brand a{color:var(--ink);text-decoration:none}
nav.toc .sub{color:var(--muted);font-size:12.5px;margin:0 0 18px}
nav.toc h2{font:700 11px/1.4 var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--sage);margin:20px 0 6px}
nav.toc ol{list-style:none;margin:0;padding:0}
nav.toc li{margin:1px 0}
nav.toc a,nav.toc span{display:block;padding:3px 8px;border-radius:6px;color:var(--ink);text-decoration:none}
nav.toc a:hover{background:var(--accent-soft)}
nav.toc a.active{background:var(--accent-soft);color:var(--accent);font-weight:600}
nav.toc span.planned{color:var(--muted);opacity:.7}
nav.toc span.planned::after{content:" · planned";font-size:11px}
.theme-btn{margin-top:22px;font:13px var(--sans);background:var(--card);color:var(--ink);border:1px solid var(--rule);border-radius:8px;padding:6px 10px;cursor:pointer}
main{padding:40px 56px 120px;min-width:0}
.cover{padding:56px 0 40px;border-bottom:1px solid var(--rule);margin-bottom:24px}
.cover h1{font-size:52px;line-height:1.08;margin:0 0 14px;letter-spacing:-.01em}
.cover p.lede{font-size:20px;color:var(--muted);max-width:40em;margin:0}
.cover .meta{font:14px var(--sans);color:var(--muted);margin-top:22px}
.status{font:13px/1.5 var(--sans);background:var(--sage-soft);border:1px solid var(--sage);border-radius:10px;padding:12px 16px;margin-top:22px;max-width:44em}
section.chapter{max-width:46em;padding-top:28px;margin-top:28px;border-top:1px solid var(--rule)}
section.part-title{max-width:46em;margin-top:56px;padding:28px 0 8px;border-top:3px double var(--rule)}
.part-name{font:700 40px/1.15 var(--serif);margin:6px 0 0;color:var(--ink)}
h1,h2,h3,h4{font-family:var(--serif);line-height:1.25;color:var(--ink)}
section.chapter>h1{font-size:36px;margin:8px 0 16px}
h2{font-size:24px;margin:40px 0 10px;padding-bottom:4px;border-bottom:1px solid var(--rule)}
h3{font-size:19px;margin:28px 0 8px}
.kicker{font:700 12px/1 var(--sans);letter-spacing:.1em;text-transform:uppercase;color:var(--accent)}
blockquote{margin:16px 0 20px;padding:14px 18px;background:var(--accent-soft);border-left:4px solid var(--accent);border-radius:0 10px 10px 0}
blockquote p{margin:0}
code{font:0.86em/1.4 var(--mono);background:var(--code-bg);padding:1px 5px;border-radius:4px;overflow-wrap:anywhere}
pre{background:var(--code-bg);border-radius:10px;padding:14px 16px;overflow:auto;font:13.5px/1.55 var(--mono)}
pre code{background:none;padding:0;font:inherit}
pre.console{background:var(--console-bg);color:var(--console-ink)}
pre.cmd{background:var(--card);border:1px solid var(--rule)}
pre.cmd code::before{content:'$ ';color:var(--muted)}
.table-wrap{overflow-x:auto;margin:14px 0}
table{border-collapse:collapse;width:100%;font:15px/1.45 var(--sans)}
th,td{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px solid var(--rule)}
th{font-weight:700;background:var(--card)}
figure{margin:20px 0 24px}
figure.diagram svg{width:100%;height:auto;display:block;border-radius:12px;border:1px solid var(--rule)}
figcaption{font:13px var(--sans);color:var(--muted);margin-top:6px}
.xref-planned{border-bottom:1px dotted var(--muted);cursor:help}
.chapnav{display:flex;justify-content:space-between;gap:12px;margin-top:40px;font:14px var(--sans)}
.chapnav a{display:block;max-width:48%;padding:10px 14px;border:1px solid var(--rule);border-radius:10px;background:var(--card);text-decoration:none}
.chapnav .dir{display:block;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.menu-btn{display:none}
@media (max-width:900px){
 .layout{display:block}
 nav.toc{position:fixed;inset:0 25% 0 0;z-index:20;background:var(--paper);transform:translateX(-102%);transition:transform .2s;visibility:hidden}
 nav.toc.open{transform:none;visibility:visible;box-shadow:0 0 40px rgba(0,0,0,.2)}
 .menu-btn{display:inline-block;position:sticky;top:10px;z-index:10;margin:10px 16px 0;font:14px var(--sans);background:var(--card);color:var(--ink);border:1px solid var(--rule);border-radius:8px;padding:8px 12px}
 main{padding:12px 16px 80px}
 .cover h1{font-size:36px}
 body{font-size:16.5px}
}
@media print{
 @page{size:A4;margin:18mm 17mm 20mm}
 @page{@bottom-center{content:counter(page);font:9pt 'Source Sans 3',Arial,sans-serif;color:#7A6A5E}}
 :root{--paper:#fff;--card:#fff}
 body{font-size:10.5pt;line-height:1.5;background:#fff}
 nav.toc,.menu-btn,.theme-btn,.chapnav{display:none!important}
 .layout{display:block}
 main{padding:0}
 section.chapter,section.part-title{break-before:page;border-top:none;margin-top:0;padding-top:0;max-width:none}
 section.part-title{padding-top:38%;text-align:center}
 .part-name{font-size:30pt}
 .cover{break-after:page;border:none;padding-top:30%}
 h2,h3{break-after:avoid}
 figure,pre,table,blockquote{break-inside:avoid}
 pre{white-space:pre-wrap;word-break:break-word;font-size:8pt}
 pre.console{background:#F3EADB;color:#3B2F2A}
 a{color:inherit;text-decoration:none}
}
"""

JS = r"""
(function(){
 var nav=document.querySelector('nav.toc'),btn=document.querySelector('.menu-btn');
 if(btn){btn.addEventListener('click',function(){nav.classList.toggle('open')});}
 nav.addEventListener('click',function(e){if(e.target.tagName==='A'&&window.innerWidth<=900){nav.classList.remove('open')}});
 var t=document.querySelector('.theme-btn');
 try{var s=localStorage.getItem('adp-theme');if(s){document.documentElement.setAttribute('data-theme',s)}}catch(e){}
 if(t){t.addEventListener('click',function(){var d=document.documentElement,
   cur=d.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'),
   nxt=cur==='dark'?'light':'dark';d.setAttribute('data-theme',nxt);try{localStorage.setItem('adp-theme',nxt)}catch(e){}});}
 var links={};document.querySelectorAll('nav.toc a[href^="#"]').forEach(function(a){links[a.getAttribute('href').slice(1)]=a});
 var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){
   document.querySelectorAll('nav.toc a.active').forEach(function(x){x.classList.remove('active')});
   var a=links[e.target.id];if(a){a.classList.add('active')}}})},{rootMargin:'0px 0px -80% 0px'});
 document.querySelectorAll('section.chapter').forEach(function(s){io.observe(s)});
})();
"""


def build(out_name: str) -> tuple[pathlib.Path, pathlib.Path, list[str]]:
    existing = {rel for _, _, items in CATALOG for rel, _ in items if (BOOK / rel).exists()}
    order = [rel for _, _, items in CATALOG for rel, _ in items if rel in existing]
    sections_html, md_parts = [], []
    toc = []

    for sid, stitle, items in CATALOG:
        present = [(r, l) for r, l in items if r in existing]
        lis = []
        for rel, label in items:
            if rel in existing:
                lis.append(f'<li><a href="#{chapter_id(rel)}">{html.escape(label)}</a></li>')
            elif sid not in ("solutions",):
                lis.append(f'<li><span class="planned">{html.escape(label)}</span></li>')
        if lis:
            toc.append(f"<h2>{html.escape(stitle)}</h2><ol>{''.join(lis)}</ol>")
        if not present:
            continue
        if sid not in ("front",):
            head, _, name = stitle.partition(" — ")
            sections_html.append(f'<section class="part-title" id="sec-{sid}"><p class="kicker">{html.escape(head)}</p>'
                                 f'<p class="part-name">{html.escape(name or head)}</p></section>')
        md_parts.append(f"\n\n<!-- ===== {stitle} ===== -->\n")
        for rel, label in present:
            src = (BOOK / rel).read_text()
            r = Renderer(rel, existing)
            body = r.render(src)
            idx = order.index(rel)
            prev_rel = order[idx - 1] if idx > 0 else None
            next_rel = order[idx + 1] if idx + 1 < len(order) else None
            labels = {rr: ll for _, _, its in CATALOG for rr, ll in its}
            nav = '<div class="chapnav">'
            nav += (f'<a href="#{chapter_id(prev_rel)}"><span class="dir">← Previous</span>{html.escape(labels[prev_rel])}</a>'
                    if prev_rel else "<span></span>")
            nav += (f'<a href="#{chapter_id(next_rel)}" style="text-align:right"><span class="dir">Next →</span>'
                    f'{html.escape(labels[next_rel])}</a>' if next_rel else "<span></span>")
            nav += "</div>"
            kicker = f'<p class="kicker">{html.escape(stitle)}</p>'
            sections_html.append(f'<section class="chapter" id="{chapter_id(rel)}">{kicker}{body}{nav}</section>')
            md_parts.append(re.sub(r"\]\(\.\./diagrams/", "](../book/diagrams/", src))

    planned = sum(1 for _, _, items in CATALOG for rel, _ in items if rel not in existing and not rel.startswith("solutions"))
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{TITLE}</title>
<meta name="description" content="{SUBTITLE}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Source+Sans+3:wght@400;600;700&family=Source+Serif+4:ital,wght@0,400;0,600;0,700;1,400&display=swap">
<style>{CSS}</style>
</head>
<body>
<button class="menu-btn" type="button" aria-label="Open contents">☰ Contents</button>
<div class="layout">
<nav class="toc" aria-label="Table of contents">
<p class="brand"><a href="#top">{TITLE}</a></p>
<p class="sub">Pattern catalog · runnable code</p>
{''.join(toc)}
<button class="theme-btn" type="button">Toggle light / dark</button>
</nav>
<main id="top">
<header class="cover">
<p class="kicker">A pattern catalog</p>
<h1>{TITLE}</h1>
<p class="lede">{SUBTITLE}</p>
<p class="meta">21 patterns · 4 parts · 3 capstones · Python standard library, offline, deterministic</p>
{f'<p class="status">Pilot edition: {len([r for r in existing if not r.startswith("solutions")])} sections written, {planned} planned. Planned chapters appear greyed in the contents, and links to them are dotted.</p>' if planned else ''}
</header>
{''.join(sections_html)}
</main>
</div>
<script>{JS}</script>
</body>
</html>
"""
    ids = set(re.findall(r'id="([^"]+)"', page))
    broken = sorted({h for h in re.findall(r'href="#([^"]+)"', page) if h not in ids})
    if broken:
        raise SystemExit(f"broken internal links: {broken}")
    DIST.mkdir(exist_ok=True)
    html_path, md_path = DIST / f"{out_name}.html", DIST / f"{out_name}.md"
    html_path.write_text(page)
    md_path.write_text(f"# {TITLE}\n\n*{SUBTITLE}*\n" + "\n\n---\n\n".join(md_parts) + "\n")
    return html_path, md_path, order


def main(argv: list[str]) -> None:
    out = argv[argv.index("--out") + 1] if "--out" in argv else "agentic-design-patterns"
    h, m, order = build(out)
    print(f"wrote {h.relative_to(ROOT)} ({h.stat().st_size // 1024} KB), {m.relative_to(ROOT)}; {len(order)} sections")


if __name__ == "__main__":
    main(sys.argv[1:])

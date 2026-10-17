# Brief: deepening the Networking Mastery Guide

Source: `guides/net/source/networking-mastery-guide.original.html` (pandoc HTML, one block per line).
The existing modules explain each topic through analogies (street addresses, registered mail).
Readers say it is too basic: it lacks the **real mental model** — the actual machine, its state,
its numbers, and how it fails. Your work fixes that without deleting anything.

## Read first

1. Invoke the Skill tool with `lucid-technical-writing` and write in that voice.
2. Read the guide's intro (`id="networking-mastery-guide"` up to Module 01): audience, conventions
   ("on your Mac" commands, Python stdlib examples), and read your module(s) in full.
3. Copy the guide's conventions: section numbering, callouts, tables, code blocks, the SVG style
   (look at one SVG in your module: wrapper, `role="img"`, `<title>`/`<desc>`, palette, fonts).

## Content bar

Explain the mechanism the way a senior network engineer holds it in their head:
- **State and data structures**: what tables, timers, queues, counters exist, where (NIC, kernel,
  switch ASIC, resolver, browser), and how they change per packet/event.
- **Exact behaviour**: field values, sequence of events, RFC numbers where they settle a point.
  Prefer an annotated packet capture (`tcpdump -nn -v`/`tshark` style text) or `ss`/`ip`/`dig`/`curl -v`
  output to prose. Captures may be constructed but must be realistic and internally consistent
  (sequence numbers, lengths, flags, TTLs add up).
- **Numbers**: sizes, limits, defaults, typical latencies, worked calculations (e.g. BDP, MTU budget,
  cache hit math). Say which numbers are defaults that vary by OS/vendor.
- **Failure modes in production**: symptom → mechanism → how to prove it (exact commands) → fix.
- **2026 context**: how the topic shows up in cloud VPCs, Kubernetes, CDNs, QUIC/HTTP/3, zero trust,
  where relevant. No vendor marketing.
- **Interview depth**: questions a senior interviewer asks to separate memorisers from people who
  understand, each with a crisp answer.
Accuracy over breadth. If you are not sure a number or behaviour is right, leave it out or say it varies.
Runnable code: Python 3.13 stdlib only; run every snippet and paste real output. Shell commands must be
correct for macOS (the guide's platform) and, where different, Linux.

## Output

- HTML fragment, written as Markdown in your scratch folder and converted with
  `pandoc -f markdown-smart+gfm_auto_identifiers --wrap=none -t html` (default highlighting).
  Add SVGs after conversion if pandoc mangles them.
- One block per line (no hard wraps inside `<p>`, `<li>`, headings).
- Prefix every id you generate (headings, `cbN` code ids and their line anchors/hrefs, SVG ids)
  with your file's slug prefix, given in your assignment. No id may collide with the source guide.
- Don't edit the source, `guide.py`, or other agents' files. Work only in your own scratch subfolder.
  No git.

Report: files created, sections added, how you verified code/commands/captures, anything uncertain.

## Two kinds of assignment

**Deep dive for an existing module NN** → `guides/net/deep/NN.html`, id prefix `dNN-`.
It is appended to the end of module NN (before the next module). Start with
`<h2 id="dNN-deep-dive">Deep dive: …</h2>` (short intro saying what the analogy hid), then further h2
sections, each `<h2 id="dNN-…">Deep dive: …</h2>`, covering in order: the real mental model (with one new
SVG diagram of the actual mechanism), what the wire/kernel actually does (annotated capture or tool
output), by the numbers, production failure modes, 2026 context, senior interview questions. Don't
repeat what the module already says well; go under it. Roughly 3,000–5,000 words per module.

**New module NN** → `guides/net/new/NN-slug.html`, id prefix `mNN-`, h1 exactly
`<h1 id="module-NN--slug">Module NN — Title</h1>` followed by the same subtitle line style the other
modules use ("Networking Mastery Guide · Module N of 23"). Use the existing modules' nine-section shape
(why it matters, mental model, how it works, exact structure, realistic example, misconceptions,
interview Q&A, try it, code) and then the deep-dive sections above. Roughly 6,000–9,000 words.

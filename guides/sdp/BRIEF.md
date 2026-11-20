# Brief: deep dives for the System Design Patterns course

Source: `guides/sdp/source/system-design-patterns.original.html`. It is a single-page course app.
Each lesson lives in `<template id="t-<slug>">…</template>`. A pattern lesson has twelve numbered
h2 sections (The Incident, The Obvious Fixes, The Pattern, Walkthrough with Numbers, Trade-offs,
When Not to Use It, …, Related Patterns, TL;DR). The lessons are good at the "what" and "why".
Readers want the **deep-dive discussion** a senior engineer brings to a design review.

## Read first

1. Invoke the Skill tool with `lucid-technical-writing` and write in that voice. Match the course's
   tone: concrete numbers, short paragraphs, the running bookstore/product examples where useful.
2. Read your lesson's template in full (search for `id="t-<slug>"`). Don't repeat what it says; go under it.
3. Copy its markup conventions: `<h2 id=… level=2>`, `<h3 id=… level=3>`, tables wrapped in
   `<div class="MuiBox-root css-1h3kb9f"><div class="table-scroll"><table class="MuiTable-root css-104jnbp">…`,
   `<blockquote>`, `<details><summary>` for answers, `<ul>/<ol>`, `<strong>`, `<code>`, `<pre>`.

## What a deep dive contains (one fragment per lesson)

Several h2 sections, each titled `Deep Dive: …`, in this order:

1. **Inside the mechanism**: the state, data structures and protocol steps that make the pattern work,
   at the level of a real implementation (e.g. Kafka partitions/offsets/ISR, RabbitMQ acks and prefetch,
   Redis Streams consumer groups, HTTP/2 streams, WebSocket framing, Postgres WAL). Name the real
   systems and the specific knobs that matter, and what each knob trades.
2. **Sizing and the numbers**: worked capacity/latency/cost math the reader can redo (throughput per
   partition, fan-out cost, connection memory, retention/storage, tail latency), with stated assumptions.
3. **Failure modes in production**: 5–7 concrete failures, each as symptom → mechanism → how you detect
   it (the metric/log/trace) → fix. Include the subtle ones (poison messages, rebalance storms,
   head-of-line blocking, thundering reconnects, clock skew, ordering breaks on retry).
4. **Design variations and how to choose**: the real decision points (e.g. at-least-once vs exactly-once
   claims, push vs pull, partition key choice, outbox vs dual write), as a comparison table plus guidance.
5. **Design-review checklist**: 8–12 sharp questions a reviewer asks before approving this pattern.
6. **Senior interview follow-ups**: 6–8 hard follow-up questions with crisp answers in
   `<details><summary>` blocks, the kind that separate memorisation from understanding.

Optional where it earns its place: one small inline SVG diagram of the internal mechanism
(`role="img"`, `<title>`/`<desc>`, readable at 720px, the course's palette from its CSS variables),
or a short code/config snippet (Python stdlib preferred; real config syntax for Kafka/nginx/etc.).

Length: roughly 2,500–4,000 words per pattern lesson; capstones 2,000–3,000 focusing on the end-to-end
deep-dive discussion (capacity plan, failure drills, evolution path). Accuracy over breadth: if unsure
of a default or limit, say it varies or leave it out. No vendor marketing.

## Output

- `guides/sdp/deep/<slug>.html`, where `<slug>` is the template id without `t-`. HTML only, no
  `<template>` wrapper. It is inserted just before the lesson's TL;DR h2.
- Every id you create starts with `dd-<slug>-` and must be unique; use the course's unquoted
  `id=… level=2` style for h2/h3. Links to other lessons use the course's `href="#<slug>"` form.
- Check your fragment: it parses (balanced tags), `python3 guides/sdp/build.py` succeeds.
- Work only in your own scratch subfolder and your own output files. Don't edit the source,
  build.py, or other agents' files. No git.

Report: files created, sections, word count, anything you were unsure of.

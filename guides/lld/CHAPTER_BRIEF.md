# Brief: writing one new type-along LLD chapter

You are adding one problem chapter to the "Python LLD Type-Along Guide"
(`guides/lld/source/python-lld-guide.original.html`, one block per line, pandoc HTML).

## Read first

1. Invoke the Skill tool with `lucid-technical-writing` and write in that voice.
2. Read Chapter 0 (search `id="chapter-0-before-you-type-a-line"`): the scoring rubric, the
   enterprise checklist, the chapter structure, the Setup rules.
3. Read one whole existing chapter as your template. Chapter 6, Car Rental
   (`id="chapter-6-car-rental-system"`), is the most complete. Copy its rhythm exactly: intro
   paragraph, then the ten sections `1. The problem` … `10. Stretch tasks`, the "Type `pkg/file.py`:"
   lead-ins, the checkpoint commands and their real output, the test-results block, the checklist
   table mapped to file/class names, the follow-up questions with answers, stretch tasks.
4. Copy the SVG class-diagram conventions from that chapter (wrapper div, `role="img"`, `<title>`
   and `<desc>` ids, viewBox, colours, fonts, box and arrow styles). Draw your own diagram for your
   classes. Keep labels readable at 960px wide; no overlapping text.

## Rules

- Python 3.13, **standard library only**. Code under `guides/lld/code/<package>/`, tests under
  `guides/lld/tests/test_<package>*.py`, using `unittest`, matching the existing layout.
- Same enterprise checklist as every chapter: SRP, Open/Closed, Liskov, constructor injection,
  custom exception hierarchy (no bare except), stdlib logging (print only in `__main__` demos),
  injectable clock/time, thread safety where state is shared, config dataclasses (no magic numbers),
  type hints throughout.
- Every file you show is complete and runnable. Run every checkpoint and the full test suite
  (`python3 -m unittest discover -s tests -v` from `guides/lld/`) and paste the **real** output.
- Requirements must include the 2026-interview angle for your problem: the clarifying questions an
  interviewer expects, and at least three "now the interviewer moves the goalposts" follow-ups
  answered in section 9 with the design change each needs.

## Output

- Write Markdown in your scratch folder, convert with
  `pandoc -f markdown-smart+gfm_auto_identifiers --wrap=none -t html` (default highlighting).
- Make every id unique against the whole guide: prefix all generated ids (headings, code blocks
  `cbN`, their line anchors and hrefs, SVG title/desc ids) with your chapter slug, e.g. `ch08-`.
  The h1 is exactly `<h1 id="chapter-NN-slug">Chapter NN: Title</h1>` (NN without leading zero in
  the text, e.g. "Chapter 8: Rate Limiter", id `chapter-8-rate-limiter`).
- One block per line: no hard wraps inside `<p>`, `<li>` or headings.
- Save the fragment to `guides/lld/chapters/<NN>-<slug>.html` (NN two-digit). Don't edit the source,
  `guide.py`, other chapters, or other agents' files. Work only in your own scratch subfolder. No git.

Report: files created, test count and result, and anything you were unsure about.

# Book source — Agentic Design Patterns

The Markdown in this folder is the source of the book. SVG diagrams in `diagrams/` are hand-placed and editable, and the build inlines them into the HTML edition.

```
python3 book/build.py      # → dist/agentic-design-patterns.html + dist/agentic-design-patterns.md
python3 code/verify.py     # code is green and every console listing quoted here matches the real run
```

| Path | What |
|---|---|
| `00-scope-sheet.md` | Gate 1: the locked pattern inventory and boundaries |
| `TEMPLATE.md` | The chapter template (pilot draft) |
| `00-front/` | Preface |
| `part-*/` | Part introductions and pattern chapters |
| `capstones/` | Capstone chapters (briefs live with the code) |
| `solutions/` | Exercise solutions, kept apart from chapters |
| `diagrams/` | Editable SVG figures (colour key: terracotta = model, sage = code, ochre = human, dashed = data) |
| `build.py` | Standard-library assembler: TOC, part/chapter nav, cross-links, print CSS |

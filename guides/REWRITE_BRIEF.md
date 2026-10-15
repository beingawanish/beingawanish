# Brief: rewriting one guide chapter

Read `.claude/skills/lucid-technical-writing/SKILL.md` first and follow it. Then study one finished
example: `guides/ccar-f/rewrites/ch01.json` (rewrites) against `guides/ccar-f/work/ch01.json` (originals;
regenerate with `python3 guides/guide.py ccar-f extract 01` if missing).

## Input and output

- Input: `guides/<guide>/work/chNN.json` = `{block_id: {"tag": "p"|"li", "html": original_inner_html}}`.
- Output: `guides/<guide>/rewrites/chNN.json` = `{block_id: new_inner_html}`. UTF-8, `ensure_ascii=False`.
- Leave a block out of the output if it already reads well (short, plain). Don't rewrite for its own sake.
- Exam question stems and answer options (`li` blocks that are options A–D, the question sentence just
  before them) are the user's exact wording: leave them out. Answer explanations may be rewritten.

## Rules

1. **Keep every fact.** Every number, `<code>` span, link `href`, and bold term must survive. The checker
   enforces numbers, code, links and bold terms of ≤ 6 words (case-sensitive, text inside `<b>`).
2. One idea per sentence. Short paragraphs. Active voice. Concrete subjects. No AI tells
   ("delve", "crucial", "it's worth noting", "in essence", em-dash chains, "not X but Y" flourishes).
3. Keep the inline HTML used by the original (`<b>`, `<i>`, `<code>`, `<a href>`, entities). Don't add
   new facts, opinions or examples. Don't change technical terms.
4. Structure you may add, **only in `p` blocks**: split paragraphs with `</p><p>`; turn a run-on
   enumeration into `</p><ul><li>…</li></ul><p>` or `<ol>`. Never end a value with `<p>` or start it
   with `</p>`. Prefer to end on a sentence after a list, or end the value with `</ul>` (the build strips
   the empty paragraph). In `li` blocks: plain sentence rewrites only, no `</p>`, `<ul>`, `<li>`.
5. A paragraph that ends with ":" introduces a code block, table or list that follows. Keep the colon
   ending so it still introduces it.

## Process

For each chapter: write the JSON (in chunks if large, merging into the same file), then run
`python3 guides/guide.py <guide> check NN` until it reports 0 problems. Fix problems by restoring the
lost fact, never by dropping the block's rewrite silently. Don't edit any other file. Don't run git.

Report back: per chapter, blocks rewritten / total, and check result.

---
name: lucid-technical-writing
description: Permanent writing standard for all long-form content (books, guides, handouts, reference docs). Load before drafting or rewriting any chapter, guide or reference prose; runs a lucidity pass then a voice-and-flow pass.
---

# Lucid technical writing

Permanent writing standard for all long-form content (books, guides, handouts, reference docs). The user's standing preference (2026-10-15): prose must read like a regular book — lucid, natural, easy to understand and comprehend. Generated technical prose that stacks clauses reads "heavy" to him; this skill is the fix, applied at writing time, not as an afterthought. It runs two passes: the **lucidity pass** (structure and simplicity) and then the **voice-and-flow pass** (natural human texture — de-AI-ifies manufactured prose).

## When to use

- Writing or editing any chapter, guide, handout, or reference document for him.
- Any prose-polish or rewrite pass over existing material.
- Content language-flow rewrites (making text read like a thoughtful person wrote it, not an AI).
- Load this skill BEFORE drafting long-form content, and hand its rules to any subagent doing writing work.

## When NOT to use

- Chat replies — those follow the normal conversational style.
- Code, code comments, SVG text, tables, headings — never rewrite these for style.
- The user's own words (his audit notes, his phrasing, anything he wrote) — preserve verbatim, never "improve."

## The rules

1. **One idea per sentence.** If a sentence has two clauses joined by "and" where each could stand alone, split it.
2. **Plain verbs over nominalizations.** "use" not "utilize"; "build" not "perform the construction of"; "fails" not "experiences a failure event."
3. **Active voice, concrete subjects.** "The chain hands you a clean seam" not "a clean seam is provided by the chain."
4. **Break up em-dash insertions that carry whole thoughts.** An em-dash aside holding a complete separate idea becomes its own sentence. Keep em-dashes only for short parenthetical color.
5. **No stacked subordinate clauses.** "Because X, which means Y, although Z" → two or three short sentences.
6. **Short paragraphs.** One point per paragraph; a new point gets a new paragraph.
7. **Keep every fact.** Numbers, terms, pattern names, cross-references, and technical claims stay exactly as-is. Lucidity must never cost meaning — simplify the sentence, never the idea.
8. **Don't rewrite for the sake of rewriting.** If a sentence is already plain, leave it.

## Voice and flow (the human-texture pass)

The lucidity rules fix *heavy* prose. This pass fixes *manufactured* prose — text that is grammatically fine but reads like it was generated: too polished, too balanced, too neutral. Apply it AFTER the lucidity pass, never before, and never let it re-complicate a sentence the lucidity pass just simplified.

1. **Natural flow over perfect polish.** Ideas should unfold the way a real person thinks — sometimes direct, sometimes reflective, occasionally a little uneven. A paragraph does not need a perfect closing summary sentence.
2. **Vary sentence length and structure.** Mix short, punchy sentences with longer, more complex ones. Break repetitive patterns: not every paragraph opens the same way, not every point gets the same two-sentence shape.
3. **Keep a voice.** Allow opinions, mild emphasis, small shifts in tone where they feel natural. Do not sand it down to neutral or universally agreeable. A sentence can prefer one approach and say so plainly.
4. **Strip AI tells.** Overly refined phrasing, unnecessary formality, mechanical transitions ("Furthermore," "Moreover," "In conclusion," "It is worth noting that," "It is important to note"), and perfectly balanced constructions ("not only X, but also Y" repeated everywhere). Prefer conversational language that still feels precise.
5. **Add light human texture where it helps.** A brief aside. A moment of emphasis. A slightly imperfect phrasing that a careful person would still write. Keep it coherent and easy to follow — texture, not mess.
6. **Read it aloud.** The final version should sound natural spoken, not manufactured. If it reads like a speech nobody would give, rework it.

**Texture ≠ slang, and voice ≠ spin.** Do not turn technical prose into chat. Do not editorialize the facts. And never "improve" the user's own words.

### Before / after (flow pass)

**Before:** "It is worth noting that caching improves performance significantly. Furthermore, the system demonstrates excellent scalability characteristics under load."
**After:** "Caching is the biggest win here — it changes the whole performance story. And once that's in place, the system scales cleanly under load."

**Before:** "One must consider not only the latency implications but also the operational complexity that such a design introduces."
**After:** "Latency is only half of it. The other half is operational complexity — and that's the half people underestimate."

## Before / after

**Before:** "Asking one prompt to do all three at once forces the model to hold three different objectives in a single context window, and the objectives bleed into each other — the draft starts steering the classification, the policy check gets skipped."
**After:** "Ask one prompt to do all three at once, and the objectives bleed into each other. The draft starts steering the classification. The policy check gets quietly skipped."

**Before:** "Chaining also earns its keep when the intermediate outputs are valuable on their own — the classification can drive routing and analytics even if the draft is never sent — and when you need to inspect or gate between steps (a human approval, a policy check, a schema validation), because the chain hands you a clean seam at every handoff."
**After:** "Chaining also pays off in two more situations. First, when the intermediate outputs are valuable on their own — the classification can drive routing and analytics even if the draft is never sent. Second, when you need to inspect or gate between steps: a human approval, a policy check, a schema validation. The chain hands you a clean seam at every handoff."

## Self-check before delivering

- Read three random paragraphs aloud (in your head). If any sentence needs a second parse, split it.
- `grep` for the heaviest tells: sentences over ~35 words, "in order to", "utilize", "facilitate", "leverage" (as a verb), double em-dashes in one sentence.
- `grep` for flow-pass tells: "Furthermore," "Moreover," "In conclusion," "It is worth noting", "It is important to note", repeated "not only ... but also".
- Rhythm check: if three sentences in a row are the same shape and length, break one up.
- Confirm: no fact changed, no number moved, no term redefined, no user-written passage altered.

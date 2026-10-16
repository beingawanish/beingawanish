"""Insert the new LLD chapters into the guide (run by guides/guide.py load(), after the other fix layers).

Fragments live in guides/lld/chapters/, named NN-slug.html and sorted by name:
06v2-… is Version 2 of Chapter 6 (an h2 section appended to that chapter),
07-… to 15-… are new problem chapters. They all go, in order, just before the outro,
which becomes the last chapter. The TOC gets an entry for every new h1 and h2.
Text edits to the intro and outro live in TEXT_EDITS (old, new, expected count).
"""
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
CHAPTERS = HERE / "chapters"
OUTRO_OLD = ("chapter-7-what-repeats", "Chapter 7: What Repeats")

TEXT_EDITS: list[tuple[str, str, int]] = []


def _toc(fragment: str) -> str:
    """TOC <li> entries for the fragment's h1/h2 headings (h2 nested under its h1)."""
    out, open_h1 = [], False
    for m in re.finditer(r'<h([12]) id="([^"]+)">(.*?)</h\1>', fragment):
        level, hid, inner = m.groups()
        link = f'<a href="#{hid}" id="toc-{hid}">{inner}</a>'
        if level == "1":
            if open_h1:
                out.append("</ul></li>")
            out.append(f"<li>{link} <ul>")
            open_h1 = True
        else:
            out.append(f"<li>{link}</li>")
    if open_h1:
        out.append("</ul></li>")
    return "\n".join(out)


def apply(text: str) -> str:
    fragments = sorted(CHAPTERS.glob("*.html"))
    if not fragments:
        return text
    new_chapters = sum(1 for f in fragments if not f.name.startswith("06v2"))
    outro_n = 7 + new_chapters
    new_id, new_title = f"chapter-{outro_n}-what-repeats", f"Chapter {outro_n}: What Repeats"
    body = "\n".join(f.read_text().strip() for f in fragments)

    # Body: fragments go just before the outro heading, which is renumbered.
    old_h1 = f'<h1 id="{OUTRO_OLD[0]}">{OUTRO_OLD[1]}</h1>'
    assert text.count(old_h1) == 1, "outro heading not found exactly once"
    text = text.replace(old_h1, f'{body}\n<h1 id="{new_id}">{new_title}</h1>')

    # TOC: v2 entries nest inside Chapter 6's list; new chapters go before the outro entry.
    old_toc = f'<li><a href="#{OUTRO_OLD[0]}" id="toc-{OUTRO_OLD[0]}">{OUTRO_OLD[1]}</a>'
    assert text.count(old_toc) == 1, "outro TOC entry not found exactly once"
    chapter_toc = "\n".join(_toc(f.read_text()) for f in fragments if not f.name.startswith("06v2"))
    text = text.replace(old_toc, f'{chapter_toc}\n<li><a href="#{new_id}" id="toc-{new_id}">{new_title}</a>')
    # Version 2 sorts first (06v2 < 07), so in the body it already ends Chapter 6.
    # In the TOC its h2 entries go inside Chapter 6's list: before the "</ul></li>" that
    # closes Chapter 6, i.e. the last one before the next top-level entry.
    for f in fragments:
        if f.name.startswith("06v2"):
            ch6 = text.index('id="toc-chapter-6-car-rental-system"')
            nxt = text.index('<li><a href="#chapter-', ch6 + 1)
            close = text.rindex("</ul>", ch6, nxt)
            text = text[:close] + _toc(f.read_text()) + "\n" + text[close:]

    # Any remaining links to the old outro id.
    text = text.replace(f'href="#{OUTRO_OLD[0]}"', f'href="#{new_id}"')

    for old, new, count in TEXT_EDITS:
        assert text.count(old) == count, f"expected {count} of: {old[:70]}"
        text = text.replace(old, new)
    return text

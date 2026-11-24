#!/usr/bin/env python3
"""Combine the System Design Patterns course and the Networking Mastery Guide into one HTML file.

    python3 guides/combined/build.py   ->  dist/system-design-and-networking.html

Each guide keeps its own CSS, scripts and navigation, so each runs unchanged in its own frame.
The guide's HTML is stored inert in a <script type="text/html"> block and loaded into an
iframe (srcdoc) the first time its tab is opened. Deep links: #sdp/<lesson> and #net/<anchor>.
"""
import html
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DIST = ROOT / "dist"
OUT = DIST / "system-design-and-networking.html"
GUIDES = [
    ("sdp", "System Design Patterns", "system-design-patterns.html",
     "12 modules from fundamentals to real systems. Every lesson ends with a deep dive: the mechanism, "
     "sizing math, failure modes, design variations, a review checklist and senior interview follow-ups. "
     "Includes the advanced event-driven architecture part and the eda-commerce capstone pointer."),
    ("net", "Networking Mastery Guide", "networking-mastery-guide.html",
     "23 modules from Ethernet to Kubernetes. Each of the original 18 ends with deep dives on the real "
     "machine (state, wire captures, numbers, failure modes, 2026 context, interview questions), plus new "
     "modules on load balancing, QUIC/HTTP3, BGP, cloud and container networking."),
]
# "</script" would end the holder block early; it is swapped for a placeholder and restored in JS.
PLACEHOLDER = "</scr_ipt"
BOOK_CSS = (pathlib.Path(__file__).with_name("book.css")).read_text()


def build() -> str:
    holders, cards, tabs = [], [], []
    for key, title, name, blurb in GUIDES:
        doc = (DIST / name).read_text()
        # Book theme last, so it overrides the guide's own colours and fonts.
        doc = doc.replace("</body>", f'<style id="book-theme">{BOOK_CSS}</style></body>', 1)
        assert PLACEHOLDER not in doc
        holders.append(f'<script type="text/html" id="src-{key}">{doc.replace("</script", PLACEHOLDER)}</script>')
        tabs.append(f'<button type="button" data-guide="{key}">{html.escape(title)}</button>')
        cards.append(f'<a class="card" href="#{key}"><h2>{html.escape(title)}</h2><p>{html.escape(blurb)}</p>'
                     f'<span>Open →</span></a>')
    frames = "".join(f'<iframe id="frame-{k}" title="{html.escape(t)}" hidden></iframe>' for k, t, *_ in GUIDES)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>System Design &amp; Networking</title>
<style>
  html, body {{ margin: 0; height: 100%; font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif; background: #fff; color: #111; }}
  body {{ display: flex; flex-direction: column; }}
  header {{ display: flex; align-items: center; gap: 8px; padding: 0 12px; height: 46px; flex: none;
           background: #fff; color: #111; border-bottom: 1px solid #111; overflow-x: auto; white-space: nowrap; }}
  header a.home {{ color: #000; font-weight: 700; text-decoration: none; margin-right: 8px; }}
  header button {{ font: inherit; font-size: 14px; color: #333; background: none; border: 0; padding: 8px 12px;
                   border-radius: 6px; cursor: pointer; }}
  header button[aria-current="true"] {{ color: #000; text-decoration: underline; text-underline-offset: 6px; }}
  @media (max-width: 600px) {{ header a.home {{ font-size: 0; }} header a.home::before {{ content: "Home"; font-size: 14px; }} }}
  main {{ flex: 1; min-height: 0; position: relative; }}
  iframe {{ position: absolute; inset: 0; width: 100%; height: 100%; border: 0; background: #fff; }}
  #home {{ max-width: 960px; margin: 0 auto; padding: 48px 20px; overflow-y: auto; height: 100%; box-sizing: border-box; }}
  #home h1 {{ font-size: 32px; margin: 0 0 8px; }}
  #home > p {{ color: #333; margin: 0 0 28px; line-height: 1.6; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; }}
  .card {{ display: block; background: #fff; border: 1px solid #111; border-radius: 0; padding: 24px;
           color: inherit; text-decoration: none;  }}
  .card:hover {{ background: #f6f6f6; }}
  .card h2 {{ margin: 0 0 10px; font-size: 21px; }}
  .card p {{ margin: 0 0 16px; line-height: 1.6; color: #222; }}
  .card span {{ color: #000; font-weight: 600; }}
</style>
</head>
<body>
<header><a class="home" href="#">System Design &amp; Networking</a>{"".join(tabs)}</header>
<main>
<section id="home">
<h1>System Design &amp; Networking</h1>
<p>Two complete guides in one file. Pick one to start; the bar at the top switches between them, and each
keeps its own navigation, outline and reading progress.</p>
<div class="cards">{"".join(cards)}</div>
</section>
{frames}
</main>
{"".join(holders)}
<script>
(() => {{
  const PH = {PLACEHOLDER!r};
  window.__pending = {{}};
  const home = document.getElementById('home');
  const tabs = document.querySelectorAll('header button');
  function frame(key) {{
    const f = document.getElementById('frame-' + key);
    if (!f.dataset.loaded) {{
      const src = document.getElementById('src-' + key).textContent.split(PH).join('</scr' + 'ipt');
      // srcdoc keeps the guide same-origin with this page. Its base URL would be this page's URL,
      // so "#lesson" links and history.replaceState would leave the frame; <base> points them back at it.
      // The injected script applies a pending deep link before the guide's own router starts.
      const boot = '<base href="about:srcdoc"><script>(function(){{var h=parent.__pending&&parent.__pending["' + key
        + '"];if(h){{parent.__pending["' + key + '"]="";history.replaceState(null,"","#"+h);}}}})();</scr' + 'ipt>';
      f.srcdoc = src.replace(/<head([^>]*)>/i, '<head$1>' + boot);
      f.dataset.loaded = '1';
    }}
    return f;
  }}
  function show() {{
    const [key, ...rest] = location.hash.slice(1).split('/');
    const sub = rest.join('/');
    const known = ['sdp', 'net'].includes(key);
    home.hidden = known;
    tabs.forEach(b => b.setAttribute('aria-current', String(b.dataset.guide === key)));
    document.querySelectorAll('iframe').forEach(f => f.hidden = true);
    if (!known) {{ document.title = 'System Design & Networking'; return; }}
    const fresh = !document.getElementById('frame-' + key).dataset.loaded;
    if (fresh) window.__pending[key] = sub;
    const f = frame(key);
    f.hidden = false;
    document.title = f.title;
    if (sub && !fresh) f.contentWindow.location.hash = sub;
  }}
  tabs.forEach(b => b.addEventListener('click', () => {{ location.hash = b.dataset.guide; }}));
  addEventListener('hashchange', show);
  show();
}})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    OUT.write_text(build())
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")

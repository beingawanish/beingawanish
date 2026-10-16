// Readability layer: side navigation built from the headings, scroll tracking,
// chapter-to-chapter links, and answers opened automatically for printing.
(function () {
  var doc = document.querySelector('.doc');
  var page = document.querySelector('.page');
  if (!doc || !page) return;
  var h1s = Array.prototype.slice.call(doc.querySelectorAll('h1[id]'));

  // Chapter number badge: "01 · Title" -> data-num="CHAPTER 01", text "Title"
  h1s.forEach(function (h) {
    var m = h.textContent.match(/^(\d\d) · (.*)$/);
    if (m) { h.setAttribute('data-num', 'CHAPTER ' + m[1]); h.dataset.short = m[2]; h.dataset.n = m[1]; h.textContent = m[2]; return; }
    // "Module 3 — Title" / "Capstone 2 — Title" -> data-num="MODULE 3", text "Title"
    m = h.textContent.replace(/\s+/g, ' ').trim().match(/^(?:\d+\.\s*)?(Module|Capstone) (\d+) [—–-] (.*)$/);
    if (m) { h.setAttribute('data-num', m[1].toUpperCase() + ' ' + m[2]); h.dataset.short = m[3]; h.dataset.n = (m[1] === 'Capstone' ? 'C' : 'M') + m[2]; h.textContent = m[3]; }
  });
  // Section number chips: "03 Title" -> <span class=secnum>03</span>Title
  doc.querySelectorAll('h2[id]').forEach(function (h) {
    var m = h.textContent.match(/^(\d\d) (.*)$/);
    if (m) { h.innerHTML = '<span class="secnum">' + m[1] + '</span>' + m[2].replace(/</g, '&lt;'); }
  });

  // Side navigation
  var side = document.createElement('nav');
  side.className = 'side';
  side.setAttribute('aria-label', 'Contents');
  var full = (document.querySelector('#title-block-header .title') || {}).textContent || document.title;
  var m0 = full.match(/^(.*?)\s*\((CCAR-[A-Z])\)/);
  var m1 = full.replace(/\s+/g, ' ').match(/^([^:]+):\s*(.*)$/);
  var html = '<p class="brand-s">' + (m0 ? m0[2] + ' Preparation Guide' : m1 ? m1[1] : document.title) + '</p><p class="sub">' +
             (m0 ? m0[1].replace(/\s*[—–-]\s*/, ' — ') : m1 ? m1[2] : '') + '</p><ol>';
  h1s.forEach(function (h) {
    html += '<li class="ch" data-ch="' + h.id + '"><a href="#' + h.id + '"><span class="n">' + (h.dataset.n || '') +
            '</span>' + (h.dataset.short || h.textContent) + '</a><ol class="secs">';
    var el = h.nextElementSibling;
    while (el && el.tagName !== 'H1') {
      if (el.tagName === 'H2' && el.id) {
        html += '<li><a href="#' + el.id + '">' + el.textContent.replace(/^\d\d/, '').trim() + '</a></li>';
      }
      el = el.nextElementSibling;
    }
    html += '</ol></li>';
  });
  side.innerHTML = html + '</ol>';
  page.insertBefore(side, page.firstChild);

  var btn = document.createElement('button');
  btn.className = 'menu-btn'; btn.type = 'button'; btn.textContent = '☰ Contents';
  btn.addEventListener('click', function () { side.classList.toggle('open'); });
  document.body.insertBefore(btn, document.body.firstChild);
  side.addEventListener('click', function (e) { if (e.target.closest('a') && window.innerWidth <= 980) side.classList.remove('open'); });

  var bar = document.createElement('div'); bar.className = 'progress'; document.body.appendChild(bar);

  // Previous / next chapter links at the end of each chapter
  h1s.forEach(function (h, i) {
    var end = i + 1 < h1s.length ? h1s[i + 1] : null;
    var nav = document.createElement('div'); nav.className = 'chapnav';
    var prev = i > 0 ? '<a href="#' + h1s[i - 1].id + '"><small>Previous</small>' + h1s[i - 1].dataset.short + '</a>' : '<span></span>';
    var next = end ? '<a href="#' + end.id + '" style="text-align:right"><small>Next</small>' + end.dataset.short + '</a>' : '<span></span>';
    nav.innerHTML = prev + next;
    if (end) doc.insertBefore(nav, end); else doc.appendChild(nav);
  });

  // Scroll tracking: open the current chapter in the sidebar, highlight the current section
  var links = {};
  side.querySelectorAll('a[href^="#"]').forEach(function (a) { links[a.getAttribute('href').slice(1)] = a; });
  var heads = Array.prototype.slice.call(doc.querySelectorAll('h1[id], h2[id]'));
  var ticking = false;
  function update() {
    ticking = false;
    var y = window.scrollY + 120, cur = null, curCh = null;
    for (var i = 0; i < heads.length; i++) {
      if (heads[i].offsetTop > y) break;
      cur = heads[i]; if (heads[i].tagName === 'H1') curCh = heads[i];
    }
    side.querySelectorAll('a.active').forEach(function (a) { a.classList.remove('active'); });
    side.querySelectorAll('.ch.open').forEach(function (c) { c.classList.remove('open'); });
    if (curCh) { var li = side.querySelector('[data-ch="' + curCh.id + '"]'); if (li) li.classList.add('open'); }
    if (cur && links[cur.id]) { links[cur.id].classList.add('active'); }
    var h = document.documentElement;
    bar.style.width = (100 * h.scrollTop / Math.max(1, h.scrollHeight - h.clientHeight)) + '%';
  }
  window.addEventListener('scroll', function () { if (!ticking) { ticking = true; requestAnimationFrame(update); } });
  update();

  // Print everything, answers included
  window.addEventListener('beforeprint', function () { document.querySelectorAll('details.answer').forEach(function (d) { d.open = true; }); });
})();

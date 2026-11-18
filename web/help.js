// Shared by every page: the Standard | Expert view switch and the ⓘ help (fiasc/help.json -> data/help.json).
// Help popovers open on hover (mouse), keyboard focus and tap, and close with Escape, a second tap or a tap elsewhere.
'use strict';
const HELP = { data: null, ready: null };

// ---------------------------------------------------------------- view: Standard | Expert (URL ?view=expert, localStorage)
const VIEW = (() => {
  let v = new URLSearchParams(location.search).get('view');
  if (v !== 'expert' && v !== 'standard') { try { v = localStorage.getItem('fia_view'); } catch (e) { v = null; } }
  return v === 'expert' ? 'expert' : 'standard';
})();
document.documentElement.dataset.view = VIEW;
const isExpert = () => document.documentElement.dataset.view === 'expert';
function setView(v) {
  document.documentElement.dataset.view = v;
  try { localStorage.setItem('fia_view', v); } catch (e) { /* storage blocked: the URL still carries the view */ }
  const u = new URL(location.href);
  if (v === 'expert') u.searchParams.set('view', 'expert'); else u.searchParams.delete('view');
  history.replaceState(null, '', u);
  document.querySelectorAll('.viewsw button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === v)));
  document.querySelectorAll('a[data-keepview]').forEach(keepView);
  window.dispatchEvent(new CustomEvent('viewchange', { detail: v }));
}
function keepView(a) {
  const u = new URL(a.getAttribute('href'), location.href);
  if (isExpert()) u.searchParams.set('view', 'expert'); else u.searchParams.delete('view');
  a.setAttribute('href', u.pathname.split('/').pop() + u.search + u.hash);
}
function viewSwitch(el) {
  el.innerHTML = `<span class="viewsw" role="group" aria-label="View"><button type="button" data-v="standard">Standard</button><button type="button" data-v="expert">Expert</button></span>`;
  el.querySelectorAll('button').forEach(b => { b.setAttribute('aria-pressed', String(b.dataset.v === document.documentElement.dataset.view)); b.onclick = () => setView(b.dataset.v); });
  document.querySelectorAll('a[data-keepview]').forEach(keepView);
}

// ---------------------------------------------------------------- help data
function loadHelp() { return HELP.ready || (HELP.ready = getJSON('data/help.json').then(d => (HELP.data = d))); }
// key: "TABLE.COL" (FIADB column) or "d:name" (value computed by this site) or "s:section"
function helpFor(key) {
  const H = HELP.data;
  if (!H || !key) return null;
  if (key.startsWith('d:')) { const d = H.derived[key.slice(2)]; return d ? { label: d.label, unit: d.unit, text: d.help, src: d.src, code: '' } : null; }
  if (key.startsWith('s:')) { const s = H.sections[key.slice(2)]; return s ? { label: s.title, unit: '', text: s.intro, src: s.refs, code: '' } : null; }
  const e = H.columns[key];
  if (!e) return null;
  const col = key.split('.').pop(), g = e.guide, p = e.plain;
  if (isExpert() || !p) {
    if (g) return { label: g.label, unit: (p && p.unit) || g.unit, text: g.text, src: `FIADB User Guide §${g.sec}` + (g.note ? ` (${g.note})` : ''), code: col, guide: true,
      plain: p ? p.help : '' };
    if (e.nodef) return { label: (p && p.label) || col, unit: (p && p.unit) || '', text: e.nodef, src: '', code: col };
  }
  return { label: p.label, unit: p.unit, text: p.help, src: g ? `FIADB User Guide §${g.sec}` : '', code: col };
}
const gAnchor = key => 'h-' + key.replace(/[^A-Za-z0-9]+/g, '-');
// a table header cell: friendly label (Standard) or the raw column name (Expert), the other in small text, and an ⓘ button
function th(key, opts = {}) {
  if (opts.sort) return thSort(key, opts);
  const h = helpFor(key) || { label: opts.l || key, unit: '', text: '', code: '' };
  const col = h.code || '';
  let main = opts.l || h.label, sub = col && col !== main ? col : '';
  if (isExpert() && col) { main = col; sub = ''; }
  if (opts.unit !== false && h.unit && !/[(/]/.test(main) && !isExpert()) sub = (sub ? sub + ' · ' : '') + h.unit;
  return `<th${opts.n ? ' class="n"' : ''} scope="col" data-hk="${esc(key)}"><span class="thl">${esc(main)}</span>${sub ? `<small class="thc">${esc(sub)}</small>` : ''}`
    + `<button type="button" class="hb" data-h="${esc(key)}" aria-label="About ${esc(main)}">ⓘ</button></th>`;
}
// sortable header: the label is its own button (sort), the ⓘ a separate tap target (help). Standard view shows the plain
// name with its unit ("Diameter (DBH), in") and the FIADB name in small text (hidden on phones); Expert view the FIADB name.
function thSort(key, opts) {
  const h = helpFor(key) || { label: opts.l || key, unit: '', text: '', code: '' };
  const col = h.code || '', exp = isExpert() && col;
  let main = exp ? col : (opts.l || h.label);
  if (!exp && h.unit && opts.unit !== false && !main.includes(h.unit)) main += `, ${h.unit}`;
  const sub = !exp && col && col !== main ? col : '';
  return `<th${opts.n ? ' class="n"' : ''} scope="col" data-hk="${esc(key)}" aria-sort="none"><button type="button" class="sortb" aria-label="Sort by ${esc(main)}">`
    + `<span class="thl">${esc(main)}</span>${sub ? `<small class="thc">${esc(sub)}</small>` : ''}<span class="arr" aria-hidden="true"></span></button>`
    + `<button type="button" class="hb" data-h="${esc(key)}" aria-label="About ${esc(main)}">ⓘ</button></th>`;
}
// a section intro: the plain-language text (Standard) or a one-line ⓘ (Expert)
function intro(sectionKey) {
  const s = HELP.data && HELP.data.sections[sectionKey];
  if (!s) return '';
  return `<div class="intro" data-sk="${esc(sectionKey)}"><p class="intro-std">${esc(s.intro)}${s.refs ? ` <span class="src">(${esc(s.refs)})</span>` : ''}</p>`
    + `<p class="intro-exp"><button type="button" class="hb" data-h="s:${esc(sectionKey)}" aria-label="About ${esc(s.title)}">ⓘ</button> <span class="muted">${esc(s.title)}${s.refs ? ' · ' + esc(s.refs) : ''}</span></p></div>`;
}
function helpHtml(key) {
  const h = helpFor(key);
  if (!h) return '<p>No help text.</p>';
  return `<div class="hp-t">${esc(h.label)}${h.code ? ` <code>${esc(h.code)}</code>` : ''}${h.unit ? ` <span class="hp-u">${esc(h.unit)}</span>` : ''}</div>`
    + `<p>${esc(h.text)}</p>` + (h.plain && isExpert() ? `<p class="hp-p">${esc(h.plain)}</p>` : '')
    + (h.src ? `<p class="hp-s">${esc(h.src)}</p>` : '')
    + `<p class="hp-l"><a href="glossary.html#${gAnchor(key)}">Glossary →</a></p>`;
}

// ---------------------------------------------------------------- popover
let pop = null, popFor = null, pinned = false;
function showHelp(btn, pin) {
  if (!pop) { pop = document.createElement('div'); pop.id = 'hpop'; pop.setAttribute('role', 'tooltip'); document.body.append(pop);
    pop.addEventListener('mouseleave', () => { if (!pinned) hideHelp(); }); }
  popFor = btn; pinned = !!pin;
  pop.innerHTML = helpHtml(btn.dataset.h);
  pop.hidden = false;
  btn.setAttribute('aria-describedby', 'hpop');
  btn.setAttribute('aria-expanded', 'true');
  const r = btn.getBoundingClientRect(), w = Math.min(340, innerWidth - 16);
  pop.style.width = w + 'px';
  let x = Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2));
  pop.style.left = (x + scrollX) + 'px';
  const ph = pop.offsetHeight, below = r.bottom + 6, y = below + ph > innerHeight && r.top - ph - 6 > 0 ? r.top - ph - 6 : below;
  pop.style.top = (y + scrollY) + 'px';
}
function hideHelp() {
  if (!pop || pop.hidden) return;
  pop.hidden = true;
  if (popFor) { popFor.removeAttribute('aria-describedby'); popFor.setAttribute('aria-expanded', 'false'); }
  popFor = null; pinned = false;
}
document.addEventListener('mouseover', e => {
  const b = e.target.closest && e.target.closest('.hb');
  if (b && !pinned && matchMedia('(hover: hover)').matches) showHelp(b, false);
});
document.addEventListener('mouseout', e => {
  const b = e.target.closest && e.target.closest('.hb');
  if (b && !pinned && b === popFor && !(e.relatedTarget && pop && pop.contains(e.relatedTarget))) setTimeout(() => { if (!pinned && pop && !pop.matches(':hover')) hideHelp(); }, 120);
});
document.addEventListener('focusin', e => { const b = e.target.closest && e.target.closest('.hb'); if (b) showHelp(b, false); });
document.addEventListener('focusout', e => { const b = e.target.closest && e.target.closest('.hb'); if (b && !pinned) setTimeout(() => { if (!pinned && (!pop || !pop.contains(document.activeElement))) hideHelp(); }, 50); });
document.addEventListener('click', e => {
  const b = e.target.closest && e.target.closest('.hb');
  if (b) { e.preventDefault(); e.stopPropagation(); if (popFor === b && pinned) hideHelp(); else showHelp(b, true); return; }
  if (pop && !pop.hidden && !pop.contains(e.target)) hideHelp();
}, true);
document.addEventListener('keydown', e => { if (e.key === 'Escape') hideHelp(); });
window.addEventListener('scroll', () => { if (pop && !pop.hidden && !pinned) hideHelp(); }, { passive: true });

// Glossary: renders data/help.json (the same text as the ⓘ help and the PDF summary) with examples from real plot values.
'use strict';
(async function () {
  const [H, ex] = await Promise.all([loadHelp(), getJSON('data/glossary_ex.json').catch(() => ({})), loadMeta()]);
  footer();
  viewSwitch($('#viewsw'));
  $('#gsrc').textContent = `Source: ${H.meta.source}. ${H.meta.how}`;
  const fill = s => (s || '').replace(/\{(\w+)\}/g, (m, k) => ex[k] || '');
  const item = (id, title, code, unit, text, src, extra) => `<div class="gitem" id="${id}" data-s="${esc((title + ' ' + code + ' ' + text).toLowerCase())}">`
    + `<h3>${esc(title)}${code ? ` <code>${esc(code)}</code>` : ''}${unit ? ` <span class="muted">· ${esc(unit)}</span>` : ''}</h3><p>${esc(text)}</p>`
    + (extra ? `<p class="gex"><b>Example:</b> ${esc(extra)}</p>` : '') + (src ? `<p class="muted">${esc(src)}</p>` : '') + '</div>';
  const slug = t => 'g-' + t.toLowerCase().replace(/[^a-z0-9]+/g, '-');
  $('#gterms').innerHTML = H.glossary.map(g => item(slug(g.term), g.term, '', g.units, g.def, g.sec ? `FIADB User Guide ${g.sec.replace(/(^|; )(?=\d)/g, '$1§')}` : '', fill(g.ex))).join('');
  $('#gderived').innerHTML = Object.entries(H.derived).map(([k, d]) => item(gAnchor('d:' + k), d.label, '', d.unit, d.help, d.src)).join('');
  $('#gsections').innerHTML = Object.entries(H.sections).map(([k, s]) => item(gAnchor('s:' + k), s.title, '', '', s.intro, s.refs)).join('');
  const byTable = {};
  Object.entries(H.columns).forEach(([k, e]) => { const t = k.split('.')[0]; (byTable[t] = byTable[t] || []).push([k, e]); });
  $('#gcols').innerHTML = Object.keys(byTable).sort().map(t => `<details class="gtab" open><summary><b>${esc(t)}</b> (${byTable[t].length})</summary>` + byTable[t].sort().map(([k, e]) => {
    const g = e.guide, p = e.plain, col = k.split('.')[1];
    const text = p ? p.help + (g ? ` — User Guide: “${g.text}”` : '') : g ? g.text : e.nodef;
    return item(gAnchor(k), p ? p.label : (g ? g.label : col), k, (p && p.unit) || (g && g.unit) || '', text, g ? `FIADB User Guide §${g.sec}${g.note ? ' (' + g.note + ')' : ''}` : '');
  }).join('') + '</details>').join('');
  const q = $('#gq');
  q.oninput = () => { const s = q.value.trim().toLowerCase(); let n = 0;
    document.querySelectorAll('.gitem').forEach(e => { const on = !s || e.dataset.s.includes(s); e.hidden = !on; n += on; });
    $('#gn').textContent = s ? `${n} matching` : ''; };
  if (location.hash) { const t = document.getElementById(location.hash.slice(1)); if (t) { const d = t.closest('details'); if (d) d.open = true; t.classList.add('gfocus'); t.scrollIntoView(); } }
  document.body.dataset.ready = '1';
})().catch(e => { document.body.dataset.ready = 'error'; $('#gterms').textContent = 'Could not load the glossary: ' + e.message; });

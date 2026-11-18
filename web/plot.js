// SC FIA plot explorer (static site): plot page.
// Data: p/<key>.json. Its "sum" block is computed by fiasc/summary.py, the same code as the PDF summary (stand totals,
// species tables, highlights, caveats), so page and PDF agree. Visit records, tree links, events and growth intervals
// come from the Python build. Expert view adds x/<key>.json (loaded only in that view; see expert.js).
'use strict';
const KEY = new URLSearchParams(location.search).get('k') || '';
const PL = { P: null, X: null, vi: null, hist: null, S: null };
window.PLOT = PL;
const plotCfg = { displaylogo: false, responsive: true, modeBarButtonsToRemove: ['lasso2d', 'select2d'] };
function theme() {
  const cs = getComputedStyle(document.documentElement);
  const ink = cs.getPropertyValue('--ink').trim(), line = cs.getPropertyValue('--line').trim();
  return { paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { color: ink, family: 'Segoe UI, Arial, sans-serif', size: 12 },
    xaxis: { gridcolor: line, zeroline: false }, yaxis: { gridcolor: line, zeroline: false }, margin: { l: 60, r: 20, t: 36, b: 50 },
    legend: { orientation: 'h', y: -0.18 }, hoverlabel: { font: { size: 12 } } };
}
const lay = o => { const t = theme(); return Object.assign(t, o, { xaxis: Object.assign(t.xaxis, o.xaxis || {}), yaxis: Object.assign(t.yaxis, o.yaxis || {}) }); };
const M = k => FIA.meta.metrics.indexOf(k);
const met = (v, k) => v.m[M(k)];
const PAL = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'], OTHER = '#9a9893';
const LIGHT = new Set(['#eda100', '#e87ba4', '#c9c8c2', '#9a9893', '#1baf7a']);

// ---------------------------------------------------------------- tables: every header goes through th() (help text required)
// cols: [{k: help key, l?: label override, n?: numeric}]; rows: arrays of cell HTML (or {h, cls, attrs} objects)
// o.sort: sortable headers (click/tap: ascending → descending → original order; cells may be {h: html, v: sort value});
// o.sticky: first column stays in view while the table scrolls sideways (with a fade on the right edge when more columns exist)
function tbl(cols, rows, o = {}) {
  const head = cols.map(c => th(c.k, { l: c.l, n: c.n, sort: o.sort })).join('');
  const body = rows.map((r, ri) => {
    const tr = Array.isArray(r) ? { cells: r } : r;
    return `<tr data-i="${ri}"${tr.attrs || ''}>` + tr.cells.map((c, i) => { const obj = c !== null && typeof c === 'object';
      const v = obj ? c.v : null, h = obj ? c.h : c;
      return `<td${cols[i] && cols[i].n ? ' class="n"' : ''}${obj && v != null ? ` data-v="${esc(v)}"` : ''}>${h ?? ''}</td>`; }).join('') + '</tr>';
  }).join('');
  const foot = o.foot ? `<tfoot><tr><td colspan="${cols.length}">${o.foot}</td></tr></tfoot>` : '';
  const cls = [o.cls || '', o.sort ? 'sortable vt' : '', o.sticky ? 'stickyfirst' : ''].join(' ').trim();
  const t = `<div class="scroll${o.wrapCls ? ' ' + o.wrapCls : ''}"${o.noMax ? ' style="max-height:none"' : ''}><table class="${cls}"${o.id ? ` id="${o.id}"` : ''}><thead><tr>${head}</tr></thead><tbody>${body}</tbody>${foot}</table></div>`;
  return o.sticky ? `<div class="hscroll">${t}</div>` : t;
}
// sort a table.sortable by one column; ties and "original" fall back to the row's original position (which is
// survey year, subplot, tree number for tree tables)
document.addEventListener('click', e => {
  const b = e.target.closest && e.target.closest('table.sortable .sortb');
  if (!b) return;
  const thEl = b.closest('th'), table = thEl.closest('table'), ci = [...thEl.parentElement.children].indexOf(thEl);
  const next = { none: 'ascending', ascending: 'descending', descending: 'none' }[thEl.getAttribute('aria-sort') || 'none'];
  table.querySelectorAll('thead th').forEach(x => x.setAttribute('aria-sort', 'none'));
  thEl.setAttribute('aria-sort', next);
  table.querySelectorAll('tr.tdet').forEach(x => { if (x.previousElementSibling) x.previousElementSibling.setAttribute('aria-expanded', 'false'); x.remove(); });
  const tb = table.tBodies[0], rows = [...tb.rows];
  const key = tr => { const td = tr.cells[ci]; if (!td) return null; const v = td.dataset.v ?? td.textContent.trim(); return v === '' || v === '—' ? null : v; };
  const num = v => v !== null && v !== '' && !isNaN(+v);
  const dir = next === 'ascending' ? 1 : next === 'descending' ? -1 : 0;
  rows.sort((a, b2) => {
    if (dir) { const x = key(a), y = key(b2);
      if (x === null && y !== null) return 1; if (y === null && x !== null) return -1;
      if (x !== null && y !== null) { const c = num(x) && num(y) ? (+x - +y) : String(x).localeCompare(String(y), undefined, { numeric: true }); if (c) return dir * c; } }
    return +a.dataset.i - +b2.dataset.i;
  });
  rows.forEach(r => tb.append(r));
});
// right-edge fade while more columns are hidden to the right
function updateFades(root = document) {
  root.querySelectorAll('.hscroll').forEach(w => { const s = w.querySelector('.scroll');
    const f = () => w.classList.toggle('more', s.scrollLeft + s.clientWidth < s.scrollWidth - 2);
    if (!s.dataset.fade) { s.dataset.fade = '1'; s.addEventListener('scroll', f, { passive: true }); }
    f(); });
}
window.addEventListener('resize', () => updateFades());
// Standard view: meanings without codes, common names, fixed decimals; Expert view: "code = meaning"
const STATUS_WORD = { 0: 'Not in sample', 1: 'Live', 2: 'Dead', 3: 'Cut' };
const NUMFMT = { DIA: 1, HT: 0, ACTUALHT: 0, CR: 0, TPA_UNADJ: 3, VOLCFNET: 1, VOLCFGRS: 1, DRYBIO_AG: 0, CARBON_AG: 0, TREECOUNT: 0, SITREE: 0, SIBASE: 0,
  AGEDIA: 0, SICOND: 0, COVER_PCT: 1, MORTYR: 0, SLOPE: 0, ASPECT: 0, CONDPROP_UNADJ: 2 };
function cell(table, col, v) {
  if (blank(v)) return { h: '', v: null };
  if (isExpert()) return { h: dvs(decodeCell(table, col, v), 26), v };
  if (col === 'STATUSCD' && STATUS_WORD[v] !== undefined && /TREE|SITETREE/.test(table)) return { h: STATUS_WORD[v], v: STATUS_WORD[v] };
  if (col === 'SPCD' || col === 'SISP' || col === 'SISP_FVS') { const n = spName(v); return { h: esc(n), v: n }; }
  const d = decodeCell(table, col, v);
  if (d && typeof d === 'object' && 'status' in d) {
    if (d.status !== 'decoded') return { h: dv(d), v: String(v) };
    const t = d.text.replace(/^[^=]*=\s*/, '').split(' - ')[0].split('. ')[0].replace(/\.$/, '').replace(/\s*\(.*$/, '');
    return { h: `<span title="${esc(d.text)}">${esc(t)}</span>`, v: t };
  }
  if (typeof v === 'number') return { h: col in NUMFMT ? fmt(v, NUMFMT[col]) : (Number.isInteger(v) ? String(v) : fmt(v, 2)), v };
  return { h: esc(v), v };
}
const S_ = () => PL.S;

// ---------------------------------------------------------------- init
async function init() {
  if (!/^\d+-\d+-\d+-\d+$/.test(KEY)) throw new Error('missing or invalid plot key');
  const [meta, codes, P] = await Promise.all([loadMeta(), loadCodes(), getJSON(`p/${encodeURIComponent(KEY)}.json`), loadHelp()]);
  PL.P = P; PL.S = P.sum;
  footer();
  viewSwitch($('#viewsw'));
  const county = (meta.counties.find(c => c.code === P.c) || {}).name || '';
  PL.county = county;
  document.title = `FIA plot ${P.k}`;
  $('#csv_trees').onclick = () => download(`fia_${P.k}_trees.csv`, treeCsv());
  $('#csv_visits').onclick = () => download(`fia_${P.k}_visits.csv`, visitCsv());
  $('#printbtn').onclick = openPrintDialog;
  PL.hist = buildHistory(P);
  PL.vi = P.v.length - 1;
  // the data can arrive (e.g. from cache) while the scripts after this one (spview.js, expert.js) are still downloading:
  // render only once every page script has run, or Expert view would stay on "Loading…"
  if (document.readyState === 'loading') await new Promise(r => document.addEventListener('DOMContentLoaded', r, { once: true }));
  renderAll();
  window.addEventListener('viewchange', () => { renderAll(); });
  document.body.dataset.ready = '1';
}
function renderAll() {
  const P = PL.P;
  renderHeader(P);
  renderTimeline(P);
  renderSurvey(P);
  renderDetails();
  renderVC(P); renderSpecies(P); renderComp(P); renderIndiv(P);
  renderGrowth(PL.hist); renderMort(PL.hist); renderInvh(P); renderCaveats(P);
  if (isExpert() && window.renderExpert) window.renderExpert(PL);
}

// ---------------------------------------------------------------- 1. header, KPIs, highlights
function renderHeader(P) {
  const S = S_(), pred = S.pred;
  $('#title').innerHTML = `FIA Plot ${esc(P.k)} · ${esc(PL.county)} County, South Carolina`;
  const lastV = P.v[P.v.length - 1];
  const badge = lastV && parseInt(lastV.d, 10) < ACTIVE_FROM ? ` ${histBadge(lastV.d)}` : '';
  const dates = (pred ? pred.v.map(v => `${v.d} (${pred.plot})`) : []).concat(S.v.map(v => v.d));
  $('#subtitle').innerHTML = `STATECD ${P.s} · UNITCD ${P.u} · COUNTYCD ${P.c} · PLOT ${P.p} · surveys: ${dates.map(esc).join(' · ')}${badge}`;
  $('#subtitle2').innerHTML = `Public location ${fmt(P.la, 5)}, ${fmt(P.lo, 5)} (fuzzed) · ${P.v.length} visit${P.v.length > 1 ? 's' : ''} (${esc(P.dsg)}) · owner group ${dvs(decode('COND.OWNGRPCD', P.og), 30)} · latest forest type ${esc(ftName(P.ft) || 'none (no accessible forest)')} · FIADB DataMart CSV, codes from the FIADB User Guide v9.4`;
  $('#printurl').textContent = location.href.split('#')[0];
  const k = S.kpi;
  if (k) {
    const a = S.v[k.a], z = S.v[k.z], pk = S.v[k.pk];
    const tile = (help, l, v, u) => `<div class="kpi"><div class="l">${esc(l)}<button type="button" class="hb" data-h="${help}" aria-label="About ${esc(l)}">ⓘ</button></div><div class="v">${v}</div><div class="u">${u}</div></div>`;
    $('#kpis').innerHTML = tile('d:ba', 'Live basal area', `${fmt(a.ba, 0)} → ${fmt(z.ba, 0)}`, `ft²/ac, ${a.y}–${z.y}${k.pk !== k.a && k.pk !== k.z ? ` (peak ${fmt(pk.ba, 0)} in ${pk.y})` : ''}`)
      + tile('d:c', 'Aboveground carbon', `${fmt(a.c, 1)} → ${fmt(z.c, 1)}`, 'tons C/ac')
      + tile('d:vol', 'Net cubic volume', `${fmt(a.vol, 0)} → ${fmt(z.vol, 0)}`, 'ft³/ac')
      + tile('d:age', 'Stand age', `${fmt(a.age, 0)} → ${fmt(z.age, 0)}`, 'years (COND.STDAGE)');
  } else $('#kpis').innerHTML = '';
  $('#hl').innerHTML = intro('highlights') + (S.hl.length ? `<ul class="hl">${S.hl.map(([b, t]) => `<li><b>${esc(b)}.</b> ${esc(t)}</li>`).join('')}</ul>`
    : '<p>No live trees were tallied at any visit (nonforest or nonsampled plot).</p>');
}

// ---------------------------------------------------------------- 2. timeline (cards with tooltips) + inferred predecessor
function renderTimeline(P) {
  const S = S_(), preds = P.pc || [];
  $('#tlintro').innerHTML = intro('timeline');
  $('#tldesc').innerHTML = `Card styles: solid border = a visit at this location key; blue 2-px border = the visit shown in Visit details (the latest visit when the page opens); `
    + `* after a date = only the month was recorded.` + (preds.length ? ` Dashed cards = periodic plots inferred to be predecessors (not database-linked).` : '')
    + ` Hover, focus or tap a card for details.`;
  const pc = preds.slice(0, 3).map((p, j) => `<div class="tc pred" data-pj="${j}" tabindex="0"><div class="d">${esc(p.last)}</div><div>Periodic plot ${esc(p.key)} · INVYR ${p.invyr}</div>
      <span class="tag">inferred candidate, not database-linked</span><div class="muted">rank ${p.rank} · score ${fmt(p.score, 0)}/100 · ${fmt(p.dist, 2)} mi</div></div>`);
  const vis = P.v.map((v, i) => `<div class="tc${i === PL.vi ? ' sel' : ''}" data-vi="${i}" tabindex="0"><div class="d">${esc(v.d)}${v.da ? '*' : ''}</div>
      <div>INVYR ${v.y} · ${esc(v.ds)}</div><div class="muted">KINDCD ${dvs(decode('PLOT.KINDCD', v.kc))}</div><div class="muted">DESIGNCD ${dvs(decode('PLOT.DESIGNCD', v.dc), 36)}</div>
      <div class="muted">${dvs(decode('PLOT.PLOT_STATUS_CD', v.st), 36)}${v.rp != null ? ` · REMPER ${fmt(v.rp)} yr` : ''}</div></div>`);
  $('#timeline').innerHTML = pc.concat(vis).join('');
  document.querySelectorAll('#timeline .tc').forEach(el => {
    const show = () => showTip(el);
    el.addEventListener('mouseenter', e => { if (matchMedia('(hover: hover)').matches) show(); });
    el.addEventListener('mouseleave', () => { if (!el.dataset.pinned) hideTip(); });
    el.addEventListener('focus', show);
    el.addEventListener('blur', () => { delete el.dataset.pinned; hideTip(); });
    el.addEventListener('click', e => {
      if (el.dataset.vi != null) selectVisit(+el.dataset.vi);
      const target = document.querySelector(el.dataset.vi != null ? `#timeline .tc[data-vi="${el.dataset.vi}"]` : `#timeline .tc[data-pj="${el.dataset.pj}"]`);
      target.dataset.pinned = '1'; showTip(target);
    });
    el.addEventListener('keydown', e => { if (e.key === 'Enter' && el.dataset.vi != null) { selectVisit(+el.dataset.vi); showTip(document.querySelector(`#timeline .tc[data-vi="${el.dataset.vi}"]`)); } if (e.key === 'Escape') hideTip(); });
  });
  if (preds.length) {
    $('#predbox').innerHTML = `<h3>Inferred periodic predecessor candidates (not database-linked)</h3>` + intro('predecessor')
      + `<p class="muted">Periodic plots in the same county within 1.5 mi (public, fuzzed coordinates) whose last measurement date + this plot's first-visit REMPER
      falls within 0.5 yr of the first national-design visit; scored 0–100 from bridge-tree matches (60), date fit (25) and distance (15).</p>`
      + tbl([{ k: 'd:rank' }, { k: 'd:pred_plot' }, { k: 'd:last_measured' }, { k: 'd:ft_age' }, { k: 'd:dist', n: 1 }, { k: 'd:datefit', n: 1 }, { k: 'd:bridge' }, { k: 'd:score', n: 1 }],
        preds.map(p => [p.rank, `<a href="${plotUrl(p.key)}">${esc(p.key)}</a>`, `${esc(p.last)} (INVYR ${p.invyr})`, `${esc(ftName(p.ft))}${p.age != null ? `, ${p.age} yr` : ''}`,
          fmt(p.dist, 2), fmt(p.dt, 2), p.nb ? `<span class="wrapcell">${p.nm} of ${p.nb}${p.pairs ? ': ' + esc(p.pairs) : ''}</span>` : 'no bridge records', fmt(p.score, 0)]), { noMax: true });
  } else if ((P.cf || []).length) {
    $('#predbox').innerHTML = intro('predecessor') + `<p class="muted">This periodic plot is an inferred predecessor candidate (not database-linked) of: ` +
      P.cf.map(c => `<a href="${plotUrl(c.key)}">${esc(c.key)}</a> (rank ${c.rank}, score ${fmt(c.score, 0)})`).join(', ') + '.</p>';
  } else $('#predbox').innerHTML = '';
}
let tipEl = null;
function tipHtml(card) {
  const P = PL.P, S = S_();
  if (card.dataset.pj != null) {
    const p = P.pc[+card.dataset.pj], pv = S.pred && S.pred.key === p.key ? S.pred.v : null, last = pv ? pv[pv.length - 1] : null;
    return `<b>${esc(p.last)}</b> · periodic plot ${esc(p.key)}<br>Design: periodic (older design, INVYR ${p.invyr})<br>`
      + `Stand age ${p.age != null ? fmt(p.age, 0) + ' yr' : '—'}${last ? ` · BA ${fmt(last.ba, 1)} ft²/ac · ${fmt(last.tpa, 0)} trees/ac (periodic design, not comparable)` : ''}`
      + `<div class="st">Dashed border, no fill: a periodic plot this site infers to be a predecessor of this plot (rank ${p.rank}, score ${fmt(p.score, 0)}/100). `
      + `<b>Inferred, not database-linked</b>: PREV_PLT_CN does not link periodic and national-design plots.</div>`;
  }
  const i = +card.dataset.vi, v = P.v[i], s = S.v[i], sel = i === PL.vi;
  return `<b>${esc(v.d)}${v.da ? '*' : ''}</b> · plot ${esc(P.k)} · INVYR ${v.y}<br>Design: ${v.ds === 'annual' ? 'national design (annual inventory)' : 'periodic (older design)'} — ${esc(dvs(decode('PLOT.DESIGNCD', v.dc), 60).replace(/<[^>]+>/g, ''))}<br>`
    + `Stand age ${fmt(s.age, 0)} yr · BA ${fmt(s.ba, 1)} ft²/ac · ${fmt(s.tpa, 0)} trees/ac`
    + `<div class="st">Solid border: a visit recorded at this location key.${sel ? ' Blue 2-px border: the visit shown in Visit details' + (i === P.v.length - 1 ? ' (the latest visit, selected when the page opens).' : ' (selected).') : ' Click or tap to show it in Visit details.'}`
    + `${v.da ? ' * after the date: only the month was recorded (DATE_APPROX).' : ''}</div>`;
}
function showTip(card) {
  if (!tipEl) { tipEl = document.createElement('div'); tipEl.id = 'tltip'; tipEl.setAttribute('role', 'tooltip'); document.body.append(tipEl); }
  tipEl.innerHTML = tipHtml(card); tipEl.hidden = false;
  card.setAttribute('aria-describedby', 'tltip');
  const r = card.getBoundingClientRect(), w = Math.min(340, innerWidth - 16);
  tipEl.style.width = w + 'px';
  tipEl.style.left = (Math.max(8, Math.min(innerWidth - w - 8, r.left)) + scrollX) + 'px';
  tipEl.style.top = (r.bottom + 6 + scrollY) + 'px';
}
function hideTip() { if (tipEl) tipEl.hidden = true; document.querySelectorAll('#timeline .tc[aria-describedby]').forEach(c => c.removeAttribute('aria-describedby')); }
document.addEventListener('click', e => { if (tipEl && !tipEl.hidden && !e.target.closest('#timeline .tc') && !tipEl.contains(e.target)) { document.querySelectorAll('#timeline .tc').forEach(c => delete c.dataset.pinned); hideTip(); } });

// ---------------------------------------------------------------- 3. survey summary + tree totals (PDF page 2)
function renderSurvey(P) {
  const S = S_(), pred = S.pred, f = (v, d) => fmt(v, d);
  const rows = [];
  if (pred) pred.v.forEach(v => rows.push({ attrs: ` class="predrow" data-pred="${v.y}"`, cells: [`<b>${esc(v.d)}</b><br><span class="tag">plot ${pred.plot}: inferred, not database-linked</span>`,
    f(v.age, 0), esc(ftName(v.ft).split(' = ').pop()), f(v.tpa5, 0) + '†', f(v.sap, 0) + '†', `<span data-ba="${v.ba}">${f(v.ba, 1)}†</span>`, f(v.qmd, 1) + '†', f(v.vol, 0) + '†', f(v.c, 1) + '†',
    `${v.nd}; ${v.cut} cut`, '—'] }));
  S.v.forEach((v, i) => {
    const dg = v.ds === 'periodic' ? '†' : '';
    rows.push({ attrs: ` data-invyr="${v.y}"`, cells: [`<b>${esc(v.d)}</b><br><span class="muted">Plot ${PL.P.p}, INVYR ${v.y}</span>`, f(v.age, 0), esc(ftName(v.ft).split(' = ').pop() || '—'),
      f(v.tpa5, 0) + dg, f(v.sap, 0) + dg, `<span data-ba="${v.ba ?? ''}">${f(v.ba, 1)}${dg}</span>`, f(v.qmd, 1) + dg, f(v.vol, 0) + dg, f(v.c, 1) + dg,
      (i ? `${v.nd} (${v.newd} new)` : `${v.nd}`) + (v.cut ? `; ${v.cut} cut` : ''), i ? `${v.ing}${v.add ? ` + ${v.add}*` : ''}` : '—'] });
  });
  const anyPer = (pred && pred.v.length) || S.v.some(v => v.ds === 'periodic');
  const foot = [anyPer ? `† Periodic design${pred ? ` (periodic plot ${pred.plot} used variable-radius points)` : ''}: per-acre values are not comparable with national-design visits.` : '',
    pred ? `The ${pred.v.map(v => v.d).join(' and ')} rows are periodic plot ${pred.plot}, the inferred predecessor (not database-linked).` : '',
    'Dead trees = standing-dead trees tallied (in brackets: newly dead since the previous visit' + (pred ? '; for periodic rows also the trees recorded cut' : '') + ').',
    'New trees = ingrowth (RECONCILECD 1); * = other additions (e.g., RECONCILECD 3 after a microplot move), not ingrowth.',
    'Saplings = live trees 1.0–4.9 in. QMD includes all live trees ≥1.0 in. Per-acre values are for live trees unless stated.'].filter(Boolean).join(' ');
  $('#survey').innerHTML = intro('survey') + tbl([{ k: 'd:survey' }, { k: 'd:age', n: 1 }, { k: 'd:fortyp' }, { k: 'd:tpa5', n: 1 }, { k: 'd:sap', n: 1 }, { k: 'd:ba', n: 1 },
    { k: 'd:qmd', n: 1 }, { k: 'd:vol', n: 1 }, { k: 'd:c', n: 1 }, { k: 'd:dead_new' }, { k: 'd:newtrees' }], rows, { cls: 'survey', id: 'totals', foot, noMax: true });
  $('#treetot').innerHTML = intro('treetot') + tbl([{ k: 'd:invyr' }, { k: 'd:survey' }, { k: 'd:n_live', n: 1 }, { k: 'd:n5', n: 1 }, { k: 'd:nsap', n: 1 }, { k: 'd:n_dead', n: 1 },
    { k: 'd:dead_tpa', n: 1 }, { k: 'd:newly_dead', n: 1 }, { k: 'd:ingrowth', n: 1 }, { k: 'd:added', n: 1 }],
    S.v.map((v, i) => [v.y, esc(v.d), v.nl, v.n5, v.ns, v.nd, fmt(v.dtpa, 0), i ? v.newd : '—', i ? v.ing : '—', i ? v.add : '—']), { id: 'treetot_t', noMax: true });
}

// ---------------------------------------------------------------- 4. visit details: every section expanded
const DSECT = [['cond', 'Conditions'], ['metrics', 'Stand metrics'], ['species_v', 'Species'], ['trees', 'Trees'], ['seed', 'Seedlings'], ['site', 'Site trees'],
  ['veg', 'P2 vegetation'], ['inv', 'Invasives'], ['dwm', 'Down woody material'], ['soils', 'Soils'], ['plotrec', 'PLOT record']];
const forVisit = (b, vi) => rowsOf(b).filter(r => r.vi === vi);
function selectVisit(vi) {
  PL.vi = vi;
  document.querySelectorAll('#timeline .tc[data-vi]').forEach(el => el.classList.toggle('sel', +el.dataset.vi === vi));
  renderDetails();
  if (isExpert() && window.renderExpert) window.renderExpert(PL);
}
function fieldsHtml(table, rec) {
  return `<div class="fields">${Object.entries(rec).filter(([c, v]) => c !== 'vi' && v !== null).map(([c, v]) => { const h = helpFor(`${table}.${c}`);
    const lab = isExpert() || !h ? c : h.label;
    return `<div><b>${esc(lab)}</b>${lab !== c ? ` <small class="thc" style="display:inline">${esc(c)}</small>` : ''}<button type="button" class="hb" data-h="${esc(table + '.' + c)}" aria-label="About ${esc(c)}">ⓘ</button>: ${dv(decodeCell(table, c, v))}</div>`; }).join('')}</div>`;
}
function genericTable(b, table, vi) {
  const rows = forVisit(b, vi);
  if (!rows.length) return '';
  const cols = b.c.filter(c => c !== 'vi' && rows.some(r => r[c] !== null));
  const num = c => rows.some(r => typeof r[c] === 'number') && !isCoded(table, c) && !(c in REF_CODED);
  return `<h4>${esc(table)} (${rows.length})</h4>` + tbl(cols.map(c => ({ k: `${table}.${c}`, n: num(c) })), rows.map(r => cols.map(c => cell(table, c, r[c]))),
    { wrapCls: 'wide', cls: 'wide', sort: true, sticky: true });
}
function detailSection(key, vi) {
  const P = PL.P, v = P.v[vi], s = S_().v[vi];
  if (key === 'cond') {
    const c = forVisit(P.cn, vi);
    if (!c.length) return '';
    const short = (col, v) => { const x = cell('COND', col, v); return x.v == null ? '' : String(x.v); };
    const line = r => [`Condition ${r.CONDID ?? ''}`, r.CONDPROP_UNADJ != null ? `${Math.round(r.CONDPROP_UNADJ * 100)}% of plot` : '',
      short('COND_STATUS_CD', r.COND_STATUS_CD).replace(/ land$/, ''), short('OWNGRPCD', r.OWNGRPCD), r.FORTYPCD != null ? (FIA.codes.ft[r.FORTYPCD] || '') : '',
      r.STDAGE != null ? `Stand age ${r.STDAGE}` : '',
      r.SICOND != null ? `Site index ${r.SICOND}` + (r.SISP != null || r.SIBASE != null ? ` (${[r.SISP != null ? spName(r.SISP) : '', r.SIBASE != null ? `base ${r.SIBASE}` : ''].filter(Boolean).join(', ')})` : '') : '']
      .filter(Boolean).join(' · ');
    return collapsible('cond', c.map(r => `<p class="condline">${esc(line(r))}</p>`).join(''), 'condition fields',
      c.map(r => `<h4>Condition ${r.CONDID ?? ''}</h4>${fieldsHtml('COND', r)}`).join(''));
  }
  if (key === 'plotrec') {
    const r = forVisit(P.pf, vi)[0];
    if (!r) return '';
    const sh = col => { const x = cell('PLOT', col, r[col]); return x.v == null ? '' : String(x.v); };
    // short forms of the decoded User Guide text ("Remeasurement of previously installed ..." -> "Remeasurement")
    const full = col => { const d = decode('PLOT.' + col, r[col]); return d.status === 'decoded' ? d.text.replace(/^[^=]*=\s*/, '') : ''; };
    const ps = full('PLOT_STATUS_CD'), ml = full('MICROPLOT_LOC');
    const status = /^Sampled/.test(ps) ? (/no accessible forest/i.test(ps) ? 'Sampled, no accessible forest' : /accessible forest/i.test(ps) ? 'Sampled, accessible forest present' : 'Sampled') : sh('PLOT_STATUS_CD');
    const micro = /offset/i.test(ml) ? 'Microplot offset from subplot center' : /at the subplot center/i.test(ml) ? 'Microplot at subplot center' : (ml ? `Microplot: ${ml.replace(/\.$/, '')}` : '');
    const line = [`Measured ${v.d}${v.da ? ' (month only)' : ''}`, `INVYR ${v.y}`, (full('KINDCD') || sh('KINDCD')).split(' of ')[0].replace(/\.$/, ''), v.ds === 'annual' ? 'National design' : 'Periodic design',
      status, r.REMPER != null ? `${fmt(r.REMPER, 1)} yr since the previous measurement` : '', r.MICROPLOT_LOC != null ? micro : '']
      .filter(Boolean).join(' · ');
    return collapsible('plotrec', `<p class="condline">${esc(line)}</p>`, 'PLOT record fields', fieldsHtml('PLOT', r));
  }
  if (key === 'metrics') {
    const k = (h, l, val, u) => `<div class="kpi"><div class="l">${l}<button type="button" class="hb" data-h="${h}" aria-label="About ${l}">ⓘ</button></div><div class="v">${val}</div><div class="u">${u}</div></div>`;
    const m = key_ => met(v, key_);
    let html = `<div class="kpis">${k('d:ba', 'Live basal area', fmt(s.ba), 'ft²/ac')}${k('d:tpa', 'Live trees', fmt(s.tpa, 0), `trees/ac (${s.nl} tallied)`)}
      ${k('d:tpa5', 'Trees ≥5 in', fmt(s.tpa5, 0), 'trees/ac')}${k('d:sap', 'Saplings 1–4.9 in', fmt(s.sap, 0), 'trees/ac')}${k('d:qmd', 'QMD', fmt(s.qmd), 'in')}
      ${k('d:vol', 'Net cubic volume', fmt(s.vol, 0), 'ft³/ac')}${k('d:c', 'Aboveground carbon', fmt(s.c, 2), 'tons C/ac')}${k('d:dead_tpa', 'Standing dead', fmt(s.dtpa, 0), `trees/ac (${s.nd} tallied)`)}</div>`;
    if (m('live_tpa_c1') != null) html += `<h4>Trees per acre by size class</h4>` + tbl([{ k: 'd:status' }, { k: 'd:c1', n: 1 }, { k: 'd:c2', n: 1 }, { k: 'd:c3', n: 1 }, { k: 'd:c4', n: 1 }],
      [['Live'].concat(['c1', 'c2', 'c3', 'c4'].map(c => ({ h: fmt(m('live_tpa_' + c), 1), v: m('live_tpa_' + c) }))),
       ['Standing dead'].concat(['c1', 'c2', 'c3', 'c4'].map(c => ({ h: fmt(m('dead_tpa_' + c), 1), v: m('dead_tpa_' + c) })))], { noMax: true, sort: true, sticky: true });
    return html + `<p class="muted">${esc(FIA.meta.unadj_note)}</p>`;
  }
  if (key === 'species_v') {
    let sp = forVisit(P.sp, vi).sort((a, b) => (b.ba || 0) - (a.ba || 0));
    if (!sp.length && S_().sp) {        // periodic visits: from the summary's species table
      const SP = S_().sp;
      sp = SP.codes.map((c, j) => ({ SPCD: c, ba: SP.ba[j][vi], tpa5: SP.tpa5[j][vi], vol: SP.vol[j][vi], carbon: SP.c[j][vi] })).filter(x => x.ba);
    }
    if (!sp.length) return '';
    const tot = sp.reduce((a, s_) => a + (s_.ba || 0), 0);
    const nv = (v, d) => ({ h: fmt(v, d), v: v ?? null });
    return tbl([{ k: 'd:species' }, { k: 'd:live_n_sp', n: 1 }, { k: 'd:tpa', n: 1 }, { k: 'd:tpa5', n: 1 }, { k: 'd:ba', n: 1 }, { k: 'd:pct_ba', n: 1 }, { k: 'd:vol', n: 1 },
      { k: 'd:c', n: 1 }, { k: 'd:dead_n_sp', n: 1 }, { k: 'd:dead_tpa_sp', n: 1 }],
      sp.map(x => [{ h: esc(spName(x.SPCD)) + (isExpert() ? ` <span class="muted">(${x.SPCD})</span>` : ''), v: spName(x.SPCD) }, { h: x.live_n ?? '—', v: x.live_n ?? null },
        nv(x.live_tpa, 1), nv(x.tpa5, 1), nv(x.ba, 2), nv(tot ? 100 * (x.ba || 0) / tot : null, 1), nv(x.vol, 0), nv(x.carbon, 2), { h: x.dead_n ?? '—', v: x.dead_n ?? null }, nv(x.dead_tpa, 1)]),
      { sort: true, sticky: true });
  }
  if (key === 'trees') {
    const cols = ['SUBP', 'TREE', 'STATUSCD', 'SPCD', 'DIA', 'HT', 'ACTUALHT', 'CR', 'CCLCD', 'TREECLCD', 'AGENTCD', 'DAMAGE_AGENT_CD1', 'DECAYCD', 'MORTYR', 'RECONCILECD', 'TPA_UNADJ', 'VOLCFNET', 'CARBON_AG'];
    const NUMC = new Set(['SUBP', 'TREE', 'DIA', 'HT', 'ACTUALHT', 'CR', 'MORTYR', 'TPA_UNADJ', 'VOLCFNET', 'CARBON_AG']);
    // bridge records (SUBP > 4 at national-design visits, P2A_GRM_FLG) are not tallied trees: left out here, kept in Expert view
    const notBridge = t => !(t.SUBP > 4 && P.v[t.vi].ds === 'annual');
    const all = rowsOf(P.tr).filter(notBridge);
    const tr = (PL.allTrees ? all : all.filter(t => t.vi === vi)).sort((a, b) => P.v[a.vi].y - P.v[b.vi].y || a.SUBP - b.SUBP || a.TREE - b.TREE);
    if (!all.length) return '';
    const nb = rowsOf(P.tr).length - all.length;
    return `<div class="actions noprint"><label class="switch"><input type="checkbox" id="alltrees"${PL.allTrees ? ' checked' : ''}> Show all surveys</label>`
      + `<span class="muted" id="trees_n">${tr.length} tree record${tr.length === 1 ? '' : 's'}${PL.allTrees ? ` from ${P.v.length} surveys` : ' at this visit'}`
      + `${nb ? `; ${nb} bridge record${nb > 1 ? 's' : ''} (SUBP &gt; 4, not tallied trees) shown in Expert view only` : ''}</span></div>`
      + (tr.length ? tbl([{ k: 'd:invyr', l: 'Survey year' }].concat(cols.map(c => ({ k: 'TREE.' + c, n: NUMC.has(c) }))).concat([{ k: 'd:ba_tree', n: 1 }, { k: 'd:linked' }]),
        tr.map(t => { const ba = t.DIA != null && t.TPA_UNADJ != null ? BA_K * t.DIA ** 2 * t.TPA_UNADJ : null;
          return [{ h: `<abbr title="${esc(P.v[t.vi].d)}">${P.v[t.vi].y}</abbr>`, v: P.v[t.vi].y }].concat(cols.map(c => cell('TREE', c, t[c])))
            .concat([{ h: fmt(ba, 3), v: ba }, { h: t.pv ? 'yes' : '', v: t.pv ? 'yes' : '' }]); }),
        { wrapCls: 'wide', cls: 'wide trees', id: 'vd_trees', sort: true, sticky: true }) : '<p class="muted">No tree records at this visit.</p>');
  }
  if (key === 'seed') return genericTable(P.sd, 'SEEDLING', vi);
  if (key === 'site') {
    const t = genericTable(P.st, 'SITETREE', vi);
    if (!t) return '';
    const yrs = [...new Set(forVisit(P.st, vi).map(r => r.YEAR_AGE_TAKEN).filter(x => x != null))];
    return `<p class="muted" id="coreyear">Year the core was taken (YEAR_AGE_TAKEN, User Guide §3.10.46): `
      + (yrs.length ? `<b>${yrs.sort().join(', ')}</b>.` : `not recorded for these site trees; they belong to the ${esc(v.d)} visit.`) + `</p>` + t;
  }
  if (key === 'veg') return genericTable(P.p2s, 'P2VEG_SUBP_STRUCTURE', vi) + genericTable(P.p2v, 'P2VEG_SUBPLOT_SPP', vi);
  if (key === 'inv') return invVisit(P, vi);
  if (key === 'dwm') return Object.entries(P.dwm || {}).map(([t, b]) => genericTable(b, t, vi)).join('');
  if (key === 'soils') return Object.entries(P.so || {}).map(([t, b]) => genericTable(b, t, vi)).join('');
  return '';
}
function invVisit(P, vi) {
  const iv = forVisit(P.iv, vi), by = {};
  iv.forEach(r => (by[r.VEG_SPCD] = by[r.VEG_SPCD] || []).push(r));
  const pf = forVisit(P.pf, vi)[0] || {};
  if (!iv.length && pf.INVASIVE_SAMPLING_STATUS_CD == null) return '';
  return `<p>Invasive sampling: ${dv(decode('PLOT.INVASIVE_SAMPLING_STATUS_CD', pf.INVASIVE_SAMPLING_STATUS_CD))}</p>` + (iv.length ? tbl([{ k: 'd:inv_species' }, { k: 'd:inv_symbol' }, { k: 'd:inv_subp' }, { k: 'd:inv_cover', n: 1 }],
    Object.entries(by).map(([s, g]) => { const [cn, sci] = plant(s), cov = g.reduce((a, r) => a + (r.COVER_PCT || 0), 0) / g.length;
      return [{ h: `${esc(cn)} <i class="muted">${esc(sci)}</i>`, v: cn }, esc(s), g.map(r => r.SUBP).sort().join(', '), { h: fmt(cov), v: cov }]; }), { noMax: true, sort: true, sticky: true })
    : '<p class="muted">No invasive plant records for this visit.</p>');
}
// Conditions and the PLOT record: collapsed by default to a one-line summary; the state lives in this page view and in the
// URL hash (#cond-open, #plot-open) so a shared link can open them; print expands both
const COLL = { cond: 'cond-open', plotrec: 'plot-open' };
const hashParts = () => location.hash.slice(1).split('&').filter(Boolean);
PL.open = Object.fromEntries(Object.entries(COLL).map(([k, t]) => [k, hashParts().includes(t)]));
function collapsible(k, summary, what, body) {
  const open = !!PL.open[k];
  return `<div class="condsum">${summary}</div><button type="button" class="linkbtn noprint" id="${k}toggle" aria-expanded="${open}" aria-controls="${k}fields">`
    + `${open ? 'Hide ' + what : 'Show all ' + what}</button><div id="${k}fields" class="collfields"${open ? '' : ' hidden'}>${body}</div>`;
}
function toggleSect(k) {
  PL.open[k] = !PL.open[k];
  const u = new URL(location.href), parts = hashParts().filter(x => x !== COLL[k]);
  if (PL.open[k]) parts.push(COLL[k]);
  u.hash = parts.join('&');
  history.replaceState(null, '', u.hash ? u : u.pathname + u.search);
  const y = scrollY; renderDetails(); scrollTo(0, y);
}
function renderDetails() {
  const P = PL.P, vi = PL.vi, v = P.v[vi];
  $('#detintro').innerHTML = intro('details');
  $('#vsel').textContent = `— ${v.d} (INVYR ${v.y}, ${v.ds})`;
  const pick = $('#vpick');
  pick.innerHTML = P.v.map((x, i) => `<option value="${i}"${i === vi ? ' selected' : ''}>${esc(x.d)} · INVYR ${x.y}</option>`).join('');
  pick.onchange = () => selectVisit(+pick.value);
  const absent = [];
  let html = '';
  const inExpert = isExpert() ? new Set(['cond', 'trees', 'plotrec']) : new Set();   // Expert panels show these in full
  if (inExpert.size) html += `<p class="muted">Conditions, Trees and the PLOT record are in the Expert panels below.</p>`;
  for (const [k, title] of DSECT) {
    if (inExpert.has(k)) continue;
    const body = detailSection(k, vi);
    if (!body) { absent.push(title); continue; }
    html += `<div class="vsect" data-ds="${k}"><h3>${esc(title)}</h3>${intro(k)}${body}</div>`;
  }
  if (absent.length) html += `<p class="absent">No records at this visit: ${absent.map(esc).join(', ')}.</p>`;
  $('#details').innerHTML = html;
  for (const k of Object.keys(COLL)) {
    const h = document.querySelector(`.vsect[data-ds=${k}] > h3`);
    if (h) { const title = h.textContent;
      h.innerHTML = `<button type="button" class="secttoggle" aria-expanded="${!!PL.open[k]}" aria-controls="${k}fields">${PL.open[k] ? '▾' : '▸'} ${esc(title)}</button>`;
      h.querySelector('button').onclick = () => toggleSect(k); }
    const t = document.getElementById(k + 'toggle'); if (t) t.onclick = () => toggleSect(k);
  }
  const at = $('#alltrees'); if (at) at.onchange = () => { PL.allTrees = at.checked; const y = scrollY; renderDetails(); scrollTo(0, y); };
  updateFades($('#details'));
}

// ---------------------------------------------------------------- shared species grouping for the stacked charts (PDF: top 7 + other)
function spGroups() {
  const S = S_();
  if (!S.sp) return null;
  const top = S.top, order = top.map(spName).concat(S.sp.codes.length > top.length ? ['Other species'] : []);
  const col = Object.fromEntries(order.map((g, i) => [g, i < top.length ? PAL[i] : OTHER]));
  const grp = c => top.includes(c) ? spName(c) : 'Other species';
  const by = m => { const o = Object.fromEntries(order.map(g => [g, S.v.map(() => 0)])); S.sp.codes.forEach((c, j) => S.sp[m][j].forEach((x, i) => { o[grp(c)][i] += x || 0; })); return o; };
  return { order, col, by, nother: S.sp.codes.length - top.length };
}
function stackChart(id, m, title, dec, totals) {
  const S = S_(), G = spGroups(), X = S.v.map(v => String(v.y)), data = G.by(m);
  const lab = g => g === 'Other species' ? `Other species (${G.nother})` : g;
  const tr = G.order.map(g => ({ x: X, y: data[g], name: lab(g), type: 'scatter', mode: 'lines', stackgroup: 'one', line: { width: 0.5, color: G.col[g] }, fillcolor: G.col[g],
    hovertemplate: `${esc(lab(g))}: %{y:.2f}<extra></extra>` }));
  tr.push({ x: X, y: totals, mode: 'markers+text', text: totals.map(v => fmt(v, dec)), textposition: 'top center', marker: { size: 1, color: 'rgba(0,0,0,0)' }, showlegend: false,
    hovertemplate: 'Total %{y:.2f}<extra></extra>', type: 'scatter' });
  Plotly.react(id, tr, lay({ title: { text: title, x: 0 }, xaxis: { type: 'category', title: 'INVYR' }, yaxis: { range: [0, Math.max(...totals, 1e-9) * 1.18] }, hovermode: 'x unified' }), plotCfg);
}
// species x survey table; cols per survey from fns
function spTable(fields, foot) {
  const S = S_(), Y = S.v.map(v => v.y), SP = S.sp;
  const cols = [{ k: 'd:species' }].concat(Y.flatMap(y => fields.map(f => ({ k: f.k, l: `${f.l} ${y}`, n: 1 }))));
  const rows = SP.codes.map((c, j) => [esc(spName(c))].concat(Y.flatMap((y, i) => fields.map(f => fmt(SP[f.m][j][i], f.d)))));
  rows.push(['<b>All species</b>'].concat(Y.flatMap((y, i) => fields.map(f => `<b>${f.tot ? f.tot(i) : fmt(SP.codes.reduce((a, c, j) => a + (SP[f.m][j][i] || 0), 0), f.d)}</b>`))));
  return tbl(cols, rows, { cls: 'wide sp', foot, noMax: true });
}

// ---------------------------------------------------------------- 5. volume and carbon (PDF page 3)
function renderVC(P) {
  const S = S_();
  if (!S.sp) { $('#vc').innerHTML = intro('vc') + '<p class="muted">No live trees were tallied at any visit.</p>'; return; }
  $('#vc').innerHTML = intro('vc') + `<div class="grid2"><div id="c_vol" class="chart"></div><div id="c_c" class="chart"></div></div>`
    + spTable([{ k: 'd:vol_y', l: 'Vol', m: 'vol', d: 0, tot: i => fmt(S.v[i].vol, 0) }], 'Vol = net cubic volume ft³/ac (VOLCFNET × TPA_UNADJ); volume exists only for trees ≥5.0 in.')
    + spTable([{ k: 'd:c_y', l: 'C', m: 'c', d: 2, tot: i => fmt(S.v[i].c, 2) }], 'C = aboveground carbon tons/ac (CARBON_AG × TPA_UNADJ ÷ 2000); carbon includes saplings.');
  stackChart('c_vol', 'vol', 'Net cubic volume (ft³/ac)', 0, S.v.map(v => v.vol || 0));
  stackChart('c_c', 'c', 'Aboveground carbon (tons C/ac)', 1, S.v.map(v => v.c || 0));
}

// ---------------------------------------------------------------- 6. species: BA by species chart + table + drop explanation (PDF page 4)
function renderSpecies(P) {
  const S = S_();
  if (!S.sp) { $('#species').innerHTML = intro('species') + '<p class="muted">No live trees were tallied at any visit.</p>'; return; }
  $('#species').innerHTML = intro('species') + `<div id="c_stack" class="chart"></div>`
    + spTable([{ k: 'd:ba_y', l: 'BA', m: 'ba', d: 1, tot: i => fmt(S.v[i].ba, 1) }, { k: 'd:tpa5_y', l: 'TPA≥5', m: 'tpa5', d: 0, tot: i => fmt(S.v[i].tpa5, 0) }, { k: 'd:pct_ba', l: '%BA', m: 'pct', d: 0, tot: () => '100' }],
      'BA = live basal area ft²/ac (all live trees ≥1.0 in); TPA ≥5 = live trees/ac ≥5.0 in DBH; %BA = share of live basal area.')
    + (S.drops.length ? `<div id="drops">${S.drops.map(t => `<p>${esc(t)}</p>`).join('')}</div>` : `<p id="drops" class="muted">Live basal area did not fall between consecutive surveys.</p>`);
  stackChart('c_stack', 'ba', 'Live basal area by species (ft²/ac)', 0, S.v.map(v => v.ba || 0));
}

// ---------------------------------------------------------------- 7. composition: one 100% bar per survey, species grouped by genus
const GENUS_LABEL = { Pinus: 'pines', Quercus: 'oaks', Liquidambar: 'sweetgum', Juniperus: 'redcedars', Ulmus: 'elms', Liriodendron: 'yellow-poplar', Acer: 'maples',
  Nyssa: 'tupelos', Taxodium: 'baldcypress', Carya: 'hickories', Fraxinus: 'ashes', Prunus: 'cherries', Celtis: 'hackberries', Platanus: 'sycamore', Magnolia: 'magnolias',
  Ilex: 'hollies', Cornus: 'dogwoods', Diospyros: 'persimmon', Robinia: 'locusts', Fagus: 'beech', Betula: 'birches', Salix: 'willows', Populus: 'cottonwoods', Juglans: 'walnuts',
  Oxydendrum: 'sourwood', Sassafras: 'sassafras', Persea: 'redbay', Gleditsia: 'honeylocust', Morus: 'mulberries', Tsuga: 'hemlocks', Chamaecyparis: 'cedars' };
const SOFT = new Set(['Pinus', 'Juniperus', 'Taxodium', 'Tsuga', 'Chamaecyparis', 'Abies', 'Picea', 'Thuja']);
const genus = c => ((FIA.codes.sp[c] || [])[1] || '').split(' ')[0] || '?';
function compGroups() {
  const S = S_(), SP = S.sp, named = (FIA.meta.comp || ['Pinus', 'Quercus', 'Liquidambar', 'Juniperus', 'Ulmus']).slice();
  const totals = SP.codes.map((c, j) => SP.ba[j].reduce((a, x) => a + (x || 0), 0));
  const top3 = SP.codes.slice(0, 3);
  const groups = {}, order = [];
  const add = (id, label, color) => { if (!groups[id]) { groups[id] = { id, label, color, codes: [] }; order.push(id); } return groups[id]; };
  SP.codes.forEach((c, j) => {
    const g = genus(c);
    let id;
    if (named.includes(g)) id = 'g:' + g;
    else if (top3.includes(c)) id = 's:' + c;
    else id = SOFT.has(g) ? 'other-soft' : 'other-hard';
    add(id, '', null).codes.push(c);
  });
  // labels: a genus group with one species present is named by that species; colours follow the statewide genus order
  const used = new Set();
  for (const id of order) { const G = groups[id];
    if (id.startsWith('g:')) { const g = id.slice(2); G.label = G.codes.length === 1 ? spName(G.codes[0]) : (GENUS_LABEL[g] || g + ' spp.'); G.color = PAL[named.indexOf(g) % PAL.length]; used.add(G.color); }
    else if (id.startsWith('s:')) G.label = spName(+id.slice(2));
    else if (id === 'other-hard') { G.label = 'other hardwoods'; G.color = OTHER; }
    else { G.label = 'other softwoods'; G.color = '#c9c8c2'; } }
  for (const id of order) if (id.startsWith('s:')) { groups[id].color = PAL.find(c => !used.has(c)) || '#0d8a8a'; used.add(groups[id].color); }
  const rank = id => id.startsWith('g:') ? named.indexOf(id.slice(2)) : id.startsWith('s:') ? 50 : id === 'other-soft' ? 98 : 99;
  order.sort((a, b) => rank(a) - rank(b));
  return order.map(id => groups[id]);
}
function renderComp(P) {
  const S = S_();
  if (!S.sp) { $('#comp').innerHTML = intro('comp') + '<p class="muted">No live trees were tallied at any visit.</p>'; return; }
  const SP = S.sp, groups = compGroups(), idx = Object.fromEntries(SP.codes.map((c, j) => [c, j]));
  const share = (G, i) => { const tot = S.v[i].ba || 0; return tot ? 100 * G.codes.reduce((a, c) => a + (SP.ba[idx[c]][i] || 0), 0) / tot : 0; };
  const surveys = S.v.map((v, i) => i).filter(i => S.v[i].ba > 0);
  const bars = surveys.map(i => `<div class="compbar" data-y="${S.v[i].y}"><div>${esc(S.v[i].d)}</div><div class="bar" role="img" aria-label="${esc(S.v[i].d)}: ` +
    groups.map(G => `${G.label} ${share(G, i).toFixed(0)}%`).join(', ') + `">` +
    groups.map(G => { const p = share(G, i); return p > 0 ? `<div class="seg${LIGHT.has(G.color) ? ' dk' : ''}" style="width:${p}%;background:${G.color}" title="${esc(G.label)}: ${p.toFixed(1)}%">${p >= 7 ? p.toFixed(0) + '%' : ''}</div>` : ''; }).join('') +
    '</div></div>').join('');
  let cap = '';
  if (surveys.length >= 2) {
    const a = surveys[0], z = surveys[surveys.length - 1];
    const ch = groups.map(G => ({ G, a: share(G, a), z: share(G, z) })).filter(x => Math.abs(x.z - x.a) >= 3).sort((p, q) => Math.abs(q.z - q.a) - Math.abs(p.z - p.a)).slice(0, 4);
    cap = ch.length ? `From ${S.v[a].y} to ${S.v[z].y}: ` + ch.map(x => `${x.G.label} ${x.a.toFixed(0)}% → ${x.z.toFixed(0)}%`).join(', ') + ' of live basal area.'
      : `Group shares changed by less than 3 percentage points between ${S.v[a].y} and ${S.v[z].y}.`;
  }
  $('#comp').innerHTML = intro('comp') + `<div class="complegend">${groups.map(G => `<span style="--c:${G.color}">${esc(G.label)}</span>`).join('')}</div>${bars}`
    + `<p id="compcap">${esc(cap)}</p><p class="muted">Groups: species grouped by genus; genera that lead plots statewide get their own group, and this plot's three leading species are never folded into “other”. Segments under 7% are unlabelled (hover for the value).</p>`;
}

// ---------------------------------------------------------------- 8. individual trees: small multiples + sortable table
function treeData() {
  const P = PL.P, H = PL.hist;
  const gr = rowsOf(P.gr), g = {};
  gr.forEach(x => (g[x.ti] = g[x.ti] || []).push(x.gd));
  return H.trees.map(t => ({ ...t, g: g[t.ti] ? g[t.ti].reduce((a, x) => a + x, 0) / g[t.ti].length : null,
    last: t.pts.filter(p => p.dia != null).slice(-1)[0] || null }));
}
const FATE = t => { const l = t.pts[t.pts.length - 1]; return l.st === 1 ? 'live' : l.st === 2 ? 'dead' : l.st === 3 ? 'cut' : 'removed'; };
function smPanel(sp, trees, xr, ymax) {
  const W = 240, Hh = 150, L = 30, R = 16, T = 8, B = 20;
  const x = y => L + (W - L - R) * (y - xr[0]) / Math.max(1, xr[1] - xr[0]), y = d => T + (Hh - T - B) * (1 - d / ymax);
  let g = `<line class="ax" x1="${L}" y1="${T}" x2="${L}" y2="${Hh - B}"/><line class="ax" x1="${L}" y1="${Hh - B}" x2="${W - R}" y2="${Hh - B}"/>`;
  for (let d = 0; d <= ymax; d += ymax > 20 ? 10 : 5) g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(d)}" y2="${y(d)}"/><text x="${L - 3}" y="${y(d) + 3}" text-anchor="end">${d}</text>`;
  g += `<line x1="${L}" x2="${W - R}" y1="${y(5)}" y2="${y(5)}" stroke="var(--muted)" stroke-dasharray="2 3"/>`;
  [xr[0], xr[1]].forEach(yy => { g += `<text x="${x(yy)}" y="${Hh - 6}" text-anchor="middle">${yy}</text>`; });
  for (const t of trees) {
    const pts = t.pts.filter(p => p.dia != null), fate = FATE(t);
    if (!pts.length) continue;
    const ttl = `${t.id} ${t.sp}: ` + pts.map(p => `${fmt(p.dia, 1)} in (${p.y})`).join(' → ') + `; ${t.fate}`;
    let seg = '';
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i], dead = b.st !== 1;
      seg += `<line x1="${x(a.y)}" y1="${y(a.dia)}" x2="${x(b.y)}" y2="${y(b.dia)}" stroke="${dead ? '#8a8984' : '#2a78d6'}" stroke-width="1.6"${a.dia < 5 ? ' stroke-dasharray="3 2"' : ''}/>`;
    }
    const e = pts[pts.length - 1], ex = x(e.y), ey = y(e.dia);
    const mk = fate === 'live' ? `<circle cx="${ex}" cy="${ey}" r="3" fill="#2a78d6"/>` : fate === 'dead' ? `<path d="M${ex - 3} ${ey - 3}L${ex + 3} ${ey + 3}M${ex - 3} ${ey + 3}L${ex + 3} ${ey - 3}" stroke="#b3261e" stroke-width="1.8"/>`
      : fate === 'cut' ? `<rect x="${ex - 3}" y="${ey - 3}" width="6" height="6" fill="#52514e"/>` : `<circle cx="${ex}" cy="${ey}" r="3" fill="none" stroke="#52514e" stroke-width="1.4"/>`;
    g += `<g><title>${esc(ttl)}</title>${seg}${pts.length === 1 && fate === 'live' ? '' : ''}${mk}</g>`;
  }
  // click / tap / Enter opens the full-size view (spview.js)
  const code = trees.length ? trees[0].pts[trees[0].pts.length - 1].spcd : '';
  return `<figure class="smz" tabindex="0" role="button" data-sp="${code}" aria-label="${esc(sp)}: enlarge the diameter chart of ${trees.length} trees">`
    + `<span class="smcue noprint" aria-hidden="true">Click to enlarge</span><figcaption>${esc(sp)} (${trees.length})</figcaption><svg viewBox="0 0 ${W} ${Hh}" role="img" aria-label="${esc(sp)}: diameter of ${trees.length} trees over time">${g}</svg></figure>`;
}
// per-tree DBH history: first/latest live DBH, total and average increase (actual measurement dates), and the increase in
// each survey interval where the tree was live at both ends; negative changes are kept as recorded
function treeRows() {
  const P = PL.P, H = PL.hist, V = P.v, ivs = V.slice(1).map((v, i) => ({ i0: i, i1: i + 1, y0: V[i].y, y1: v.y, yrs: v.dy - V[i].dy, d0: V[i].d, d1: v.d }));
  const moved = new Set(H.microplot_moved);
  const short = (key, v) => { const d = decode(key, v); return d.status === 'decoded' ? d.text.replace(/^[^=]*=\s*/, '').split(' - ')[0].split('. ')[0].split(' (')[0].replace(/\.$/, '').toLowerCase() : `code ${v}`; };
  return H.trees.map(t => {
    const live = t.pts.filter(p => p.st === 1 && p.dia != null);
    const first = live[0] || t.pts.find(p => p.dia != null) || null, last = live[live.length - 1] || null;
    const total = live.length >= 2 ? last.dia - first.dia : null, yrs = live.length >= 2 ? V[last.vi].dy - V[first.vi].dy : null;
    const byVi = Object.fromEntries(t.pts.map(p => [p.vi, p]));
    const inc = ivs.map(iv => { const a = byVi[iv.i0], b = byVi[iv.i1]; return a && b && a.st === 1 && b.st === 1 && a.dia != null && b.dia != null ? b.dia - a.dia : null; });
    // status / fate in plain words (full text in the tooltip and in Expert view)
    const lp = t.pts[t.pts.length - 1], prevLive = p => { const k = t.pts.indexOf(p); for (let j = k - 1; j >= 0; j--) if (t.pts[j].st === 1) return t.pts[j]; return null; };
    let fate;
    if (lp.st === 1) fate = `Live ${lp.y}`;
    else if (lp.st === 3) { const pl = prevLive(lp); fate = `Cut ${pl ? pl.y + '–' : ''}${lp.y}`; }
    else if (lp.st === 0) fate = `Dropped ${lp.y} (${moved.has(lp.y) && (lp.dia ?? (last && last.dia) ?? 0) < 5 ? 'microplot moved' : short('TREE.RECONCILECD', lp.rc)})`;
    else { const d = t.pts.find(p => p.st === 2), pl = prevLive(d);
      fate = pl ? `Died ${pl.y}–${d.y}` + (d.agent != null ? ` (${short('TREE.AGENTCD', d.agent)})` : '') : `Dead when first tallied ${d.y}`; }
    // species recorded at the end of each interval (records can name different species at different visits)
    const ivsp = ivs.map(iv => byVi[iv.i1] ? spName(byVi[iv.i1].spcd) : null);
    return { t, ti: t.ti, id: t.id, sp: t.sp, ivsp, first, last, total, yrs, rate: total != null && yrs > 0 ? total / yrs : null, inc, ivs, fate, full: `${t.entry}; ${t.fate}` };
  });
}
function renderIndiv(P) {
  const H = PL.hist;
  if (H.empty) { $('#indiv').innerHTML = intro('indiv') + '<p class="muted">No TREE records at this location key.</p>'; return; }
  const T = treeData(), Y = P.v.map(v => v.y), xr = [Y[0], Y[Y.length - 1]];
  const ymax = Math.max(5, Math.ceil(Math.max(...T.flatMap(t => t.pts.map(p => p.dia || 0))) / 5) * 5);
  const order = (S_().sp ? S_().sp.codes.map(spName) : []).concat([...new Set(T.map(t => t.sp))]).filter((s, i, a) => a.indexOf(s) === i && T.some(t => t.sp === s));
  const legend = `<div class="smleg"><span><svg width="26" height="10"><line x1="1" y1="5" x2="25" y2="5" stroke="#2a78d6" stroke-width="1.6"/></svg> live, ≥5.0 in</span>`
    + `<span><svg width="26" height="10"><line x1="1" y1="5" x2="25" y2="5" stroke="#2a78d6" stroke-width="1.6" stroke-dasharray="3 2"/></svg> sapling (segment starting below 5.0 in)</span>`
    + `<span><svg width="26" height="10"><line x1="1" y1="5" x2="25" y2="5" stroke="#8a8984" stroke-width="1.6"/></svg> segment ending in a dead or cut record</span>`
    + `<span><svg width="10" height="10"><circle cx="5" cy="5" r="3" fill="#2a78d6"/></svg> live at last survey</span><span><svg width="10" height="10"><path d="M2 2L8 8M2 8L8 2" stroke="#b3261e" stroke-width="1.8"/></svg> died</span>`
    + `<span><svg width="10" height="10"><rect x="2" y="2" width="6" height="6" fill="#52514e"/></svg> cut</span><span><svg width="10" height="10"><circle cx="5" cy="5" r="3" fill="none" stroke="#52514e" stroke-width="1.4"/></svg> left the sample</span>`
    + `<span>dotted line = 5.0 in</span></div>`;
  const R = PL.treeRows = treeRows();
  PL.sm = { T, order, xr, ymax, legend };
  $('#indiv').innerHTML = intro('indiv') + `<h3>Diameter by species (same axes in every panel: ${xr[0]}–${xr[1]}, 0–${ymax} in)</h3>` + legend
    + `<div class="sm" id="smult">${order.map(s => smPanel(s, T.filter(t => t.sp === s), xr, ymax)).join('')}</div>`
    + `<h3 class="treetable">Trees (${R.length})</h3><p class="muted treetable">One row per tree. Click or tap a row for its full history. Increases use the actual measurement dates; `
    + `negative changes are kept as recorded (grey).</p><div class="treetable" id="treetab"></div>`;
  drawTreeTable(R);
  if (window.SPV) SPV.sync();                     // a shared link with #species=<SPCD> opens the full-size view
}
function drawTreeTable(R) {
  const ivs = R.length ? R[0].ivs : [];
  const yy = y => String(y).slice(2);
  const cols = [{ k: 'd:tree_id' }, { k: 'd:species' }, { k: 'd:first_y', n: 1 }, { k: 'd:first_dbh', n: 1 }, { k: 'd:last_y', n: 1 }, { k: 'd:last_dbh', n: 1 },
    { k: 'd:dbh_total', n: 1 }, { k: 'd:dbh_rate', n: 1 }, { k: 'd:dbh_rate5', n: 1 }]
    .concat(ivs.map(iv => ({ k: 'd:ivl', l: `${iv.y0}→${yy(iv.y1)}`, n: 1, title: `${iv.d0} → ${iv.d1}: ${iv.yrs.toFixed(2)} years` }))).concat([{ k: 'd:fate' }]);
  const neg = (v, d) => v == null ? { h: '', v: null } : { h: v < 0 ? `<span class="negchg" title="Negative change = measurement variation">${fmt(v, d)}</span>` : fmt(v, d), v };
  const rows = R.map(r => ({ attrs: ` class="trow" data-ti="${r.ti}" tabindex="0" aria-expanded="false"`,
    cells: [{ h: esc(r.id), v: r.id }, { h: esc(r.sp), v: r.sp }, { h: r.first ? r.first.y : '', v: r.first ? r.first.y : null }, { h: r.first ? fmt(r.first.dia, 1) : '', v: r.first ? r.first.dia : null },
      { h: r.last ? r.last.y : '', v: r.last ? r.last.y : null }, { h: r.last ? fmt(r.last.dia, 1) : '', v: r.last ? r.last.dia : null },
      neg(r.total, 1), neg(r.rate, 2), neg(r.rate != null ? r.rate * 5 : null, 2)].concat(r.inc.map(x => neg(x, 1)))
      .concat([{ h: isExpert() ? `<span class="wrapcell">${esc(r.full)}</span>` : `<span title="${esc(r.full)}">${esc(r.fate)}</span>`, v: r.fate }]) }));
  const html = tbl(cols, rows, { sort: true, sticky: true, id: 'trees_t', cls: 'sticky2' });
  // exact dates and years elapsed in the interval headers' tooltips
  $('#treetab').innerHTML = html;
  $('#treetab').querySelectorAll('thead th').forEach((h, i) => { if (cols[i] && cols[i].title) h.querySelector('.sortb').title = cols[i].title; });
  $('#treetab').querySelectorAll('tr.trow').forEach(tr => { const go = e => { if (e && e.target.closest('a, button')) return; toggleTree(tr); }; tr.onclick = go; tr.onkeydown = e => { if (e.key === 'Enter') go(); }; });
  updateFades($('#treetab'));
}
function toggleTree(tr) {
  const nx = tr.nextElementSibling;
  if (nx && nx.classList.contains('tdet')) { nx.remove(); tr.setAttribute('aria-expanded', 'false'); return; }
  const P = PL.P, ti = +tr.dataset.ti, recs = rowsOf(P.tr).filter(r => r.ti === ti).sort((a, b) => a.vi - b.vi);
  const cols = ['STATUSCD', 'SPCD', 'DIA', 'HT', 'CR', 'CCLCD', 'AGENTCD', 'RECONCILECD', 'MORTYR', 'TPA_UNADJ'];
  const t = PL.hist.trees.find(x => x.ti === ti), n = tr.cells.length;
  const html = `<tr class="tdet"><td colspan="${n}"><div class="tdetin"><p class="muted">${esc(t ? t.entry + '; ' + t.fate : '')}</p>`
    + `<div class="grid2"><div id="td_dbh_${ti}" class="chart tchart"></div><div id="td_ht_${ti}" class="chart tchart"></div></div>`
    + tbl([{ k: 'd:survey' }, { k: 'TREE.SUBP' }].concat(cols.map(c => ({ k: 'TREE.' + c }))),
      recs.map(r => [esc(P.v[r.vi].d), r.SUBP].concat(cols.map(c => cell('TREE', c, r[c]).h))), { noMax: true }) + '</div></td></tr>';
  tr.insertAdjacentHTML('afterend', html); tr.setAttribute('aria-expanded', 'true');
  const X = recs.map(r => P.v[r.vi].d), mk = recs.map(r => r.STATUSCD === 1 ? 'circle' : r.STATUSCD === 2 ? 'x' : 'square-open');
  const one = (id, key, title, unit) => Plotly.react(id, [{ x: X, y: recs.map(r => r[key]), mode: 'lines+markers', type: 'scatter', line: { color: '#2a78d6', width: 2 },
    marker: { size: 9, symbol: mk, color: '#2a78d6' }, hovertemplate: `%{x}: %{y} ${unit}<extra></extra>` }],
    lay({ title: { text: `${t ? t.id + ' ' + t.sp : ''}: ${title}`, x: 0 }, xaxis: { title: 'Survey date' }, yaxis: { title: unit, rangemode: 'tozero' }, showlegend: false, margin: { l: 50, r: 10, t: 36, b: 44 } }), plotCfg);
  one(`td_dbh_${ti}`, 'DIA', 'DBH at each survey (× = dead, □ = cut)', 'in');
  one(`td_ht_${ti}`, 'HT', 'total height at each survey', 'ft');
}
// ---------------------------------------------------------------- 9-11. growth, mortality, invasives (unchanged content)
function renderGrowth(H) {
  if (H.empty) { $('#growth').innerHTML = intro('growth') + '<p class="muted">No TREE records at this location key.</p>'; return; }
  $('#growth').innerHTML = intro('growth') + `<div id="c_growth" class="chart"></div>`;
  const G = H.growth, col = Object.fromEntries((S_().top || []).map((c, i) => [spName(c), PAL[i]]));
  if (G.length) {
    Plotly.react('c_growth', [
      { x: G.map(g => g.hi - g.lo), base: G.map(g => g.lo), y: G.map(g => g.sp), type: 'bar', orientation: 'h', marker: { color: 'rgba(154,152,147,.45)' }, width: 0.18, name: 'range', hoverinfo: 'skip' },
      { x: G.map(g => g.mean), y: G.map(g => g.sp), mode: 'markers', type: 'scatter', name: 'mean', marker: { size: 11, color: G.map(g => col[g.sp] || OTHER), line: { width: 1, color: '#222' } },
        customdata: G.map(g => [g.n, g.median, g.lo, g.hi]), hovertemplate: '%{y}: mean %{x:.3f} in/yr<br>n=%{customdata[0]}, median %{customdata[1]:.3f}, range %{customdata[2]:.3f} to %{customdata[3]:.3f}<extra></extra>' }],
      lay({ title: { text: 'Annual DBH growth by species (mean, range)', x: 0 }, xaxis: { title: 'in/yr' }, yaxis: { autorange: 'reversed', automargin: true }, showlegend: false, margin: { l: 140, r: 20, t: 36, b: 50 } }), plotCfg);
  } else $('#c_growth').outerHTML = '<p class="muted">No tree was live at two consecutive visits.</p>';
}
function renderMort(H) {
  if (H.empty) { $('#mort').innerHTML = intro('mort') + '<p class="muted">No TREE records at this location key.</p>'; return; }
  $('#mort').innerHTML = intro('mort') + `<div class="actions noprint"><label>Mortality as <select id="h_mm"><option value="tpa">trees/ac</option><option value="ba_ac">BA ft²/ac</option><option value="n">trees tallied</option></select></label></div><div id="c_mort" class="chart"></div>`;
  const ivls = H.years.slice(1).map((y, i) => `${H.years[i]}→${y}`);
  const drawMort = () => {
    const m = $('#h_mm').value, Mo = H.events.filter(e => e.type === 'mortality'), causes = [...new Set(Mo.map(e => e.cause))];
    const pal = ['#6250d6', '#008300', '#e87ba4', '#eda100', '#e34948', '#2a78d6', '#eb6834', '#1baf7a'];
    const tr = causes.map((c, i) => ({ x: ivls, y: ivls.map(iv => Mo.filter(e => e.cause === c && e.ivl === iv).reduce((a, e) => a + (m === 'n' ? 1 : (e[m] || 0)), 0)),
      name: c.length > 60 ? c.slice(0, 57) + '…' : c, type: 'bar', marker: { color: pal[i % pal.length] }, hovertemplate: `${esc(c)}<br>%{x}: %{y:.2f}<extra></extra>` }));
    Plotly.react('c_mort', tr.length ? tr : [{ x: ivls, y: ivls.map(() => 0), type: 'bar', name: 'no mortality' }],
      lay({ title: { text: 'Mortality by interval and cause (AGENTCD, decoded)', x: 0 }, barmode: 'stack', xaxis: { type: 'category' }, legend: { orientation: 'h', y: -0.3, font: { size: 10.5 } } }), plotCfg);
  };
  $('#h_mm').onchange = drawMort; drawMort();
}
function renderInvh(P) {
  const parts = P.v.map((v, i) => { const h = invVisit(P, i); return h ? `<div class="vsect"><h3>${esc(v.d)} (INVYR ${v.y})</h3>${h}</div>` : ''; }).filter(Boolean);
  $('#invh').innerHTML = intro('invh') + (parts.length ? parts.join('') : '<p class="muted">No invasive plant survey at this location key.</p>');
}

// ---------------------------------------------------------------- 13. plot-specific caveats
function renderCaveats(P) {
  const S = S_(), items = S.cav.map(([b, t]) => `<li><b>${esc(b)}.</b> ${esc(t)}</li>`);
  if (S.undc && S.undc.length) items.push(`<li><b>Undecoded codes</b> (shown flagged, not guessed):<ul>${S.undc.map(t => `<li>${esc(t)}</li>`).join('')}</ul></li>`);
  if (P.cd) items.push('<li><b>Coordinates differ between visits.</b> The public coordinates changed between visits; the map uses the latest visit\'s.</li>');
  if (P.nc > 1) items.push(`<li><b>${P.nc} separate PREV_PLT_CN chains</b> share this location key: some visits are not database-linked to each other.</li>`);
  $('#caveats').innerHTML = intro('caveats') + `<ul class="hl">${items.join('')}</ul><p class="muted">General caveats: <a href="about.html" data-keepview>About &amp; caveats</a>.</p>`;
}

// ---------------------------------------------------------------- history data (port of fiasc.plotdata.history; used by growth, mortality, trees)
function entryFate(recs, P) {
  const g0 = recs[0], last = recs[recs.length - 1], Y = r => P.v[r.vi].y;
  const entry = g0.SUBP > 4 && P.v[g0.vi].ds === 'annual' ? 'periodic-to-annual GRM record only (P2A_GRM_FLG); not a tallied tree'
    : g0.vi === 0 ? `tallied at first visit (${Y(g0)})` : `new in ${Y(g0)}: ${decode('TREE.RECONCILECD', g0.RECONCILECD).text}`;
  let fate;
  if (last.STATUSCD === 1) fate = `live at ${Y(last)}`;
  else if (last.STATUSCD === 0) fate = `left sample ${Y(last)}: ${decode('TREE.RECONCILECD', last.RECONCILECD).text}`;
  else if (last.STATUSCD === 3) fate = `cut by ${Y(last)}`;
  else { const d = recs.find(r => r.STATUSCD === 2), ex = [d.MORTYR != null ? `MORTYR ${d.MORTYR}` : '', d.AGENTCD != null ? `AGENTCD ${decode('TREE.AGENTCD', d.AGENTCD).text}` : ''].filter(Boolean);
    fate = (d === recs[0] ? `dead when first tallied (${Y(d)})` : `dead by ${Y(d)}`) + (ex.length ? ` (${ex.join('; ')})` : ''); }
  return [entry, fate];
}
function buildHistory(P) {
  const YRS = P.v.map(v => v.y), H = { years: YRS };
  if (!P.tr) return Object.assign(H, { empty: true });
  const sp = rowsOf(P.sp), tot = {}; sp.forEach(s => tot[s.SPCD] = (tot[s.SPCD] || 0) + (s.ba || 0));
  const rank = Object.keys(tot).map(Number).filter(s => tot[s] > 0).sort((a, b) => tot[b] - tot[a] || spName(a).localeCompare(spName(b)));
  // trees: national-design bridge records excluded; periodic visits keep their tallied points
  const tr = rowsOf(P.tr).filter(r => r.SUBP <= 4 || (P.v[r.vi].ds !== 'annual' && r.TPA_UNADJ != null)), byT = new Map();
  tr.forEach(r => { if (!byT.has(r.ti)) byT.set(r.ti, []); byT.get(r.ti).push(r); });
  H.trees = [...byT.entries()].map(([ti, recs]) => { recs.sort((a, b) => a.vi - b.vi); const [entry, fate] = entryFate(recs, P);
    return { ti, id: P.tl[ti], sp: spName(recs[recs.length - 1].SPCD), entry, fate, pts: recs.map(r => ({ vi: r.vi, spcd: r.SPCD, y: P.v[r.vi].y, dia: r.DIA, ht: r.HT, st: r.STATUSCD, agent: r.AGENTCD, rc: r.RECONCILECD, mortyr: r.MORTYR })) }; })
    .sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true }));
  const gr = rowsOf(P.gr), gs = {};
  gr.forEach(g => (gs[g.SPCD] = gs[g.SPCD] || []).push(g));
  const med = a => { const s = [...a].sort((x, y) => x - y), n = s.length; return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2; };
  H.growth = rank.concat(Object.keys(gs).map(Number).filter(s => !rank.includes(s))).filter(s => gs[s]).map(s => { const g = gs[s], d = g.map(x => x.gd), h = g.map(x => x.gh).filter(x => x != null);
    return { sp: spName(s), spcd: s, n: g.length, trees: new Set(g.map(x => x.ti)).size, mean: d.reduce((a, x) => a + x, 0) / d.length, median: med(d),
      lo: Math.min(...d), hi: Math.max(...d), ht: h.length ? h.reduce((a, x) => a + x, 0) / h.length : null }; });
  const moved = new Set(); P.v.forEach((v, i) => { if (i && v.mp != null && P.v[i - 1].mp != null && v.mp !== P.v[i - 1].mp) moved.add(v.y); });
  H.microplot_moved = [...moved];
  const T = FIA.meta.evtypes;
  H.events = rowsOf(P.ev).map(e => { const type = T[e.t];
    const cls = type === 'ingrowth' ? 'ingrowth (RECONCILECD 1)'
      : type === 'added (not ingrowth)' ? (moved.has(e.Y1) && (e.DIA || 0) < 5 ? 'microplot relocation addition' : 'other addition')
      : type === 'removed from sample' && moved.has(e.Y1) && (e.DIA || 0) < 5 ? 'microplot relocation drop' : type;
    return { type, cls, y0: e.Y0, y1: e.Y1, ivl: `${e.Y0 ?? ''}→${e.Y1}`, sp: spName(e.SPCD), cause: decode('TREE.AGENTCD', e.AGENTCD).text || 'no AGENTCD recorded',
      tpa: e.TPA, ba_ac: e.BA_AC, dia: e.DIA }; });
  return H;
}

// ---------------------------------------------------------------- print / save as PDF
const PSECS = [['highlights', 'Header and highlights'], ['timeline', 'Visit timeline'], ['survey', 'Survey summary and tree totals'], ['details', 'Visit details (selected visit)'],
  ['expert', 'Expert panels'], ['vc', 'Volume and carbon'], ['species', 'Species'], ['comp', 'Species composition'], ['indiv', 'Individual trees'], ['growth', 'Growth'],
  ['mort', 'Mortality'], ['invh', 'Invasives'], ['caveats', 'Caveats']];
function openPrintDialog() {
  const d = $('#printdlg');
  $('#pd_secs').innerHTML = PSECS.filter(([k]) => k !== 'expert' || isExpert()).map(([k, l]) => `<label><input type="checkbox" data-ps="${k}" checked> ${esc(l)}</label>`).join('');
  if (typeof d.showModal !== 'function') { doPrint({ secs: null, trees: true, raw: false }); return; }
  d.onclose = () => { if (d.returnValue === 'print') doPrint({ secs: [...d.querySelectorAll('[data-ps]')].filter(x => x.checked).map(x => x.dataset.ps), trees: $('#pd_trees').checked, raw: isExpert() && $('#pd_raw').checked }); };
  d.showModal();
}
async function doPrint(opt) { const done = await preparePrint(opt); window.addEventListener('afterprint', done, { once: true }); window.print(); }
// everything except window.print(): used by the button and by the headless print test (CDP Page.printToPDF)
async function preparePrint(opt) {
  document.body.classList.add('printing');
  const restore = [];
  document.querySelectorAll('section.psec').forEach(s => { const on = !opt.secs || opt.secs.includes(s.dataset.sec); s.dataset.print = on ? 'on' : 'off'; });
  const was = { ...PL.open };                                         // print expands every collapsed section
  if (Object.values(was).some(x => !x)) { Object.keys(PL.open).forEach(k => PL.open[k] = true); renderDetails(); restore.push(() => { PL.open = was; renderDetails(); }); }
  document.querySelectorAll('.treetable').forEach(e => { if (!opt.trees) { e.dataset.prevDisplay = e.style.display; e.style.display = 'none'; restore.push(() => { e.style.display = e.dataset.prevDisplay || ''; }); } });
  if (opt.raw && window.expertRawAppendix) { const a = window.expertRawAppendix(); restore.push(() => a.remove()); }
  // very wide tables (more than 24 columns: the Expert tree table, raw records) print as continuation blocks of at most 15
  // columns, each repeating the first (identifier) column, instead of being clipped at the page edge
  document.querySelectorAll('section.psec[data-print="on"] table').forEach(t => {
    const n = t.tHead ? t.tHead.rows[0].cells.length : 0;
    if (n <= 24 || t.closest('.printsplit')) return;
    const nb = Math.ceil((n - 1) / 15), per = Math.ceil((n - 1) / nb);
    const box = document.createElement('div'); box.className = 'printsplit printonly';
    for (let start = 1, part = 1; start < n; start += per, part++) {
      const keep = new Set([0].concat(Array.from({ length: Math.min(per, n - start) }, (_, j) => start + j)));
      const c = t.cloneNode(true); c.removeAttribute('id');
      c.querySelectorAll('tr').forEach(tr => { const cells = [...tr.cells]; if (cells.length === n) cells.forEach((td, j) => { if (!keep.has(j)) td.remove(); }); });
      const h = document.createElement('p'); h.className = 'muted'; h.textContent = `Columns ${start + 1}–${Math.min(n, start + per)} of ${n}` + (part > 1 ? ' (continued)' : '');
      box.append(h, c);
    }
    const wrap = t.closest('.hscroll') || t.closest('.scroll') || t;
    wrap.classList.add('noprint'); wrap.after(box);
    restore.push(() => { box.remove(); wrap.classList.remove('noprint'); });
  });
  // charts as static images (sharp in print, no interactivity needed)
  const charts = [...document.querySelectorAll('.js-plotly-plot')].filter(c => c.closest('section.psec[data-print="on"]') || c.closest('#s-expert'));
  for (const c of charts) {
    try {
      const w = 900, h = Math.max(320, Math.min(520, c.clientHeight || 360));       // fixed print width: readable text at page width
      // print colours (dark text on white) regardless of the screen theme, then back
      const old = { 'font.color': c.layout.font && c.layout.font.color, 'xaxis.gridcolor': c.layout.xaxis && c.layout.xaxis.gridcolor, 'yaxis.gridcolor': c.layout.yaxis && c.layout.yaxis.gridcolor };
      await Plotly.relayout(c, { 'font.color': '#111', 'xaxis.gridcolor': '#d0d0d0', 'yaxis.gridcolor': '#d0d0d0' });
      const url = await Plotly.toImage(c, { format: 'png', width: w, height: h, scale: 2 });
      await Plotly.relayout(c, old);
      const img = document.createElement('img'); img.src = url; img.className = 'chartimg'; img.alt = (c.layout && c.layout.title && c.layout.title.text) || 'chart';
      img.style.width = '100%'; img.style.maxWidth = '7.3in';
      const host = c.closest('.chart') || c; host.classList.add('has-img'); host.append(img);
      restore.push(() => { img.remove(); host.classList.remove('has-img'); });
    } catch (e) { console.error('chart image', e); }
  }
  // running header/footer (paged media margin boxes where supported) + closing terms list
  const ver = (FIA.meta.build.fiadb_version || {}).version || '';
  const st = document.createElement('style');
  const q = s => '"' + String(s).replace(/["\\]/g, '') + '"';
  st.textContent = `@page { @top-left { content: ${q(`FIA Plot ${PL.P.k} · ${PL.county} Co., SC`)}; font: 7.5pt 'Segoe UI', Arial, sans-serif; color: #444; }
    @top-right { content: ${q(isExpert() ? 'Expert view' : '')}; font: 7.5pt 'Segoe UI', Arial, sans-serif; color: #444; }
    @bottom-left { content: ${q(`Generated ${new Date().toISOString().slice(0, 10)} from FIADB ${ver}; public data; coordinates fuzzed`)}; font: 7pt 'Segoe UI', Arial, sans-serif; color: #444; }
    @bottom-right { content: "Page " counter(page) " of " counter(pages); font: 7.5pt 'Segoe UI', Arial, sans-serif; color: #444; } }`;
  document.head.append(st); restore.push(() => st.remove());
  $('#printfoot').textContent = `Generated ${new Date().toISOString().slice(0, 10)} from FIADB ${ver}; public data; coordinates fuzzed. ${location.href.split('#')[0]}`;
  $('#s-terms').innerHTML = termsUsed(); restore.push(() => { $('#s-terms').innerHTML = ''; });
  const done = () => { restore.reverse().forEach(f => { try { f(); } catch (e) { /* ignore */ } }); document.querySelectorAll('section.psec').forEach(s => delete s.dataset.print); document.body.classList.remove('printing'); };
  PL.printRestore = done;
  return done;
}
PL.preparePrint = o => preparePrint(o);
// "Terms used": help text of the headers shown in the printed sections (instead of tooltips)
function termsUsed() {
  const keys = new Set();
  // column headers and computed values (field lists already show their labels next to each value)
  document.querySelectorAll('section.psec[data-print="on"] th[data-hk], section.psec[data-print="on"] .kpi [data-h]').forEach(e => { const k = e.dataset.hk || e.dataset.h; if (k && !k.startsWith('s:')) keys.add(k); });
  const items = [...keys].map(k => ({ k, h: helpFor(k) })).filter(x => x.h).sort((a, b) => a.h.label.localeCompare(b.h.label));
  const seen = new Set();
  return `<h2>Terms used</h2><dl class="terms">` + items.filter(x => { const id = x.h.label + x.h.code; if (seen.has(id)) return false; seen.add(id); return true; })
    .map(x => `<dt><b>${esc(x.h.label)}</b>${x.h.code ? ` (${esc(x.h.code)})` : ''}${x.h.unit ? `, ${esc(x.h.unit)}` : ''}</dt><dd>${esc(x.h.text)}${x.h.src ? ` <i>${esc(x.h.src)}</i>` : ''}</dd>`).join('') + '</dl>';
}

// ---------------------------------------------------------------- CSV export (in the browser)
const csvCell = v => v == null ? '' : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v);
const toCsv = (cols, rows) => '﻿' + [cols.join(',')].concat(rows.map(r => r.map(csvCell).join(','))).join('\r\n');
function treeCsv() {
  const P = PL.P, byT = new Map();
  rowsOf(P.tr).forEach(r => { if (!byT.has(r.ti)) byT.set(r.ti, []); byT.get(r.ti).push(r); });
  const rows = [];
  for (const [ti, recs] of byT) {
    recs.sort((a, b) => a.vi - b.vi);
    const [entry, fate] = entryFate(recs, P);
    for (const r of recs) {
      const v = P.v[r.vi], ok = r.TPA_UNADJ != null;
      rows.push([P.k, P.tl[ti], entry, fate, v.y, v.d, r.SUBP, r.TREE, r.SPCD, spName(r.SPCD), decode('TREE.STATUSCD', r.STATUSCD).text, r.DIA, r.HT, r.TPA_UNADJ,
        ok && r.DIA != null ? +(BA_K * r.DIA ** 2 * r.TPA_UNADJ).toFixed(4) : '', ok && r.VOLCFNET != null ? +(r.VOLCFNET * r.TPA_UNADJ).toFixed(3) : '',
        ok && r.CARBON_AG != null ? +(r.CARBON_AG * r.TPA_UNADJ / 2000).toFixed(5) : '', decode('TREE.AGENTCD', r.AGENTCD).text,
        decode('TREE.RECONCILECD', r.RECONCILECD).text, r.MORTYR, r.SUBP > 4]);
    }
  }
  return toCsv(['plot_key', 'tree_id', 'entry', 'fate', 'INVYR', 'survey_date', 'SUBP', 'TREE', 'SPCD', 'species', 'STATUSCD', 'DIA_in', 'HT_ft', 'TPA_UNADJ',
    'BA_ft2_per_ac', 'VOLCFNET_ft3_per_ac', 'carbon_tons_per_ac', 'AGENTCD', 'RECONCILECD', 'MORTYR', 'bridge_record'], rows);
}
function visitCsv() {
  const P = PL.P, m = FIA.meta.metrics;
  return toCsv(['plot_key', 'PLT_CN', 'INVYR', 'DATE', 'DATE_APPROX', 'DESIGN', 'KINDCD', 'DESIGNCD', 'PLOT_STATUS_CD', 'REMPER', 'FORTYPCD', 'STDAGE', 'N_INVASIVE_SPP'].concat(m),
    P.v.map(v => [P.k, v.cn, v.y, v.d, v.da, v.ds, decode('PLOT.KINDCD', v.kc).text, decode('PLOT.DESIGNCD', v.dc).text, decode('PLOT.PLOT_STATUS_CD', v.st).text,
      v.rp, ftName(v.ft), v.ag, v.ni].concat(v.m)));
}
function download(name, text, type = 'text/csv;charset=utf-8') {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name; document.body.append(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

init().catch(e => { $('#title').textContent = 'Could not load plot ' + KEY + ': ' + e.message; document.body.dataset.ready = 'error'; console.error(e); });

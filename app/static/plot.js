// SC FIA plot explorer: plot page.
'use strict';
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (v, d = 1) => v == null || v === '' || isNaN(v) ? '—' : Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const KEY = decodeURIComponent(location.pathname.split('/').pop());
const api = p => fetch(p).then(r => r.ok ? r.json() : r.json().then(j => Promise.reject(new Error(j.detail || r.statusText))));
const P = { header: null, visit: null, hist: null };
window.PLOT = P;

// decoded values: {code, text, status}; anything not decoded is flagged, never guessed
function dv(x) {
  if (x && typeof x === 'object' && 'status' in x) {
    if (x.status === 'blank') return '';
    if (x.status !== 'decoded') return `<span class="flag" title="${x.status === 'no_table' ? 'no code list in the FIADB User Guide v9.4' : 'value not in the FIADB User Guide v9.4 code list'}">⚠ ${esc(x.text)}</span>`;
    return esc(x.text);
  }
  if (typeof x === 'number') return Number.isInteger(x) ? String(x) : fmt(x, 3);
  return esc(x);
}
// compact form for cards: first clause of the guide text, full text on hover
function dvs(x, n = 48) {
  if (!x || typeof x !== 'object' || x.status !== 'decoded') return dv(x);
  let t = x.text.split(' - ')[0].split('. ')[0];
  if (t.length > n) t = t.slice(0, n - 1).replace(/\s+\S*$/, '') + '…';
  return `<span title="${esc(x.text)}">${esc(t)}</span>`;
}
const plotCfg = { displaylogo: false, responsive: true, modeBarButtonsToRemove: ['lasso2d', 'select2d'] };
function theme() {
  const cs = getComputedStyle(document.documentElement);
  const ink = cs.getPropertyValue('--ink').trim(), line = cs.getPropertyValue('--line').trim();
  return { paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { color: ink, family: 'Segoe UI, Arial, sans-serif', size: 12 },
    xaxis: { gridcolor: line, zeroline: false }, yaxis: { gridcolor: line, zeroline: false }, margin: { l: 60, r: 20, t: 36, b: 50 },
    legend: { orientation: 'h', y: -0.18 }, hoverlabel: { font: { size: 12 } } };
}
const lay = o => { const t = theme(); return Object.assign(t, o, { xaxis: Object.assign(t.xaxis, o.xaxis || {}), yaxis: Object.assign(t.yaxis, o.yaxis || {}) }); };

async function init() {
  const h = await api('/api/plot/' + encodeURIComponent(KEY));
  P.header = h;
  document.title = `FIA plot ${h.key}`;
  $('#title').textContent = `Plot ${h.key} · ${h.county} County, SC`;
  $('#subtitle').innerHTML = `STATECD ${h.statecd} · UNITCD ${h.unitcd} · COUNTYCD ${h.countycd} · PLOT ${h.plot} · public location ${fmt(h.lat, 5)}, ${fmt(h.lon, 5)} (fuzzed) ·
    ${h.n_visits} visit${h.n_visits > 1 ? 's' : ''} (${esc(h.designs)}) · owner group ${dvs(h.owngrp, 30)} · latest forest type ${esc(h.fortyp || 'none (no accessible forest)')}`;
  const notes = [esc(h.coord_note), esc(h.unadj_note)];
  if (h.coords_differ) notes.push('<b>The public coordinates differ between visits</b> (the latest visit\'s are shown on the map).');
  if (h.n_chains > 1) notes.push(`<b>${h.n_chains} separate PREV_PLT_CN chains share this location key</b>: some visits are not database-linked to each other.`);
  $('#notes').innerHTML = notes.join('<br>');
  $('#csv_trees').href = `/api/plot/${encodeURIComponent(KEY)}/export.csv?what=trees`;
  $('#csv_visits').href = `/api/plot/${encodeURIComponent(KEY)}/export.csv?what=visits`;
  $('#pdf').href = `/api/plot/${encodeURIComponent(KEY)}/summary.pdf`;
  renderTimeline(h);
  renderTotals(h);
  selectVisit(h.visits[h.visits.length - 1].plt_cn);
  P.hist = await api(`/api/plot/${encodeURIComponent(KEY)}/history`);
  renderHistory(P.hist);
  document.body.dataset.ready = '1';
}

function renderTimeline(h) {
  $('#tldesc').innerHTML = `Survey dates from PLOT MEASYEAR-MEASMON-MEASDAY (periodic plots often lack the day: shown to the month).` +
    (h.predecessors.length ? ` Dashed cards are periodic plots that are <b>inferred candidates, not database-linked</b> predecessors (ranked by score).` : '');
  const preds = h.predecessors.slice(0, 3).map(p => `<div class="tc pred"><div class="d">${esc(p.last_date)}</div>
      <div>Periodic plot ${esc(p.key)} · INVYR ${p.invyr}</div><span class="tag">${esc(p.label)}</span>
      <div class="muted">rank ${p.rank} · score ${fmt(p.score, 0)}/100 · ${fmt(p.dist_mi, 2)} mi</div></div>`);
  const vis = h.visits.map(v => `<div class="tc" data-cn="${esc(v.plt_cn)}" tabindex="0"><div class="d">${esc(v.date)}${v.date_approx ? '*' : ''}</div>
      <div>INVYR ${v.invyr} · ${esc(v.design)}</div><div class="muted">KINDCD ${dvs(v.kindcd)}</div><div class="muted">DESIGNCD ${dvs(v.designcd, 36)}</div>
      <div class="muted">${dvs(v.status, 36)}${v.remper != null ? ` · REMPER ${fmt(v.remper)} yr` : ''}</div></div>`);
  $('#timeline').innerHTML = preds.concat(vis).join('');
  document.querySelectorAll('.tc[data-cn]').forEach(el => { el.onclick = () => selectVisit(el.dataset.cn); el.onkeydown = e => { if (e.key === 'Enter') selectVisit(el.dataset.cn); }; });
  if (h.predecessors.length) {
    $('#predbox').innerHTML = `<h3>Inferred periodic predecessor candidates (not database-linked)</h3>
      <p class="muted">Periodic plots in the same county within 1.5 mi (public, fuzzed coordinates) whose last measurement date + this plot's first-visit REMPER
      falls within 0.5 yr of the first national-design visit; scored 0–100 from bridge-tree matches (60), date fit (25) and distance (15).</p>
      <div class="scroll"><table><thead><tr><th>Rank</th><th>Periodic plot</th><th>Last measured</th><th>Forest type, age</th><th class="n">Distance mi</th>
      <th class="n">Date fit yr</th><th>Bridge trees matched</th><th class="n">Score</th></tr></thead><tbody>` +
      h.predecessors.map(p => `<tr><td>${p.rank}</td><td><a href="/plot/${encodeURIComponent(p.key)}">${esc(p.key)}</a></td><td>${esc(p.last_date)} (INVYR ${p.invyr})</td>
        <td>${esc(p.fortyp)}${p.stdage != null ? `, ${p.stdage} yr` : ''}</td><td class="n">${fmt(p.dist_mi, 2)}</td><td class="n">${fmt(p.dt_yr, 2)}</td>
        <td>${p.n_bridge ? `${p.n_matched} of ${p.n_bridge}${p.pairs ? ': ' + esc(p.pairs) : ''}` : 'no bridge records'}</td><td class="n">${fmt(p.score, 0)}</td></tr>`).join('') +
      '</tbody></table></div>';
  } else if (h.candidate_for.length) {
    $('#predbox').innerHTML = `<p class="muted">This periodic plot is an inferred predecessor candidate (not database-linked) of: ` +
      h.candidate_for.map(c => `<a href="/plot/${encodeURIComponent(c.key)}">${esc(c.key)}</a> (rank ${c.rank}, score ${fmt(c.score, 0)})`).join(', ') + '.</p>';
  }
}

function renderTotals(h) {
  // per-visit totals from the database (same numbers the PDF is validated against)
  const rows = h.visits.map(v => `<tr data-invyr="${v.invyr}"><td>${esc(v.date)}</td><td>${v.invyr}</td><td>${esc(v.design)}${v.design === 'periodic' ? ' †' : ''}</td>
     <td class="n" data-ba="${v.ba ?? ''}">${fmt(v.ba, 1)}</td><td class="n">${fmt(v.live_tpa, 0)}</td><td>${esc(v.fortyp)}</td><td class="n">${fmt(v.stdage, 0)}</td>
     <td class="n">${v.n_invasive}</td></tr>`).join('');
  $('#totals').innerHTML = `<thead><tr><th>Survey date</th><th>INVYR</th><th>Design</th><th class="n">Live BA ft²/ac</th><th class="n">Live trees/ac</th>
     <th>Forest type (dominant forest condition)</th><th class="n">Stand age</th><th class="n">Invasive spp.</th></tr></thead><tbody>${rows}</tbody>
     <tfoot><tr><td colspan="8" class="muted">Live trees ≥1.0 in on subplots 1–4 (bridge records on SUBP &gt; 4 excluded); Σ(BA × TPA_UNADJ). † periodic design: not comparable with national-design visits.</td></tr></tfoot>`;
}

// ---------------------------------------------------------------- visit tabs
const TABS = [['cond', 'Conditions'], ['metrics', 'Stand metrics'], ['species', 'Species'], ['trees', 'Trees'], ['seed', 'Seedlings'],
  ['site', 'Site trees'], ['veg', 'P2 vegetation'], ['inv', 'Invasives'], ['dwm', 'Down woody material'], ['soils', 'Soils'], ['plot', 'PLOT record']];
let curTab = 'metrics';
async function selectVisit(cn) {
  document.querySelectorAll('.tc[data-cn]').forEach(el => el.classList.toggle('sel', el.dataset.cn === cn));
  $('#tab').innerHTML = 'Loading…';
  P.visit = await api(`/api/plot/${encodeURIComponent(KEY)}/visit/${encodeURIComponent(cn)}`);
  const v = P.visit;
  $('#vsel').textContent = `— ${v.visit.DATE} (INVYR ${v.visit.INVYR}, ${v.visit.DESIGN})`;
  const has = {
    cond: v.conditions.length, metrics: 1, species: v.species.length, trees: v.trees.length, seed: v.seedlings.rows.length, site: v.sitetrees.rows.length,
    veg: v.p2veg_structure.rows.length + v.p2veg_species.rows.length, inv: 1, dwm: Object.values(v.dwm).some(t => t.rows.length),
    soils: Object.values(v.soils).some(t => t.rows.length), plot: 1
  };
  $('#tabs').innerHTML = TABS.map(([k, l]) => `<button type="button" data-t="${k}" class="${k === curTab ? 'on' : ''}" ${has[k] ? '' : 'disabled title="no records for this visit"'}>${l}</button>`).join('');
  document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => { curTab = b.dataset.t; document.querySelectorAll('#tabs button').forEach(x => x.classList.toggle('on', x === b)); renderTab(); });
  if (!has[curTab]) curTab = 'metrics';
  renderTab();
}
function fieldsHtml(list) { return `<div class="fields">${list.map(f => `<div><b>${esc(f.col)}</b>: ${dv(f.value)}</div>`).join('')}</div>`; }
function genericTable(t, title) {
  if (!t.available) return `<p class="muted">${esc(title)}: table not in this build.</p>`;
  if (!t.rows.length) return `<p class="muted">${esc(title)}: no records for this visit.</p>`;
  return `<h3>${esc(title)} (${t.rows.length})</h3><div class="scroll"><table><thead><tr>${t.columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>` +
    t.rows.map(r => '<tr>' + t.columns.map(c => `<td>${dv(r[c])}</td>`).join('') + '</tr>').join('') + '</tbody></table></div>';
}
function renderTab() {
  const v = P.visit, el = $('#tab');
  if (curTab === 'cond') el.innerHTML = v.conditions.map((c, i) => `<h3>Condition ${dv(c.find(f => f.col === 'CONDID')?.value)}</h3>${fieldsHtml(c)}`).join('');
  else if (curTab === 'plot') el.innerHTML = fieldsHtml(v.plot_fields);
  else if (curTab === 'metrics') {
    const m = v.metrics;
    const k = (l, val, u) => `<div class="kpi"><div class="l">${l}</div><div class="v">${val}</div><div class="u">${u}</div></div>`;
    el.innerHTML = `<div class="kpis">${k('Live basal area', fmt(m.ba), 'ft²/ac')}${k('Live trees', fmt(m.live_tpa, 0), `trees/ac (${m.live_n ?? 0} tallied)`)}
      ${k('Trees ≥5 in', fmt(m.tpa5, 0), 'trees/ac')}${k('Saplings 1–4.9 in', fmt(m.sap_tpa, 0), 'trees/ac')}${k('QMD', fmt(m.qmd), 'in')}
      ${k('Net cubic volume', fmt(m.vol, 0), 'ft³/ac')}${k('Aboveground carbon', fmt(m.carbon, 2), 'tons C/ac')}${k('Standing dead', fmt(m.dead_tpa, 0), `trees/ac (${m.dead_n ?? 0} tallied), ${fmt(m.dead_ba)} ft²/ac`)}</div>
      <h3>Trees per acre by size class</h3><table><thead><tr><th>Status</th><th class="n">1.0–4.9 in</th><th class="n">5.0–9.9 in</th><th class="n">10.0–19.9 in</th><th class="n">≥20 in</th></tr></thead>
      <tbody><tr><td>Live</td>${['c1', 'c2', 'c3', 'c4'].map(c => `<td class="n">${fmt(m['live_tpa_' + c], 1)}</td>`).join('')}</tr>
      <tr><td>Standing dead</td>${['c1', 'c2', 'c3', 'c4'].map(c => `<td class="n">${fmt(m['dead_tpa_' + c], 1)}</td>`).join('')}</tr></tbody></table>
      <p class="muted">${esc(v.unadj_note)}</p>`;
  } else if (curTab === 'species') {
    el.innerHTML = `<div class="scroll"><table><thead><tr><th>Species</th><th class="n">Live trees</th><th class="n">Live TPA</th><th class="n">TPA ≥5 in</th><th class="n">BA ft²/ac</th>
      <th class="n">% BA</th><th class="n">Vol ft³/ac</th><th class="n">Carbon t/ac</th><th class="n">Dead trees</th><th class="n">Dead TPA</th></tr></thead><tbody>` +
      v.species.map(s => `<tr><td>${esc(s.species)} <span class="muted">(${s.SPCD})</span></td><td class="n">${s.live_n ?? 0}</td><td class="n">${fmt(s.live_tpa, 1)}</td>
        <td class="n">${fmt(s.tpa5, 1)}</td><td class="n">${fmt(s.ba, 2)}</td><td class="n">${fmt(s.pct_ba, 1)}</td><td class="n">${fmt(s.vol, 0)}</td><td class="n">${fmt(s.carbon, 2)}</td>
        <td class="n">${s.dead_n ?? 0}</td><td class="n">${fmt(s.dead_tpa, 1)}</td></tr>`).join('') + '</tbody></table></div>';
  } else if (curTab === 'trees') {
    const cols = ['SUBP', 'TREE', 'STATUSCD', 'SPCD', 'DIA', 'HT', 'ACTUALHT', 'CR', 'CCLCD', 'TREECLCD', 'AGENTCD', 'DAMAGE_AGENT_CD1', 'DECAYCD', 'MORTYR', 'RECONCILECD', 'TPA_UNADJ', 'VOLCFNET', 'CARBON_AG'];
    el.innerHTML = `<p class="muted">${v.trees.length} TREE records. Rows on SUBP &gt; 4 are periodic-to-annual bridge records (excluded from totals). “linked” = has PREV_TRE_CN.</p>
      <div class="scroll"><table><thead><tr>${cols.map(c => `<th>${c}</th>`).join('')}<th class="n">BA ft²/ac</th><th>linked</th></tr></thead><tbody>` +
      v.trees.map(t => `<tr${t.bridge ? ' class="muted"' : ''}>${cols.map(c => `<td>${dv(t[c])}</td>`).join('')}<td class="n">${fmt(t.ba_ac, 3)}</td><td>${t.linked ? 'yes' : ''}</td></tr>`).join('') + '</tbody></table></div>';
  } else if (curTab === 'seed') el.innerHTML = genericTable(v.seedlings, 'SEEDLING');
  else if (curTab === 'site') el.innerHTML = genericTable(v.sitetrees, 'SITETREE');
  else if (curTab === 'veg') el.innerHTML = genericTable(v.p2veg_structure, 'P2VEG_SUBP_STRUCTURE') + genericTable(v.p2veg_species, 'P2VEG_SUBPLOT_SPP');
  else if (curTab === 'inv') el.innerHTML = `<p>Invasive sampling: ${dv(v.invasive_surveyed)}</p>` + (v.invasives.length ? `<table><thead><tr><th>Species</th><th>Symbol</th>
      <th>Subplots</th><th class="n">Mean cover %</th></tr></thead><tbody>` + v.invasives.map(i => `<tr><td>${esc(i.name)} <i class="muted">${esc(i.sci)}</i></td><td>${esc(i.symbol)}</td>
      <td>${i.subplots.join(', ')}</td><td class="n">${fmt(i.cover_mean)}</td></tr>`).join('') + '</tbody></table>' : '<p class="muted">No invasive plant records for this visit.</p>');
  else if (curTab === 'dwm') el.innerHTML = Object.entries(v.dwm).map(([t, d]) => genericTable(d, t)).join('');
  else if (curTab === 'soils') el.innerHTML = Object.entries(v.soils).map(([t, d]) => genericTable(d, t)).join('');
}

// ---------------------------------------------------------------- history
function renderHistory(H) {
  if (H.empty) { $('#hist').innerHTML = '<p class="muted">No TREE records at this location key.</p>'; return; }
  const X = H.years.map(String);
  $('#hist').innerHTML = `
    <div class="actions"><label>Stacked metric <select id="h_metric"><option value="ba">Basal area ft²/ac</option><option value="tpa">Trees/ac</option>
      <option value="carbon">Aboveground carbon tons C/ac</option><option value="vol">Net cubic volume ft³/ac</option></select></label></div>
    <div id="c_stack" class="chart"></div>
    <div class="grid2"><div><div class="actions"><label>Tree history <select id="h_tm"><option value="dia">DBH (in)</option><option value="ht">Height (ft)</option></select></label>
      <label>Species <select id="h_sp"><option value="">All</option></select></label></div><div id="c_trees" class="chart"></div></div>
      <div><div id="c_growth" class="chart"></div></div></div>
    <div class="grid2"><div><div class="actions"><label>Mortality as <select id="h_mm"><option value="tpa">trees/ac</option><option value="ba_ac">BA ft²/ac</option><option value="n">trees tallied</option></select></label></div>
      <div id="c_mort" class="chart"></div></div><div><div class="actions"><span class="muted">Additions by RECONCILECD; microplot-relocation additions are separated from ingrowth${H.microplot_moved.length ? ` (microplot moved at ${H.microplot_moved.join(', ')})` : ''}.</span></div>
      <div id="c_ing" class="chart"></div></div></div>
    <h3>Individual trees (${H.trees.length})</h3>
    <div class="scroll"><table><thead><tr><th>Tree</th><th>Species</th><th>Entry</th><th>Fate</th>${X.map(y => `<th class="n">${y}</th>`).join('')}</tr></thead><tbody>` +
    H.trees.map(t => { const by = Object.fromEntries(t.pts.map(p => [p.y, p]));
      return `<tr><td>${esc(t.id)}</td><td>${esc(t.sp)}</td><td>${esc(t.entry)}</td><td>${esc(t.fate)}</td>${H.years.map(y => { const p = by[y];
        return `<td class="n">${p ? (p.st === 1 ? fmt(p.dia, 1) : p.st === 2 ? `<span title="dead">✝ ${fmt(p.dia, 1)}</span>` : p.st === 3 ? 'cut' : '–') : ''}</td>`; }).join('')}</tr>`; }).join('') +
    '</tbody></table></div><p class="muted">' + esc(H.unadj_note) + '</p>';
  const order = H.species.order, col = H.species.colors;
  const lab = g => g === 'Other species' ? `Other species (${H.species.other_n})` : g;
  const drawStack = () => {
    const m = $('#h_metric').value;
    const tr = order.map(g => ({ x: X, y: H.stack[m][g], name: lab(g), type: 'scatter', mode: 'lines', stackgroup: 'one', line: { width: 0.5, color: col[g] },
      fillcolor: col[g], hovertemplate: `${esc(lab(g))}: %{y:.2f}<extra></extra>` }));
    tr.push({ x: X, y: H.totals[m], name: 'Total', mode: 'markers+text', text: H.totals[m].map(v => v.toFixed(m === 'carbon' ? 1 : 0)), textposition: 'top center',
      marker: { size: 1, color: 'rgba(0,0,0,0)' }, showlegend: false, hovertemplate: 'Total %{y:.2f}<extra></extra>', type: 'scatter' });
    Plotly.react('c_stack', tr, lay({ title: { text: $('#h_metric').selectedOptions[0].text + ' by species (live)', x: 0 }, xaxis: { type: 'category', title: 'INVYR' },
      hovermode: 'x unified' }), plotCfg);
  };
  $('#h_metric').onchange = drawStack; drawStack();
  const sps = [...new Set(H.trees.map(t => t.sp))].sort();
  sps.forEach(s => $('#h_sp').append(new Option(s, s)));
  const drawTrees = () => {
    const m = $('#h_tm').value, sp = $('#h_sp').value;
    const tr = H.trees.filter(t => !sp || t.sp === sp).map(t => ({ x: t.pts.map(p => String(p.y)), y: t.pts.map(p => p[m]), name: t.id, type: 'scatter', mode: 'lines+markers',
      line: { width: 1.2, color: col[t.spg] }, marker: { size: 6, symbol: t.pts.map(p => p.st === 1 ? 'circle' : p.st === 2 ? 'x' : 'square-open'), color: col[t.spg] },
      showlegend: false, hovertemplate: `${esc(t.id)} ${esc(t.sp)}<br>%{x}: %{y}<extra></extra>` }));
    Plotly.react('c_trees', tr, lay({ title: { text: `Individual tree ${m === 'dia' ? 'DBH (in)' : 'height (ft)'} (× = dead)`, x: 0 }, xaxis: { type: 'category', categoryarray: X } }), plotCfg);
  };
  $('#h_tm').onchange = drawTrees; $('#h_sp').onchange = drawTrees; drawTrees();
  const G = H.growth;
  if (G.length) {
    Plotly.react('c_growth', [
      { x: G.map(g => g.hi - g.lo), base: G.map(g => g.lo), y: G.map(g => g.sp), type: 'bar', orientation: 'h', marker: { color: 'rgba(154,152,147,.45)' }, width: 0.18, name: 'range',
        hoverinfo: 'skip' },
      { x: G.map(g => g.mean), y: G.map(g => g.sp), mode: 'markers', type: 'scatter', name: 'mean', marker: { size: 11, color: G.map(g => col[order.includes(g.sp) ? g.sp : 'Other species']), line: { width: 1, color: '#222' } },
        customdata: G.map(g => [g.n, g.median, g.lo, g.hi]), hovertemplate: '%{y}: mean %{x:.3f} in/yr<br>n=%{customdata[0]}, median %{customdata[1]:.3f}, range %{customdata[2]:.3f} to %{customdata[3]:.3f}<extra></extra>' }],
      lay({ title: { text: 'Annual DBH growth by species (mean, range)', x: 0 }, xaxis: { title: 'in/yr' }, yaxis: { autorange: 'reversed', automargin: true }, showlegend: false, margin: { l: 140, r: 20, t: 36, b: 50 } }), plotCfg);
  } else $('#c_growth').innerHTML = '<p class="muted">No tree was live at two consecutive visits.</p>';
  const ivls = H.years.slice(1).map((y, i) => `${H.years[i]}→${y}`);
  const drawMort = () => {
    const m = $('#h_mm').value;
    const M = H.events.filter(e => e.type === 'mortality');
    const causes = [...new Set(M.map(e => e.cause))];
    const pal = ['#6250d6', '#008300', '#e87ba4', '#eda100', '#e34948', '#2a78d6', '#eb6834', '#1baf7a'];
    const tr = causes.map((c, i) => ({ x: ivls, y: ivls.map(iv => M.filter(e => e.cause === c && e.ivl === iv).reduce((a, e) => a + (m === 'n' ? 1 : (e[m] || 0)), 0)),
      name: c.length > 60 ? c.slice(0, 57) + '…' : c, type: 'bar', marker: { color: pal[i % pal.length] }, hovertemplate: `${esc(c)}<br>%{x}: %{y:.2f}<extra></extra>` }));
    Plotly.react('c_mort', tr.length ? tr : [{ x: ivls, y: ivls.map(() => 0), type: 'bar', name: 'no mortality' }],
      lay({ title: { text: 'Mortality by interval and cause (AGENTCD, decoded)', x: 0 }, barmode: 'stack', xaxis: { type: 'category' }, legend: { orientation: 'h', y: -0.3, font: { size: 10.5 } } }), plotCfg);
  };
  $('#h_mm').onchange = drawMort; drawMort();
  const cls = ['ingrowth (RECONCILECD 1)', 'other addition', 'microplot relocation addition', 'microplot relocation drop', 'removed from sample', 'cut', 'dead at first tally'];
  const ccol = { 'ingrowth (RECONCILECD 1)': '#1baf7a', 'other addition': '#eda100', 'microplot relocation addition': '#2a78d6', 'microplot relocation drop': '#9a9893',
    'removed from sample': '#52514e', 'cut': '#e34948', 'dead at first tally': '#6250d6' };
  const tr = cls.map(c => ({ x: ivls, y: ivls.map(iv => H.events.filter(e => e.cls === c && e.ivl === iv).length), name: c, type: 'bar', marker: { color: ccol[c] },
    hovertemplate: `${c}<br>%{x}: %{y} trees<extra></extra>` })).filter(t => t.y.some(v => v));
  Plotly.react('c_ing', tr.length ? tr : [{ x: ivls, y: ivls.map(() => 0), type: 'bar', name: 'no additions' }],
    lay({ title: { text: 'Additions and other sample changes (trees tallied)', x: 0 }, barmode: 'group', xaxis: { type: 'category' }, legend: { orientation: 'h', y: -0.3, font: { size: 10.5 } } }), plotCfg);
}

init().catch(e => { $('#title').textContent = 'Could not load plot ' + KEY + ': ' + e.message; document.body.dataset.ready = 'error'; });

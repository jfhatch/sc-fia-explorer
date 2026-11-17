// SC FIA plot explorer (static site): plot page. Port of app/static/plot.js + fiasc/plotdata.py for a static host:
// everything comes from p/<key>.json (visit metrics, species, events, growth intervals and tree links computed and
// validated by the Python build) and the shared code dictionary.
'use strict';
const KEY = new URLSearchParams(location.search).get('k') || '';
const PL = { P: null, vi: null, hist: null };
window.PLOT = PL;
const UNADJ = () => FIA.meta.unadj_note;
const plotCfg = { displaylogo: false, responsive: true, modeBarButtonsToRemove: ['lasso2d', 'select2d', 'toImage'] };
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

async function init() {
  if (!/^\d+-\d+-\d+-\d+$/.test(KEY)) throw new Error('missing or invalid plot key');
  const [meta, codes, P] = await Promise.all([loadMeta(), loadCodes(), getJSON(`p/${encodeURIComponent(KEY)}.json`)]);
  PL.P = P;
  footer();
  const county = (meta.counties.find(c => c.code === P.c) || {}).name || '';
  document.title = `FIA plot ${P.k}`;
  $('#title').textContent = `Plot ${P.k} · ${county} County, SC`;
  const lastV = P.v[P.v.length - 1];
  if (lastV && parseInt(lastV.d, 10) < ACTIVE_FROM) $('#title').insertAdjacentHTML('afterend', `<p>${histBadge(lastV.d)}</p>`);
  const last = P.v[P.v.length - 1];
  $('#subtitle').innerHTML = `STATECD ${P.s} · UNITCD ${P.u} · COUNTYCD ${P.c} · PLOT ${P.p} · public location ${fmt(P.la, 5)}, ${fmt(P.lo, 5)} (fuzzed) ·
    ${P.v.length} visit${P.v.length > 1 ? 's' : ''} (${esc(P.dsg)}) · owner group ${dvs(decode('COND.OWNGRPCD', P.og), 30)} · latest forest type ${esc(ftName(P.ft) || 'none (no accessible forest)')}`;
  const notes = [esc(meta.coord_note), esc(meta.unadj_note)];
  if (P.cd) notes.push('<b>The public coordinates differ between visits</b> (the latest visit\'s are shown on the map).');
  if (P.nc > 1) notes.push(`<b>${P.nc} separate PREV_PLT_CN chains share this location key</b>: some visits are not database-linked to each other.`);
  $('#notes').innerHTML = notes.join('<br>');
  $('#csv_trees').onclick = () => download(`fia_${P.k}_trees.csv`, treeCsv());
  $('#csv_visits').onclick = () => download(`fia_${P.k}_visits.csv`, visitCsv());
  $('#print').onclick = () => window.print();
  renderTimeline(P);
  renderTotals(P);
  selectVisit(P.v.length - 1);
  PL.hist = history(P);
  renderHistory(PL.hist);
  document.body.dataset.ready = '1';
}

// ---------------------------------------------------------------- header
function renderTimeline(P) {
  const preds = P.pc || [];
  $('#tldesc').innerHTML = `Survey dates from PLOT MEASYEAR-MEASMON-MEASDAY (periodic plots often lack the day: shown to the month, marked *).` +
    (preds.length ? ` Dashed cards are periodic plots that are <b>inferred candidates, not database-linked</b> predecessors (ranked by score).` : '');
  const pc = preds.slice(0, 3).map(p => `<div class="tc pred"><div class="d">${esc(p.last)}</div><div>Periodic plot ${esc(p.key)} · INVYR ${p.invyr}</div>
      <span class="tag">inferred candidate, not database-linked</span><div class="muted">rank ${p.rank} · score ${fmt(p.score, 0)}/100 · ${fmt(p.dist, 2)} mi</div></div>`);
  const vis = P.v.map((v, i) => `<div class="tc" data-vi="${i}" tabindex="0"><div class="d">${esc(v.d)}${v.da ? '*' : ''}</div>
      <div>INVYR ${v.y} · ${esc(v.ds)}</div><div class="muted">KINDCD ${dvs(decode('PLOT.KINDCD', v.kc))}</div><div class="muted">DESIGNCD ${dvs(decode('PLOT.DESIGNCD', v.dc), 36)}</div>
      <div class="muted">${dvs(decode('PLOT.PLOT_STATUS_CD', v.st), 36)}${v.rp != null ? ` · REMPER ${fmt(v.rp)} yr` : ''}</div></div>`);
  $('#timeline').innerHTML = pc.concat(vis).join('');
  document.querySelectorAll('.tc[data-vi]').forEach(el => { el.onclick = () => selectVisit(+el.dataset.vi); el.onkeydown = e => { if (e.key === 'Enter') selectVisit(+el.dataset.vi); }; });
  if (preds.length) {
    $('#predbox').innerHTML = `<h3>Inferred periodic predecessor candidates (not database-linked)</h3>
      <p class="muted">Periodic plots in the same county within 1.5 mi (public, fuzzed coordinates) whose last measurement date + this plot's first-visit REMPER
      falls within 0.5 yr of the first national-design visit; scored 0–100 from bridge-tree matches (60), date fit (25) and distance (15).</p>
      <div class="scroll"><table><thead><tr><th>Rank</th><th>Periodic plot</th><th>Last measured</th><th>Forest type, age</th><th class="n">Distance mi</th>
      <th class="n">Date fit yr</th><th>Bridge trees matched</th><th class="n">Score</th></tr></thead><tbody>` +
      preds.map(p => `<tr><td>${p.rank}</td><td><a href="${plotUrl(p.key)}">${esc(p.key)}</a></td><td>${esc(p.last)} (INVYR ${p.invyr})</td>
        <td>${esc(ftName(p.ft))}${p.age != null ? `, ${p.age} yr` : ''}</td><td class="n">${fmt(p.dist, 2)}</td><td class="n">${fmt(p.dt, 2)}</td>
        <td>${p.nb ? `${p.nm} of ${p.nb}${p.pairs ? ': ' + esc(p.pairs) : ''}` : 'no bridge records'}</td><td class="n">${fmt(p.score, 0)}</td></tr>`).join('') + '</tbody></table></div>';
  } else if ((P.cf || []).length) {
    $('#predbox').innerHTML = `<p class="muted">This periodic plot is an inferred predecessor candidate (not database-linked) of: ` +
      P.cf.map(c => `<a href="${plotUrl(c.key)}">${esc(c.key)}</a> (rank ${c.rank}, score ${fmt(c.score, 0)})`).join(', ') + '.</p>';
  }
}
function renderTotals(P) {
  const rows = P.v.map(v => `<tr data-invyr="${v.y}"><td>${esc(v.d)}</td><td>${v.y}</td><td>${esc(v.ds)}${v.ds === 'periodic' ? ' †' : ''}</td>
     <td class="n" data-ba="${met(v, 'ba') ?? ''}">${fmt(met(v, 'ba'), 1)}</td><td class="n">${fmt(met(v, 'live_tpa'), 0)}</td><td class="n">${fmt(met(v, 'carbon'), 1)}</td>
     <td class="n">${fmt(met(v, 'vol'), 0)}</td><td>${esc(ftName(v.ft))}</td><td class="n">${fmt(v.ag, 0)}</td><td class="n">${v.ni ?? 0}</td></tr>`).join('');
  $('#totals').innerHTML = `<thead><tr><th>Survey date</th><th>INVYR</th><th>Design</th><th class="n">Live BA ft²/ac</th><th class="n">Live trees/ac</th>
     <th class="n">Carbon t/ac</th><th class="n">Net vol ft³/ac</th><th>Forest type (dominant forest condition)</th><th class="n">Stand age</th><th class="n">Invasive spp.</th></tr></thead><tbody>${rows}</tbody>
     <tfoot><tr><td colspan="10" class="muted">Live trees ≥1.0 in on subplots 1–4 (bridge records on SUBP &gt; 4 excluded); Σ(value × TPA_UNADJ). † periodic design: not comparable with national-design visits.</td></tr></tfoot>`;
}

// ---------------------------------------------------------------- visit tabs
const TABS = [['cond', 'Conditions'], ['metrics', 'Stand metrics'], ['species', 'Species'], ['trees', 'Trees'], ['seed', 'Seedlings'],
  ['site', 'Site trees'], ['veg', 'P2 vegetation'], ['inv', 'Invasives'], ['dwm', 'Down woody material'], ['soils', 'Soils'], ['plot', 'PLOT record']];
let curTab = 'metrics';
const forVisit = (b, vi) => rowsOf(b).filter(r => r.vi === vi);
function selectVisit(vi) {
  const P = PL.P, v = P.v[vi];
  PL.vi = vi;
  document.querySelectorAll('.tc[data-vi]').forEach(el => el.classList.toggle('sel', +el.dataset.vi === vi));
  $('#vsel').textContent = `— ${v.d} (INVYR ${v.y}, ${v.ds})`;
  const n = b => b ? b.r.filter(r => r[0] === vi).length : 0;
  const has = { cond: n(P.cn), metrics: 1, species: n(P.sp), trees: n(P.tr), seed: n(P.sd), site: n(P.st), veg: n(P.p2s) + n(P.p2v), inv: 1,
    dwm: Object.values(P.dwm || {}).some(b => n(b)), soils: Object.values(P.so || {}).some(b => n(b)), plot: 1 };
  $('#tabs').innerHTML = TABS.map(([k, l]) => `<button type="button" data-t="${k}" class="${k === curTab ? 'on' : ''}" ${has[k] ? '' : 'disabled title="no records for this visit"'}>${l}</button>`).join('');
  document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => { curTab = b.dataset.t; document.querySelectorAll('#tabs button').forEach(x => x.classList.toggle('on', x === b)); renderTab(); });
  if (!has[curTab]) curTab = 'metrics';
  renderTab();
}
function fieldsHtml(table, rec) {
  return `<div class="fields">${Object.entries(rec).filter(([c, v]) => c !== 'vi' && v !== null).map(([c, v]) => `<div><b>${esc(c)}</b>: ${dv(decodeCell(table, c, v))}</div>`).join('')}</div>`;
}
function genericTable(b, table, vi) {
  const rows = forVisit(b, vi);
  if (!rows.length) return `<p class="muted">${esc(table)}: no records for this visit.</p>`;
  const cols = b.c.filter(c => c !== 'vi' && rows.some(r => r[c] !== null));
  return `<h3>${esc(table)} (${rows.length})</h3><div class="scroll"><table><thead><tr>${cols.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>` +
    rows.map(r => '<tr>' + cols.map(c => `<td>${dv(decodeCell(table, c, r[c]))}</td>`).join('') + '</tr>').join('') + '</tbody></table></div>';
}
function renderTab() {
  const P = PL.P, vi = PL.vi, v = P.v[vi], el = $('#tab');
  if (curTab === 'cond') el.innerHTML = forVisit(P.cn, vi).map(c => `<h3>Condition ${c.CONDID ?? ''}</h3>${fieldsHtml('COND', c)}`).join('');
  else if (curTab === 'plot') el.innerHTML = forVisit(P.pf, vi).map(r => fieldsHtml('PLOT', r)).join('');
  else if (curTab === 'metrics') {
    const k = (l, val, u) => `<div class="kpi"><div class="l">${l}</div><div class="v">${val}</div><div class="u">${u}</div></div>`;
    const m = key => met(v, key);
    el.innerHTML = `<div class="kpis">${k('Live basal area', fmt(m('ba')), 'ft²/ac')}${k('Live trees', fmt(m('live_tpa'), 0), `trees/ac (${m('live_n') ?? 0} tallied)`)}
      ${k('Trees ≥5 in', fmt(m('tpa5'), 0), 'trees/ac')}${k('Saplings 1–4.9 in', fmt(m('sap_tpa'), 0), 'trees/ac')}${k('QMD', fmt(m('qmd')), 'in')}
      ${k('Net cubic volume', fmt(m('vol'), 0), 'ft³/ac')}${k('Aboveground carbon', fmt(m('carbon'), 2), 'tons C/ac')}${k('Standing dead', fmt(m('dead_tpa'), 0), `trees/ac (${m('dead_n') ?? 0} tallied), ${fmt(m('dead_ba'))} ft²/ac`)}</div>
      <h3>Trees per acre by size class</h3><div class="scroll" style="max-height:none"><table><thead><tr><th>Status</th><th class="n">1.0–4.9 in</th><th class="n">5.0–9.9 in</th><th class="n">10.0–19.9 in</th><th class="n">≥20 in</th></tr></thead>
      <tbody><tr><td>Live</td>${['c1', 'c2', 'c3', 'c4'].map(c => `<td class="n">${fmt(m('live_tpa_' + c), 1)}</td>`).join('')}</tr>
      <tr><td>Standing dead</td>${['c1', 'c2', 'c3', 'c4'].map(c => `<td class="n">${fmt(m('dead_tpa_' + c), 1)}</td>`).join('')}</tr></tbody></table></div>
      <p class="muted">${esc(UNADJ())}</p>`;
  } else if (curTab === 'species') {
    const sp = forVisit(P.sp, vi).sort((a, b) => (b.ba || 0) - (a.ba || 0)), tot = sp.reduce((a, s) => a + (s.ba || 0), 0);
    el.innerHTML = `<div class="scroll"><table><thead><tr><th>Species</th><th class="n">Live trees</th><th class="n">Live TPA</th><th class="n">TPA ≥5 in</th><th class="n">BA ft²/ac</th>
      <th class="n">% BA</th><th class="n">Vol ft³/ac</th><th class="n">Carbon t/ac</th><th class="n">Dead trees</th><th class="n">Dead TPA</th></tr></thead><tbody>` +
      sp.map(s => `<tr><td>${esc(spName(s.SPCD))} <span class="muted">(${s.SPCD})</span></td><td class="n">${s.live_n ?? 0}</td><td class="n">${fmt(s.live_tpa, 1)}</td>
        <td class="n">${fmt(s.tpa5, 1)}</td><td class="n">${fmt(s.ba, 2)}</td><td class="n">${tot ? fmt(100 * (s.ba || 0) / tot, 1) : '—'}</td><td class="n">${fmt(s.vol, 0)}</td>
        <td class="n">${fmt(s.carbon, 2)}</td><td class="n">${s.dead_n ?? 0}</td><td class="n">${fmt(s.dead_tpa, 1)}</td></tr>`).join('') + '</tbody></table></div>';
  } else if (curTab === 'trees') {
    const cols = ['SUBP', 'TREE', 'STATUSCD', 'SPCD', 'DIA', 'HT', 'ACTUALHT', 'CR', 'CCLCD', 'TREECLCD', 'AGENTCD', 'DAMAGE_AGENT_CD1', 'DECAYCD', 'MORTYR', 'RECONCILECD', 'TPA_UNADJ', 'VOLCFNET', 'CARBON_AG'];
    const tr = forVisit(P.tr, vi);
    el.innerHTML = `<p class="muted">${tr.length} TREE records. Rows on SUBP &gt; 4 are periodic-to-annual bridge records (excluded from totals). “linked” = has PREV_TRE_CN.</p>
      <div class="scroll"><table><thead><tr><th>Tree</th>${cols.map(c => `<th>${c}</th>`).join('')}<th class="n">BA ft²/ac</th><th>linked</th></tr></thead><tbody>` +
      tr.map(t => `<tr${t.SUBP > 4 ? ' class="muted"' : ''}><td>${esc(P.tl[t.ti])}</td>${cols.map(c => `<td>${dv(decodeCell('TREE', c, t[c]))}</td>`).join('')}
        <td class="n">${t.DIA != null && t.TPA_UNADJ != null ? fmt(BA_K * t.DIA ** 2 * t.TPA_UNADJ, 3) : '—'}</td><td>${t.pv ? 'yes' : ''}</td></tr>`).join('') + '</tbody></table></div>';
  } else if (curTab === 'seed') el.innerHTML = genericTable(P.sd, 'SEEDLING', vi);
  else if (curTab === 'site') el.innerHTML = genericTable(P.st, 'SITETREE', vi);
  else if (curTab === 'veg') el.innerHTML = genericTable(P.p2s, 'P2VEG_SUBP_STRUCTURE', vi) + genericTable(P.p2v, 'P2VEG_SUBPLOT_SPP', vi);
  else if (curTab === 'inv') {
    const iv = forVisit(P.iv, vi), by = {};
    iv.forEach(r => (by[r.VEG_SPCD] = by[r.VEG_SPCD] || []).push(r));
    const pf = forVisit(P.pf, vi)[0] || {};
    el.innerHTML = `<p>Invasive sampling: ${dv(decode('PLOT.INVASIVE_SAMPLING_STATUS_CD', pf.INVASIVE_SAMPLING_STATUS_CD))}</p>` + (iv.length ? `<div class="scroll" style="max-height:none"><table><thead><tr><th>Species</th><th>Symbol</th>
      <th>Subplots</th><th class="n">Mean cover %</th></tr></thead><tbody>` + Object.entries(by).map(([s, g]) => { const [cn, sci] = plant(s);
        return `<tr><td>${esc(cn)} <i class="muted">${esc(sci)}</i></td><td>${esc(s)}</td><td>${g.map(r => r.SUBP).sort().join(', ')}</td>
        <td class="n">${fmt(g.reduce((a, r) => a + (r.COVER_PCT || 0), 0) / g.length)}</td></tr>`; }).join('') + '</tbody></table></div>' : '<p class="muted">No invasive plant records for this visit.</p>');
  } else if (curTab === 'dwm') el.innerHTML = Object.entries(P.dwm || {}).map(([t, b]) => genericTable(b, t, vi)).join('');
  else if (curTab === 'soils') el.innerHTML = Object.entries(P.so || {}).map(([t, b]) => genericTable(b, t, vi)).join('');
}

// ---------------------------------------------------------------- history (port of fiasc.plotdata.history)
const PAL = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'], OTHER = '#9a9893';
function entryFate(recs, P) {
  const g0 = recs[0], last = recs[recs.length - 1], Y = r => P.v[r.vi].y;
  const entry = g0.SUBP > 4 ? 'periodic-to-annual GRM record only (P2A_GRM_FLG); not a tallied tree'
    : g0.vi === 0 ? `tallied at first visit (${Y(g0)})` : `new in ${Y(g0)}: ${decode('TREE.RECONCILECD', g0.RECONCILECD).text}`;
  let fate;
  if (last.STATUSCD === 1) fate = `live at ${Y(last)}`;
  else if (last.STATUSCD === 0) fate = `left sample ${Y(last)}: ${decode('TREE.RECONCILECD', last.RECONCILECD).text}`;
  else if (last.STATUSCD === 3) fate = `cut by ${Y(last)}`;
  else { const d = recs.find(r => r.STATUSCD === 2); fate = `dead by ${Y(d)} (MORTYR ${d.MORTYR ?? ''}; AGENTCD ${decode('TREE.AGENTCD', d.AGENTCD).text})`; }
  return [entry, fate];
}
function history(P) {
  const YRS = P.v.map(v => v.y), H = { years: YRS };
  const sp = rowsOf(P.sp);
  if (!P.tr) return Object.assign(H, { empty: true });
  const tot = {}; sp.forEach(s => tot[s.SPCD] = (tot[s.SPCD] || 0) + (s.ba || 0));
  const rank = Object.keys(tot).map(Number).filter(s => tot[s] > 0).sort((a, b) => tot[b] - tot[a] || spName(a).localeCompare(spName(b)));
  const top = rank.slice(0, 7), grp = s => top.includes(s) ? spName(s) : 'Other species';
  const order = top.map(spName).concat(['Other species']);
  H.species = { order, colors: Object.fromEntries(order.map((g, i) => [g, i < top.length ? PAL[i] : OTHER])), other_n: rank.length - top.length, grp };
  H.stack = {};
  for (const [m, col] of [['ba', 'ba'], ['tpa', 'live_tpa'], ['carbon', 'carbon'], ['vol', 'vol']]) {
    H.stack[m] = Object.fromEntries(order.map(g => [g, YRS.map(() => 0)]));
    sp.forEach(s => { if (s[col]) H.stack[m][grp(s.SPCD)][s.vi] += s[col]; });
  }
  H.totals = { ba: P.v.map(v => met(v, 'ba') || 0), tpa: P.v.map(v => met(v, 'live_tpa') || 0), carbon: P.v.map(v => met(v, 'carbon') || 0), vol: P.v.map(v => met(v, 'vol') || 0) };
  const tr = rowsOf(P.tr).filter(r => r.SUBP <= 4), byT = new Map();
  tr.forEach(r => { if (!byT.has(r.ti)) byT.set(r.ti, []); byT.get(r.ti).push(r); });
  H.trees = [...byT.entries()].map(([ti, recs]) => { recs.sort((a, b) => a.vi - b.vi); const [entry, fate] = entryFate(recs, P);
    const s = recs[recs.length - 1].SPCD;
    return { id: P.tl[ti], sp: spName(s), spg: grp(s), entry, fate, pts: recs.map(r => ({ y: P.v[r.vi].y, dia: r.DIA, ht: r.HT, st: r.STATUSCD })) }; })
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
function renderHistory(H) {
  if (H.empty) { $('#hist').innerHTML = '<p class="muted">No TREE records at this location key.</p>'; return; }
  const X = H.years.map(String), P = PL.P;
  $('#hist').innerHTML = `
    <div class="actions noprint"><label>Stacked metric <select id="h_metric"><option value="ba">Basal area ft²/ac</option><option value="tpa">Trees/ac</option>
      <option value="carbon">Aboveground carbon tons C/ac</option><option value="vol">Net cubic volume ft³/ac</option></select></label></div>
    <div id="c_stack" class="chart"></div>
    <div class="grid2"><div><div class="actions noprint"><label>Tree history <select id="h_tm"><option value="dia">DBH (in)</option><option value="ht">Height (ft)</option></select></label>
      <label>Species <select id="h_sp"><option value="">All</option></select></label></div><div id="c_trees" class="chart"></div></div>
      <div><div id="c_growth" class="chart"></div></div></div>
    <div class="grid2"><div><div class="actions noprint"><label>Mortality as <select id="h_mm"><option value="tpa">trees/ac</option><option value="ba_ac">BA ft²/ac</option><option value="n">trees tallied</option></select></label></div>
      <div id="c_mort" class="chart"></div></div><div><div class="actions"><span class="muted">Additions by RECONCILECD; microplot-relocation additions are separated from ingrowth${H.microplot_moved.length ? ` (microplot moved at ${H.microplot_moved.join(', ')})` : ''}.</span></div>
      <div id="c_ing" class="chart"></div></div></div>
    <h3>Individual trees (${H.trees.length})</h3>
    <div class="scroll"><table><thead><tr><th>Tree</th><th>Species</th><th>Entry</th><th>Fate</th>${X.map(y => `<th class="n">${y}</th>`).join('')}</tr></thead><tbody>` +
    H.trees.map(t => { const by = Object.fromEntries(t.pts.map(p => [p.y, p]));
      return `<tr><td>${esc(t.id)}</td><td>${esc(t.sp)}</td><td>${esc(t.entry)}</td><td>${esc(t.fate)}</td>${H.years.map(y => { const p = by[y];
        return `<td class="n">${p ? (p.st === 1 ? fmt(p.dia, 1) : p.st === 2 ? `<span title="dead">✝ ${fmt(p.dia, 1)}</span>` : p.st === 3 ? 'cut' : '–') : ''}</td>`; }).join('')}</tr>`; }).join('') +
    '</tbody></table></div><p class="muted">' + esc(UNADJ()) + '</p>';
  const order = H.species.order, col = H.species.colors;
  const lab = g => g === 'Other species' ? `Other species (${H.species.other_n})` : g;
  const drawStack = () => {
    const m = $('#h_metric').value;
    const tr = order.map(g => ({ x: X, y: H.stack[m][g], name: lab(g), type: 'scatter', mode: 'lines', stackgroup: 'one', line: { width: 0.5, color: col[g] },
      fillcolor: col[g], hovertemplate: `${esc(lab(g))}: %{y:.2f}<extra></extra>` }));
    tr.push({ x: X, y: H.totals[m], name: 'Total', mode: 'markers+text', text: H.totals[m].map(v => v.toFixed(m === 'carbon' ? 1 : 0)), textposition: 'top center',
      marker: { size: 1, color: 'rgba(0,0,0,0)' }, showlegend: false, hovertemplate: 'Total %{y:.2f}<extra></extra>', type: 'scatter' });
    Plotly.react('c_stack', tr, lay({ title: { text: $('#h_metric').selectedOptions[0].text + ' by species (live)', x: 0 }, xaxis: { type: 'category', title: 'INVYR' }, hovermode: 'x unified' }), plotCfg);
  };
  $('#h_metric').onchange = drawStack; drawStack();
  [...new Set(H.trees.map(t => t.sp))].sort().forEach(s => $('#h_sp').append(new Option(s, s)));
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
      { x: G.map(g => g.hi - g.lo), base: G.map(g => g.lo), y: G.map(g => g.sp), type: 'bar', orientation: 'h', marker: { color: 'rgba(154,152,147,.45)' }, width: 0.18, name: 'range', hoverinfo: 'skip' },
      { x: G.map(g => g.mean), y: G.map(g => g.sp), mode: 'markers', type: 'scatter', name: 'mean', marker: { size: 11, color: G.map(g => col[order.includes(g.sp) ? g.sp : 'Other species']), line: { width: 1, color: '#222' } },
        customdata: G.map(g => [g.n, g.median, g.lo, g.hi]), hovertemplate: '%{y}: mean %{x:.3f} in/yr<br>n=%{customdata[0]}, median %{customdata[1]:.3f}, range %{customdata[2]:.3f} to %{customdata[3]:.3f}<extra></extra>' }],
      lay({ title: { text: 'Annual DBH growth by species (mean, range)', x: 0 }, xaxis: { title: 'in/yr' }, yaxis: { autorange: 'reversed', automargin: true }, showlegend: false, margin: { l: 140, r: 20, t: 36, b: 50 } }), plotCfg);
  } else $('#c_growth').innerHTML = '<p class="muted">No tree was live at two consecutive visits.</p>';
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
  const cls = ['ingrowth (RECONCILECD 1)', 'other addition', 'microplot relocation addition', 'microplot relocation drop', 'removed from sample', 'cut', 'dead at first tally'];
  const ccol = { 'ingrowth (RECONCILECD 1)': '#1baf7a', 'other addition': '#eda100', 'microplot relocation addition': '#2a78d6', 'microplot relocation drop': '#9a9893',
    'removed from sample': '#52514e', 'cut': '#e34948', 'dead at first tally': '#6250d6' };
  const tr = cls.map(c => ({ x: ivls, y: ivls.map(iv => H.events.filter(e => e.cls === c && e.ivl === iv).length), name: c, type: 'bar', marker: { color: ccol[c] },
    hovertemplate: `${c}<br>%{x}: %{y} trees<extra></extra>` })).filter(t => t.y.some(v => v));
  Plotly.react('c_ing', tr.length ? tr : [{ x: ivls, y: ivls.map(() => 0), type: 'bar', name: 'no additions' }],
    lay({ title: { text: 'Additions and other sample changes (trees tallied)', x: 0 }, barmode: 'group', xaxis: { type: 'category' }, legend: { orientation: 'h', y: -0.3, font: { size: 10.5 } } }), plotCfg);
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
function download(name, text) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
  a.download = name; document.body.append(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

init().catch(e => { $('#title').textContent = 'Could not load plot ' + KEY + ': ' + e.message; document.body.dataset.ready = 'error'; });

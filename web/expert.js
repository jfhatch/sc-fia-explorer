// Expert view panels for the plot page (presentation only: the same public data and calculations as Standard view).
// Loaded with the plot page but does nothing until Expert view is on; x/<key>.json is fetched only then.
'use strict';
(function () {
  const XS = { loading: null, treeCols: null, sort: { c: null, dir: 1 }, filter: '' };
  const codeVal = (table, col, v) => v == null ? '<span class="muted">—</span>' : dv(decodeCell(table, col, v));
  const codeShort = (table, col, v) => v == null ? '' : dvs(decodeCell(table, col, v), 26);     // dense tables: full text on hover
  const kvx = (table, rec, cols) => `<div class="kvx">${cols.filter(c => c in rec).map(c => `<div class="k">${esc(c)}<button type="button" class="hb" data-h="${esc(table + '.' + c)}" aria-label="About ${esc(c)}">ⓘ</button></div><div class="v">${codeVal(table, c, rec[c])}</div>`).join('')}</div>`;
  const live = (P, vi) => rowsOf(P.tr).filter(t => t.vi === vi && t.STATUSCD === 1 && t.TPA_UNADJ != null && t.DIA != null);

  async function loadX(PL) {
    if (PL.X) return PL.X;
    if (!XS.loading) XS.loading = getJSON(`x/${encodeURIComponent(PL.P.k)}.json`).then(x => (PL.X = x));
    return XS.loading;
  }
  window.renderExpert = async function (PL) {
    const el = $('#expert');
    el.innerHTML = 'Loading expert records…';
    let X;
    try { X = await loadX(PL); } catch (e) { el.innerHTML = `<p class="bad">Could not load expert records: ${esc(e.message)}</p>`; return; }
    if (!isExpert()) return;
    const P = PL.P, vi = PL.vi, v = P.v[vi];
    $('#xsel').textContent = `— ${v.d} (INVYR ${v.y})`;
    el.innerHTML = [meta(P, X, vi), conds(P, vi), structure(P, PL, vi), treeTable(P, X, vi), grm(P, X, vi), subplots(P, X, vi), raw(P, X)].join('');
    drawStructure(P, PL, vi);
    wireTreeTable(P, X, vi);
    wireRaw(P, X);
    document.body.dataset.expertReady = '1';
  };

  // ---------------------------------------------------------------- plot/visit metadata
  function meta(P, X, vi) {
    const pf = rowsOf(P.pf).find(r => r.vi === vi) || {}, v = P.v[vi];
    const chain = P.v.map((x, i) => `<div class="k">${esc(x.d)}</div><div class="v"><code>${esc(x.cn)}</code>${x.pp ? ` ← PREV_PLT_CN <code>${esc(x.pp)}</code>` : ' (no PREV_PLT_CN)'}${i === vi ? ' ◀' : ''}</div>`).join('');
    const cols = ['INVYR', 'MEASYEAR', 'MEASMON', 'MEASDAY', 'CYCLE', 'SUBCYCLE', 'P2PANEL', 'SUBPANEL', 'KINDCD', 'DESIGNCD', 'MANUAL', 'REMPER', 'PLOT_STATUS_CD',
      'PLOT_NONSAMPLE_REASN_CD', 'SAMP_METHOD_CD', 'QA_STATUS', 'INTENSITY', 'MICROPLOT_LOC', 'ELEV', 'ECOSUBCD', 'INVASIVE_SAMPLING_STATUS_CD', 'P2VEG_SAMPLING_STATUS_CD'];
    const ps = rowsOf(X.ppsa).filter(r => r.vi === vi);
    return `<h3>Plot and visit metadata</h3>${intro('plotrec')}<div class="xgrid"><div><div class="kvx"><div class="k">PLT_CN</div><div class="v"><code>${esc(v.cn)}</code></div>`
      + `<div class="k">STATECD-UNITCD-COUNTYCD-PLOT</div><div class="v">${P.s}-${P.u}-${P.c}-${P.p}</div></div>${kvx('PLOT', pf, cols)}</div>`
      + `<div><h4>PREV_PLT_CN chain</h4><div class="kvx">${chain}</div><h4>POP_PLOT_STRATUM_ASSGN (evaluations, strata)</h4>`
      + (ps.length ? tbl(['EVALID', 'ESTN_UNIT', 'STRATUMCD', 'RSCD'].map(c => ({ k: 'POP_PLOT_STRATUM_ASSGN.' + c })), ps.map(r => [r.EVALID, r.ESTN_UNIT, r.STRATUMCD, r.RSCD]), { noMax: false })
        : '<p class="muted">No stratum assignment for this visit.</p>') + '</div></div>';
  }
  // ---------------------------------------------------------------- conditions
  function conds(P, vi) {
    const cols = ['CONDID', 'CONDPROP_UNADJ', 'COND_STATUS_CD', 'OWNCD', 'OWNGRPCD', 'RESERVCD', 'FORTYPCD', 'FLDTYPCD', 'FORTYPCDCALC', 'STDSZCD', 'FLDSZCD', 'STDAGE', 'FLDAGE',
      'SITECLCD', 'SICOND', 'SIBASE', 'SISP', 'PHYSCLCD', 'SLOPE', 'ASPECT', 'DSTRBCD1', 'DSTRBYR1', 'DSTRBCD2', 'DSTRBYR2', 'DSTRBCD3', 'DSTRBYR3', 'TRTCD1', 'TRTYR1', 'TRTCD2', 'TRTYR2',
      'TRTCD3', 'TRTYR3', 'GSSTK', 'ALSTK', 'GSSTKCD', 'ALSTKCD', 'BALIVE', 'CARBON_DOWN_DEAD', 'CARBON_LITTER', 'CARBON_SOIL_ORG', 'CARBON_UNDERSTORY_AG', 'CARBON_UNDERSTORY_BG'];
    const cs = rowsOf(P.cn).filter(r => r.vi === vi);
    return `<h3>Conditions (${cs.length})</h3><div class="xgrid">` + (cs.length ? cs.map(c => `<div><h4>CONDID ${c.CONDID}</h4>${kvx('COND', c, cols)}</div>`).join('') : '<p class="muted">No COND records.</p>') + '</div>';
  }
  // ---------------------------------------------------------------- stand structure
  const dclass = d => { const k = Math.floor((d - 1) / 2), lo = 1 + 2 * k; return [k, `${lo.toFixed(1)}–${(lo + 1.9).toFixed(1)}`]; };
  function standTable(P, vi) {
    const L = live(P, vi), by = new Map();
    for (const t of L) {
      const [k, lab] = dclass(t.DIA), key = k + '|' + t.SPCD;
      const o = by.get(key) || { k, lab, sp: t.SPCD, tpa: 0, ba: 0, vol: 0 };
      o.tpa += t.TPA_UNADJ; o.ba += BA_K * t.DIA ** 2 * t.TPA_UNADJ; o.vol += (t.VOLCFNET || 0) * t.TPA_UNADJ; by.set(key, o);
    }
    return [...by.values()].sort((a, b) => a.k - b.k || b.ba - a.ba);
  }
  window.EXPERT_standTable = standTable;          // read by the test (hand-calculation check)
  function structure(P, PL, vi) {
    const s = PL.S.v[vi], rows = standTable(P, vi), cls = [...new Set(rows.map(r => r.k))];
    const sdi = s.tpa && s.qmd ? s.tpa * Math.pow(s.qmd / 10, 1.605) : null;
    const c = rowsOf(P.cn).filter(r => r.vi === vi).sort((a, b) => (b.CONDPROP_UNADJ || 0) - (a.CONDPROP_UNADJ || 0))[0] || {};
    const body = [];
    for (const k of cls) {
      const g = rows.filter(r => r.k === k);
      g.forEach((r, i) => body.push([i ? '' : `<b>${esc(r.lab)}</b>`, esc(spName(r.sp)), fmt(r.tpa, 1), fmt(r.ba, 2), fmt(r.vol, 1)]));
      if (g.length > 1) body.push(['', '<i>class total</i>', `<i>${fmt(g.reduce((a, r) => a + r.tpa, 0), 1)}</i>`, `<i>${fmt(g.reduce((a, r) => a + r.ba, 0), 2)}</i>`, `<i>${fmt(g.reduce((a, r) => a + r.vol, 0), 1)}</i>`]);
    }
    body.push(['<b>All</b>', '', `<b>${fmt(rows.reduce((a, r) => a + r.tpa, 0), 1)}</b>`, `<b>${fmt(rows.reduce((a, r) => a + r.ba, 0), 2)}</b>`, `<b>${fmt(rows.reduce((a, r) => a + r.vol, 0), 1)}</b>`]);
    return `<h3>Stand structure</h3><div class="kpis">`
      + `<div class="kpi"><div class="l">QMD<button type="button" class="hb" data-h="d:qmd" aria-label="About QMD">ⓘ</button></div><div class="v" id="x_qmd">${fmt(s.qmd, 2)}</div><div class="u">in</div></div>`
      + `<div class="kpi"><div class="l">SDI (Reineke)<button type="button" class="hb" data-h="d:sdi" aria-label="About SDI">ⓘ</button></div><div class="v" id="x_sdi" data-sdi="${sdi ?? ''}">${fmt(sdi, 0)}</div><div class="u">SDI = TPA × (QMD ÷ 10)^1.605 = ${fmt(s.tpa, 1)} × (${fmt(s.qmd, 2)} ÷ 10)^1.605</div></div>`
      + `<div class="kpi"><div class="l">Growing-stock stocking<button type="button" class="hb" data-h="COND.GSSTK" aria-label="About GSSTK">ⓘ</button></div><div class="v">${fmt(c.GSSTK, 1)}</div><div class="u">% (COND.GSSTK, as reported by FIA) · GSSTKCD ${codeVal('COND', 'GSSTKCD', c.GSSTKCD)}</div></div>`
      + `<div class="kpi"><div class="l">All-live stocking<button type="button" class="hb" data-h="COND.ALSTK" aria-label="About ALSTK">ⓘ</button></div><div class="v">${fmt(c.ALSTK, 1)}</div><div class="u">% (COND.ALSTK, as reported by FIA) · ALSTKCD ${codeVal('COND', 'ALSTKCD', c.ALSTKCD)}</div></div></div>`
      + `<p class="muted">Stocking is FIA's reported value for the largest condition; this site does not compute FIA stocking. SDI uses this visit's live trees ≥1.0 in (unadjusted per-acre values).</p>`
      + `<div class="grid2"><div>${tbl([{ k: 'd:dclass' }, { k: 'd:species' }, { k: 'd:tpa', n: 1 }, { k: 'd:ba', n: 1 }, { k: 'd:vol', n: 1 }], body, { id: 'x_stand' })}</div><div id="x_ddist" class="chart"></div></div>`
      + `<div class="grid2"><div id="x_hd" class="chart"></div><div><div id="x_ccl" class="chart" style="height:200px"></div><div id="x_cr" class="chart" style="height:200px"></div></div></div>`;
  }
  function drawStructure(P, PL, vi) {
    const L = live(P, vi);
    if (!L.length) { ['x_ddist', 'x_hd', 'x_ccl', 'x_cr'].forEach(id => { const e = document.getElementById(id); if (e) e.innerHTML = '<p class="muted">No live trees at this visit.</p>'; }); return; }
    const rows = standTable(P, vi), cls = [...new Set(rows.map(r => r.k))].sort((a, b) => a - b), labs = cls.map(k => rows.find(r => r.k === k).lab);
    const top = (PL.S.top || []).slice(0, 7), PALX = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6'];
    const grpOf = sp => top.includes(sp) ? spName(sp) : 'other species', groups = [...new Set(rows.map(r => grpOf(r.sp)))];
    Plotly.react('x_ddist', groups.map(g => ({ x: labs, y: cls.map(k => rows.filter(r => r.k === k && grpOf(r.sp) === g).reduce((a, r) => a + r.tpa, 0)), name: g, type: 'bar',
      marker: { color: g === 'other species' ? '#9a9893' : PALX[top.map(spName).indexOf(g)] } })),
      lay({ title: { text: 'Diameter distribution (trees/ac by 2-in class)', x: 0 }, barmode: 'stack', xaxis: { title: 'DBH class (in)', type: 'category' }, yaxis: { title: 'trees/ac' } }), plotCfg);
    const hd = L.filter(t => t.HT != null), sps = [...new Set(hd.map(t => grpOf(t.SPCD)))];
    Plotly.react('x_hd', sps.map(g => { const ts = hd.filter(t => grpOf(t.SPCD) === g); return { x: ts.map(t => t.DIA), y: ts.map(t => t.HT), mode: 'markers', type: 'scatter', name: g,
      marker: { size: 8, color: g === 'other species' ? '#9a9893' : PALX[top.map(spName).indexOf(g)], line: { width: 1, color: '#222' } }, text: ts.map(t => PL.P.tl[t.ti]), hovertemplate: '%{text}: %{x} in, %{y} ft<extra>' + esc(g) + '</extra>' }; }),
      lay({ title: { text: 'Height vs. diameter (live trees)', x: 0 }, xaxis: { title: 'DIA (in)' }, yaxis: { title: 'HT (ft)' } }), plotCfg);
    const cc = {}; L.forEach(t => { const k = t.CCLCD == null ? 'not recorded' : decode('TREE.CCLCD', t.CCLCD).text; cc[k] = (cc[k] || 0) + 1; });
    Plotly.react('x_ccl', [{ x: Object.values(cc), y: Object.keys(cc).map(s => s.length > 40 ? s.slice(0, 38) + '…' : s), type: 'bar', orientation: 'h', marker: { color: '#2a78d6' } }],
      lay({ title: { text: 'Crown class (CCLCD), live trees tallied', x: 0 }, margin: { l: 220, r: 10, t: 30, b: 30 }, yaxis: { automargin: true } }), plotCfg);
    const cr = L.filter(t => t.CR != null).map(t => t.CR);
    Plotly.react('x_cr', [{ x: cr, type: 'histogram', xbins: { start: 0, end: 100, size: 10 }, marker: { color: '#1baf7a' } }],
      lay({ title: { text: 'Crown ratio (CR, %), live trees tallied', x: 0 }, margin: { l: 40, r: 10, t: 30, b: 30 }, xaxis: { range: [0, 100] } }), plotCfg);
  }
  // ---------------------------------------------------------------- full tree table: column chooser, sort, filter, CSV of what is shown
  const TCOLS = ['SUBP', 'TREE', 'CONDID', 'SPCD', 'SPGRPCD', 'STATUSCD', 'DIA', 'DIAHTCD', 'HT', 'ACTUALHT', 'HTCD', 'CR', 'CCLCD', 'TREECLCD', 'DECAYCD', 'STANDING_DEAD_CD',
    'AGENTCD', 'DAMAGE_AGENT_CD1', 'DAMAGE_AGENT_CD2', 'DAMAGE_AGENT_CD3', 'MORTYR', 'RECONCILECD', 'TPA_UNADJ', 'VOLCFNET', 'VOLCFGRS', 'VOLBFNET', 'DRYBIO_AG', 'CARBON_AG', 'PREV_TRE_CN'];
  function treeRows(P, X, vi) {
    const tr = rowsOf(P.tr), xr = X.trx ? rowsOf(X.trx) : [];
    return tr.map((t, i) => Object.assign({ _i: i, _id: P.tl[t.ti] }, t, xr[i] || {})).filter(t => t.vi === vi);
  }
  function cellText(c, t) { const v = t[c]; if (v == null) return ''; const d = decodeCell('TREE', c, v); return d && d.text ? d.text : String(v); }
  function treeTable(P, X, vi) {
    XS.treeCols = XS.treeCols || TCOLS.slice();
    return `<h3>Tree records (full columns)</h3><div class="actions noprint"><label>Filter <input id="x_tf" type="search" value="${esc(XS.filter)}" placeholder="text in any shown column"></label>`
      + `<button type="button" id="x_tcsv">CSV of shown rows and columns</button><span class="muted" id="x_tn"></span></div>`
      + `<details class="noprint"><summary>Columns</summary><div class="chooser">${TCOLS.map(c => `<label><input type="checkbox" data-tc="${c}"${XS.treeCols.includes(c) ? ' checked' : ''}> ${c}</label>`).join('')}</div></details><div id="x_tt"></div>`;
  }
  function wireTreeTable(P, X, vi) {
    const draw = () => {
      const cols = TCOLS.filter(c => XS.treeCols.includes(c)), f = XS.filter.toLowerCase();
      let rows = treeRows(P, X, vi);
      if (f) rows = rows.filter(t => [t._id].concat(cols.map(c => cellText(c, t))).join(' ').toLowerCase().includes(f));
      if (XS.sort.c) { const c = XS.sort.c; rows.sort((a, b) => { const x = c === '_id' ? a._id : a[c], y = c === '_id' ? b._id : b[c];
        return XS.sort.dir * (x == null ? 1 : y == null ? -1 : typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true })); }); }
      XS.shown = { cols, rows };
      if (!rows.length) { $('#x_tt').innerHTML = `<p class="muted">${XS.filter ? 'No tree record matches the filter.' : 'No TREE records at this visit.'}</p>`; $('#x_tn').textContent = ''; return; }
      const head = th('d:tree_id').replace('<th', `<th data-xs="_id" aria-sort="${XS.sort.c === '_id' ? (XS.sort.dir > 0 ? 'ascending' : 'descending') : 'none'}" tabindex="0"`)
        + cols.map(c => th('TREE.' + c, { n: ['DIA', 'HT', 'ACTUALHT', 'CR', 'TPA_UNADJ', 'VOLCFNET', 'VOLCFGRS', 'VOLBFNET', 'DRYBIO_AG', 'CARBON_AG'].includes(c) })
          .replace('<th', `<th data-xs="${c}" aria-sort="${XS.sort.c === c ? (XS.sort.dir > 0 ? 'ascending' : 'descending') : 'none'}" tabindex="0"`)).join('');
      $('#x_tt').innerHTML = `<div class="scroll"><table class="sortable wide" id="x_trees"><thead><tr>${head}</tr></thead><tbody>` + rows.map(t => `<tr${t.SUBP > 4 && P.v[vi].ds === 'annual' ? ' class="muted"' : ''}><td>${esc(t._id)}</td>`
        + cols.map(c => `<td>${c === 'PREV_TRE_CN' ? (t[c] ? `<code>${esc(t[c])}</code>` : '') : codeShort('TREE', c, t[c])}</td>`).join('') + '</tr>').join('') + '</tbody></table></div>';
      $('#x_tn').textContent = `${rows.length} records shown`;
      $('#x_tt').querySelectorAll('th[data-xs]').forEach(h => { const go = () => { const c = h.dataset.xs; XS.sort = { c, dir: XS.sort.c === c ? -XS.sort.dir : 1 }; draw(); };
        h.onclick = e => { if (!e.target.closest('.hb')) go(); }; h.onkeydown = e => { if (e.key === 'Enter') go(); }; });
    };
    $('#x_tf').oninput = e => { XS.filter = e.target.value; draw(); };
    document.querySelectorAll('[data-tc]').forEach(cb => cb.onchange = () => { XS.treeCols = [...document.querySelectorAll('[data-tc]')].filter(x => x.checked).map(x => x.dataset.tc); draw(); });
    $('#x_tcsv').onclick = () => { const { cols, rows } = XS.shown; download(`fia_${P.k}_INVYR${P.v[vi].y}_trees_shown.csv`, toCsv(['tree'].concat(cols), rows.map(t => [t._id].concat(cols.map(c => cellText(c, t)))))); };
    draw();
  }
  // ---------------------------------------------------------------- GRM components (TREE_GRM_COMPONENT, as provided)
  function grm(P, X, vi) {
    const g = rowsOf(X.grm).filter(r => r.vi === vi);
    if (!g.length) return `<h3>Growth, removals and mortality components</h3><p class="muted">No TREE_GRM_COMPONENT records end at this visit (first visits and periodic visits have none).</p>`;
    const by = {};
    g.forEach(r => { const c = r.SUBP_COMPONENT_AL_FOREST || 'not assigned'; const o = by[c] || (by[c] = { n: 0, tg: 0, gr: 0, mo: 0, re: 0, dg: [] });
      o.n++; o.tg += r.SUBP_TPAGROW_UNADJ_AL_FOREST || 0; o.gr += (r.GROWCFAL_FOREST || 0) * (r.SUBP_TPAGROW_UNADJ_AL_FOREST || 0);
      o.mo += (r.MORTCFAL_FOREST || 0) * (r.SUBP_TPAMORT_UNADJ_AL_FOREST || 0); o.re += (r.REMVCFAL_FOREST || 0) * (r.SUBP_TPAREMV_UNADJ_AL_FOREST || 0); if (r.ANN_DIA_GROWTH != null) o.dg.push(r.ANN_DIA_GROWTH); });
    const prev = vi ? P.v[vi - 1] : null;
    return `<h3>Growth, removals and mortality components ${prev ? `(${esc(prev.d)} → ${esc(P.v[vi].d)})` : ''}</h3>`
      + tbl([{ k: 'TREE_GRM_COMPONENT.SUBP_COMPONENT_AL_FOREST' }, { k: 'd:grm_n', n: 1 }, { k: 'TREE_GRM_COMPONENT.SUBP_TPAGROW_UNADJ_AL_FOREST', n: 1, l: 'Σ TPAGROW_UNADJ' },
        { k: 'd:grm_grow', n: 1 }, { k: 'd:grm_mort', n: 1 }, { k: 'd:grm_remv', n: 1 }, { k: 'TREE_GRM_COMPONENT.ANN_DIA_GROWTH', n: 1, l: 'mean ANN_DIA_GROWTH' }],
        Object.entries(by).sort().map(([c, o]) => [esc(c), o.n, fmt(o.tg, 3), fmt(o.gr, 2), fmt(o.mo, 2), fmt(o.re, 2), o.dg.length ? fmt(o.dg.reduce((a, x) => a + x, 0) / o.dg.length, 3) : '—']), { id: 'x_grm' })
      + `<p class="muted">Values as provided in TREE_GRM_COMPONENT (all live trees on forest land, subplot-based columns), summed for this plot: per acre per year, <b>unadjusted</b> (TPA factors only, no stratum adjustment). `
      + `Growth = Σ GROWCFAL_FOREST × SUBP_TPAGROW_UNADJ_AL_FOREST (ft³/ac/yr); mortality and removals use MORTCFAL/REMVCFAL with their TPA factors.</p>`;
  }
  // ---------------------------------------------------------------- subplots
  function subplots(P, X, vi) {
    const sb = rowsOf(X.sbp).filter(r => r.vi === vi), sc = rowsOf(X.sbc).filter(r => r.vi === vi);
    const tr = rowsOf(P.tr).filter(t => t.vi === vi && t.TPA_UNADJ != null && t.STATUSCD === 1);
    const subs = [...new Set(sb.map(r => r.SUBP).concat(tr.map(t => t.SUBP)))].sort((a, b) => a - b);
    if (!subs.length) return '<h3>Subplots</h3><p class="muted">No SUBPLOT records for this visit.</p>';
    const rows = subs.map(s => { const t = tr.filter(x => x.SUBP === s), sap = t.filter(x => x.DIA < 5), big = t.filter(x => x.DIA >= 5), r = sb.find(x => x.SUBP === s) || {};
      const ba = {}; t.forEach(x => ba[x.SPCD] = (ba[x.SPCD] || 0) + BA_K * x.DIA ** 2 * x.TPA_UNADJ);
      const topsp = Object.entries(ba).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([c]) => spName(+c)).join(', ');
      return [s, codeVal('SUBPLOT', 'SUBP_STATUS_CD', r.SUBP_STATUS_CD), r.SUBPCOND ?? '—', r.MICRCOND ?? '—', big.length, sap.length,
        fmt(t.reduce((a, x) => a + x.TPA_UNADJ, 0), 1), fmt(t.reduce((a, x) => a + BA_K * x.DIA ** 2 * x.TPA_UNADJ, 0), 2), esc(topsp)]; });
    return `<h3>Subplots and microplots</h3>` + tbl([{ k: 'SUBPLOT.SUBP' }, { k: 'SUBPLOT.SUBP_STATUS_CD' }, { k: 'SUBPLOT.SUBPCOND' }, { k: 'SUBPLOT.MICRCOND' }, { k: 'd:sub_n5', n: 1 }, { k: 'd:sub_nsap', n: 1 },
      { k: 'd:sub_tpa', n: 1 }, { k: 'd:sub_ba', n: 1 }, { k: 'd:sub_comp' }], rows, { id: 'x_subp' })
      + `<p class="muted">Per-acre columns are each subplot's contribution to the plot's unadjusted per-acre totals (a subplot's trees carry the plot-level TPA_UNADJ).</p>`
      + (sc.length ? '<h4>SUBP_COND (condition mapping)</h4>' + tbl(['SUBP', 'CONDID', 'SUBPCOND_PROP', 'MICRCOND_PROP', 'MACRCOND_PROP', 'NONFR_INCL_PCT_SUBP', 'NONFR_INCL_PCT_MACRO'].map(c => ({ k: 'SUBP_COND.' + c })),
        sc.map(r => ['SUBP', 'CONDID', 'SUBPCOND_PROP', 'MICRCOND_PROP', 'MACRCOND_PROP', 'NONFR_INCL_PCT_SUBP', 'NONFR_INCL_PCT_MACRO'].map(c => codeVal('SUBP_COND', c, r[c])))) : '');
  }
  // ---------------------------------------------------------------- raw records: every extracted table row for the plot
  function rawBlocks(P, X) {
    const B = [['PLOT', P.pf], ['COND', P.cn], ['TREE', P.tr], ['TREE (extra columns)', X.trx], ['SEEDLING', P.sd], ['SITETREE', P.st], ['P2VEG_SUBP_STRUCTURE', P.p2s],
      ['P2VEG_SUBPLOT_SPP', P.p2v], ['INVASIVE_SUBPLOT_SPP', P.iv]];
    Object.entries(P.dwm || {}).forEach(e => B.push(e)); Object.entries(P.so || {}).forEach(e => B.push(e));
    B.push(['SUBPLOT', X.sbp], ['SUBP_COND', X.sbc], ['POP_PLOT_STRATUM_ASSGN', X.ppsa], ['TREE_GRM_COMPONENT', X.grm]);
    return B.filter(([, b]) => b && b.r && b.r.length);
  }
  function raw(P, X) {
    return `<h3>Raw records</h3><p class="muted">Every extracted row for this plot, all visits, as stored (codes not decoded; vi = visit index). Open a table to view, copy or download it.</p>`
      + rawBlocks(P, X).map(([t, b], i) => `<details class="rawtab" data-rb="${i}"><summary>${esc(t)} (${b.r.length} rows, ${b.c.length} columns)</summary>`
        + `<div class="actions noprint"><button type="button" data-copy="${i}">Copy (tab-separated)</button><button type="button" data-csv="${i}">CSV</button><span class="muted" data-msg="${i}"></span></div><div data-rt="${i}"></div></details>`).join('');
  }
  const rawTable = (t, b) => `<div class="scroll"><table class="wide raw"><thead><tr>${b.c.map(c => ['vi', 'ti', 'pv'].includes(c) ? th('d:raw_' + c)
    : th(t.replace(' (extra columns)', '') + '.' + c)).join('')}</tr></thead><tbody>${b.r.map(r => '<tr>' + r.map(x => `<td>${esc(x ?? '')}</td>`).join('') + '</tr>').join('')}</tbody></table></div>`;
  function wireRaw(P, X) {
    const B = rawBlocks(P, X);
    document.querySelectorAll('details.rawtab').forEach(d => d.addEventListener('toggle', () => { const i = +d.dataset.rb, host = d.querySelector(`[data-rt="${i}"]`);
      if (d.open && !host.innerHTML) host.innerHTML = rawTable(B[i][0], B[i][1]); }));
    document.querySelectorAll('[data-copy]').forEach(b => b.onclick = async () => { const [t, blk] = B[+b.dataset.copy], txt = [blk.c.join('\t')].concat(blk.r.map(r => r.map(x => x ?? '').join('\t'))).join('\n');
      const m = document.querySelector(`[data-msg="${b.dataset.copy}"]`);
      try { await navigator.clipboard.writeText(txt); m.textContent = 'copied'; } catch (e) { m.textContent = 'copy not allowed here; use CSV'; } });
    document.querySelectorAll('[data-csv]').forEach(b => b.onclick = () => { const [t, blk] = B[+b.dataset.csv]; download(`fia_${P.k}_${t.replace(/\W+/g, '_')}.csv`, toCsv(blk.c, blk.r)); });
  }
  // print appendix: all raw tables expanded
  window.expertRawAppendix = function () {
    const P = PLOT.P, X = PLOT.X, sec = document.createElement('section');
    sec.className = 'psec rawappendix'; sec.dataset.print = 'on';
    sec.innerHTML = '<h2>Appendix: raw records</h2>' + rawBlocks(P, X).map(([t, b]) => `<h3>${esc(t)}</h3>` + rawTable(t, b)).join('');
    $('#s-caveats').after(sec);
    return sec;
  };
})();

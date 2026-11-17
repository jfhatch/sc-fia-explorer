// Map page: Expert view filters, marker colouring and the estimated next measurement (data/plots_x.json, fetched only in
// Expert view), plus "Print map" (one landscape page: current extent, visible plots, legend and active filters).
'use strict';
(function () {
  const X = { data: null, loading: null, col: null, idx: null };
  const PALX = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'];
  const SEQ = ['#d6e6f7', '#a9c9ee', '#7aaae3', '#4b8ad6', '#2a6fc0', '#1c55a0', '#123d78', '#0a2650'];
  // filter definitions: [id, label, help key, value getter, decode key]
  const F = [
    ['p2', 'P2PANEL', 'PLOT.P2PANEL', x => x[X.col.p2], 'PLOT.P2PANEL'],
    ['cy', 'CYCLE', 'PLOT.CYCLE', x => x[X.col.cy], 'PLOT.CYCLE'],
    ['iy', 'Last INVYR', 'PLOT.INVYR', (x, r) => r[APP.col.l], null],
    ['kc', 'KINDCD', 'PLOT.KINDCD', x => x[X.col.kc], 'PLOT.KINDCD'],
    ['dc', 'DESIGNCD', 'PLOT.DESIGNCD', x => x[X.col.dc], 'PLOT.DESIGNCD'],
    ['st', 'PLOT_STATUS_CD', 'PLOT.PLOT_STATUS_CD', x => x[X.col.st], 'PLOT.PLOT_STATUS_CD'],
    ['ns', 'Nonsampled reason', 'PLOT.PLOT_NONSAMPLE_REASN_CD', x => x[X.col.ns], 'PLOT.PLOT_NONSAMPLE_REASN_CD'],
    ['sz', 'Stand size class', 'COND.STDSZCD', x => x[X.col.sz], 'COND.STDSZCD'],
    ['gs', 'Stocking class (GSSTKCD)', 'COND.GSSTKCD', x => x[X.col.gs], 'COND.GSSTKCD'],
    ['ds', 'Disturbance code', 'COND.DSTRBCD1', x => x[X.col.ds], 'COND.DSTRBCD1'],
    ['tr', 'Treatment code', 'COND.TRTCD1', x => x[X.col.tr], 'COND.TRTCD1'],
    ['sc', 'Site class', 'COND.SITECLCD', x => x[X.col.sc], 'COND.SITECLCD'],
  ];
  const sel = {};
  const xrow = r => X.data ? X.data.r[FIA.plots.byKey.get(r[APP.col.k])] : null;
  const lab = (dk, v) => { if (v == null) return 'not recorded'; if (!dk) return String(v); const d = decode(dk, v); return d.status === 'decoded' ? d.text : `${v} (${d.status === 'undecoded' ? 'undecoded' : 'not in guide'})`; };

  async function load() {
    if (X.data) return X.data;
    if (!X.loading) X.loading = getJSON('data/plots_x.json').then(d => { X.data = d; X.col = Object.fromEntries(d.c.map((c, i) => [c, i])); return d; });
    return X.loading;
  }
  function buildFilters() {
    const rows = APP.rows, out = [];
    for (const [id, label, hk, get, dk] of F) {
      const vals = new Map();
      rows.forEach(r => { const x = xrow(r); if (!x) return; const v = get(x, r); (Array.isArray(v) ? v : [v]).forEach(z => { if (z != null) vals.set(z, (vals.get(z) || 0) + 1); }); });
      const opts = [...vals.keys()].sort((a, b) => (typeof a === 'number' ? a - b : String(a).localeCompare(String(b))));
      out.push(`<div class="row"><label for="xf_${id}">${esc(label)}<button type="button" class="hb" data-h="${hk}" aria-label="About ${esc(label)}">ⓘ</button></label>`
        + `<select id="xf_${id}" data-xf="${id}"><option value="">Any</option>${opts.map(v => `<option value="${esc(v)}"${sel[id] === String(v) ? ' selected' : ''}>${esc((dk ? lab(dk, v) : String(v)).slice(0, 70))} (${vals.get(v).toLocaleString()})</option>`).join('')}</select></div>`);
    }
    $('#xf_rows').innerHTML = out.join('');
    $('#xf_status').textContent = 'Fields of each plot\'s latest visit (PLOT row) and its largest condition (COND). Codes decoded from the FIADB User Guide; undecoded codes are flagged.';
    document.querySelectorAll('[data-xf]').forEach(s => s.onchange = () => { sel[s.dataset.xf] = s.value; applyFilters(); });
  }
  function passes(r) {
    if (!X.data) return true;
    const x = xrow(r);
    for (const [id, , , get] of F) {
      const want = sel[id];
      if (!want) continue;
      if (!x) return false;
      const v = get(x, r);
      if (Array.isArray(v) ? !v.map(String).includes(want) : String(v) !== want) return false;
    }
    return true;
  }
  // ---------------------------------------------------------------- marker colouring
  function colorBy(mode) {
    const c = APP.col, legend = $('#xlegend');
    if (mode === 'grp' || !X.data || !isExpert()) {
      APP.rows.forEach(r => { const m = APP.markers.get(r[c.k]); if (m.options.fill !== false) m.setStyle({ fillColor: APP.groupColor[r[c.g]] || '#9a9893' }); });
      legend.innerHTML = ''; return;
    }
    const valOf = r => { const x = xrow(r); if (!x) return null;
      return mode === 'invyr' ? r[c.l] : mode === 'p2' ? x[X.col.p2] : mode === 'sz' ? x[X.col.sz] : mode === 'gs' ? x[X.col.gs] : mode === 'ds' ? (x[X.col.ds].length ? 'disturbance recorded' : 'none recorded')
        : mode === 'nx' ? (x[X.col.nx] == null ? null : Math.floor(x[X.col.nx])) : null; };
    const vals = [...new Set(APP.rows.map(valOf).filter(v => v != null))].sort((a, b) => (typeof a === 'number' ? a - b : String(a).localeCompare(String(b))));
    const seq = mode === 'invyr' || mode === 'nx';
    const colorOf = new Map(vals.map((v, i) => [v, seq ? SEQ[Math.round(i * (SEQ.length - 1) / Math.max(1, vals.length - 1))] : (i < PALX.length ? PALX[i] : '#9a9893')]));
    APP.rows.forEach(r => { const m = APP.markers.get(r[c.k]); if (m.options.fill === false) return; const v = valOf(r); m.setStyle({ fillColor: v == null ? '#c9c8c2' : colorOf.get(v) }); });
    const dk = { sz: 'COND.STDSZCD', gs: 'COND.GSSTKCD', p2: 'PLOT.P2PANEL' }[mode];
    legend.innerHTML = `<p class="muted">${mode === 'nx' ? 'Estimated next measurement year: last national-design measurement + the median of this plot\'s own past intervals. <b>Estimated from past intervals, not an FIA schedule.</b>' : 'Active plots coloured by the selected field.'}</p>`
      + vals.slice(0, 16).map(v => `<div class="legend-item"><span class="sw" style="background:${colorOf.get(v)}"></span>${esc(dk ? lab(dk, v) : String(v))}</div>`).join('')
      + (vals.length > 16 ? `<p class="muted">… ${vals.length - 16} more values (grey)</p>` : '') + `<div class="legend-item"><span class="sw" style="background:#c9c8c2"></span>not recorded</div>`;
  }
  function popupLine(key) {
    if (!X.data) return '';
    const x = X.data.r[FIA.plots.byKey.get(key)];
    if (!x) return '';
    const nx = x[X.col.nx];
    return `<div class="muted" style="margin:3px 0">P2PANEL ${x[X.col.p2] ?? '—'} · CYCLE ${x[X.col.cy] ?? '—'}.${x[X.col.scy] != null ? x[X.col.scy] : ''} · STDSZCD ${x[X.col.sz] ?? '—'} · GSSTKCD ${x[X.col.gs] ?? '—'}<br>`
      + `Expected next measurement: ${nx != null ? `~${nx.toFixed(1)} (estimated from ${x[X.col.ni]} past interval${x[X.col.ni] > 1 ? 's' : ''}, not an FIA schedule)` : 'no estimate (fewer than two national-design visits)'}</div>`;
  }
  async function activate() {
    if (!isExpert()) { colorBy('grp'); applyFilters(); return; }
    try { await load(); } catch (e) { $('#xf_status').textContent = 'Could not load expert fields: ' + e.message; return; }
    buildFilters(); colorBy($('#x_color').value); applyFilters();
    document.body.dataset.mapx = '1';
  }
  window.MAPX = { passes, popupLine, load, colorBy };
  $('#x_color').onchange = e => colorBy(e.target.value);
  window.addEventListener('viewchange', activate);
  const wait = setInterval(() => { if (document.body.dataset.ready === '1') { clearInterval(wait); activate(); } }, 100);

  // ---------------------------------------------------------------- print map (one landscape page)
  $('#printmap').onclick = () => {
    const c = APP.col, b = map.getBounds();
    const filt = [...document.querySelectorAll('#side select, #side input')].filter(e => e.id !== 'basemap' && e.id !== 'x_color' && ((e.type === 'checkbox' && e.id === 'f_hist' && e.checked) || (e.type !== 'checkbox' && e.value && !(e.id === 'f_nv' && e.value === '1'))))
      .map(e => { const l = document.querySelector(`label[for="${e.id}"]`); const name = l ? l.textContent.replace('ⓘ', '').trim() : (e.getAttribute('aria-label') || e.id);
        return `${esc(name.split('\n')[0])}: ${esc(e.tagName === 'SELECT' ? e.selectedOptions[0].textContent : e.type === 'checkbox' ? 'on' : e.value)}`; });
    const hidden = [...document.querySelectorAll('#legend input[data-grp]')].filter(i => !i.checked).map(i => i.parentElement.textContent.trim());
    if (hidden.length) filt.push('Forest type groups hidden: ' + hidden.map(esc).join('; '));
    const legend = ($('#xlegend').innerHTML && isExpert() && $('#x_color').value !== 'grp') ? $('#xlegend').innerHTML
      : [...document.querySelectorAll('#legend .legend-item')].filter(e => !e.classList.contains('hidden')).map(e => e.outerHTML.replace(/<input[^>]*>/, '')).join('');
    const ver = (FIA.meta.build.fiadb_version || {}).version || '';
    $('#printinfo').innerHTML = `<h1 style="font-size:14pt;margin:0">SC FIA plot explorer — map</h1><p style="margin:2px 0">${esc($('#count').textContent)} · extent ${b.getSouth().toFixed(2)}–${b.getNorth().toFixed(2)}° N, `
      + `${(-b.getEast()).toFixed(2)}–${(-b.getWest()).toFixed(2)}° W · ${isExpert() ? 'Expert' : 'Standard'} view</p><p style="margin:2px 0"><b>Active filters:</b> ${filt.length ? filt.join(' · ') : 'none'}</p>`
      + `<div class="printlegend">${legend}</div><p style="margin:2px 0;font-size:7.5pt">Generated ${new Date().toISOString().slice(0, 10)} from FIADB ${esc(ver)}; public data; coordinates fuzzed. ${esc(location.href.split('#')[0])}</p>`;
    const st = document.createElement('style');
    st.textContent = '@page { size: letter landscape; margin: 0.4in; }';
    document.head.append(st);
    document.body.classList.add('printmap');
    map.invalidateSize(false); map.fitBounds(b, { animate: false });
    const done = () => { document.body.classList.remove('printmap'); st.remove(); map.invalidateSize(false); map.fitBounds(b, { animate: false }); window.removeEventListener('afterprint', done); };
    window.addEventListener('afterprint', done);
    window.MAPX.printRestore = done;
    setTimeout(() => window.print(), 1200);           // let the resized map draw its tiles first
  };
})();

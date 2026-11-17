// SC FIA plot explorer: map page.
// Privacy: location search runs here, in the browser, over the public coordinates already loaded; the entered point is
// never sent to the server, written to storage, or put in the URL. "Clear and forget" wipes it from the page.
'use strict';
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (v, d = 1) => v == null || isNaN(v) ? '—' : Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

async function api(path, opts = {}) {
  const o = Object.assign({}, opts);
  if (o.method && o.method !== 'GET') o.headers = Object.assign({ 'X-FIASC': '1', 'Content-Type': 'application/json' }, o.headers || {});
  const r = await fetch(path, o);
  if (!r.ok) {
    let msg = r.status + ' ' + r.statusText;
    try { const j = await r.json(); msg = j.detail || msg; } catch (e) { /* not json */ }
    throw new Error(msg);
  }
  return r.json();
}

const S = { meta: null, rows: [], col: {}, markers: new Map(), newKeys: new Set(), attrKeys: null, locLayer: null };
window.APP = S;     // read by the headless test

// ---------------------------------------------------------------- map
const map = L.map('map', { preferCanvas: true, zoomControl: true }).setView([0, 0], 2);   // fitted to the bundled county boundaries once they load
const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 18, attribution: '&copy; OpenStreetMap contributors', referrerPolicy: 'no-referrer'
});
let tileErrors = 0, usingPlain = false;
function setBasemap(kind) {
  usingPlain = kind === 'plain';
  if (usingPlain) { map.removeLayer(osm); map.getContainer().classList.add('plain-bg'); }
  else { osm.addTo(map); map.getContainer().classList.remove('plain-bg'); }
  $('#basemap').value = kind;
}
osm.on('tileerror', () => { if (++tileErrors > 6 && !usingPlain) setBasemap('plain'); });
setBasemap(navigator.onLine ? 'osm' : 'plain');
$('#basemap').onchange = e => setBasemap(e.target.value);
const cluster = L.markerClusterGroup({ chunkedLoading: true, maxClusterRadius: 45, disableClusteringAtZoom: 12, showCoverageOnHover: false });
map.addLayer(cluster);
const newLayer = L.layerGroup().addTo(map);      // plots with new data, drawn unclustered when highlighted
const canvas = L.canvas({ padding: 0.3 });

fetch('/static/sc_counties.geojson').then(r => r.json()).then(gj => {
  const lyr = L.geoJSON(gj, { style: { color: '#6b6a66', weight: 1, fill: false, opacity: 0.8 }, interactive: false }).addTo(map);
  map.fitBounds(lyr.getBounds(), { padding: [10, 10] });
}).catch(() => {});

// ---------------------------------------------------------------- data + filters
async function init() {
  const [meta, loc] = await Promise.all([api('/api/meta'), api('/api/locations')]);
  S.meta = meta;
  loc.cols.forEach((c, i) => S.col[c] = i);
  S.rows = loc.rows;
  S.groupColor = Object.fromEntries(meta.groups.map(g => [g.code, g.color]));
  $('#buildinfo').textContent = `Build ${meta.build.build_name || ''} · FIADB ${meta.build.fiadb_version?.version || '?'} · latest INVYR ${meta.build.latest_invyr}`;
  $('#coordnote').textContent = meta.coord_note;
  for (const c of meta.counties) $('#f_cty').append(new Option(`${c.name} (${c.code})`, c.code));
  for (const t of meta.types) $('#f_ft').append(new Option(`${t.code} ${t.name} (${t.n})`, t.code));
  for (const o of meta.owners) $('#f_own').append(new Option(`${o.name} (${o.n})`, o.code));
  $('#f_last0').value = meta.last_invyr[0]; $('#f_last1').value = meta.last_invyr[1];
  $('#legend').innerHTML = meta.groups.map(g => `<label class="legend-item"><input type="checkbox" data-grp="${g.code}" checked>
      <span class="sw" style="background:${g.color}"></span>${esc(g.name)}<span class="n">${g.n.toLocaleString()}</span></label>`).join('');
  document.querySelectorAll('#side select, #side input').forEach(el => el.addEventListener('change', applyFilters));
  $('#f_reset').onclick = () => {
    ['#f_cty', '#f_ft', '#f_own', '#f_des', '#f_inv', '#f_new'].forEach(s => $(s).value = '');
    $('#f_nv').value = 1; $('#f_last0').value = meta.last_invyr[0]; $('#f_last1').value = meta.last_invyr[1];
    document.querySelectorAll('#legend input').forEach(i => i.checked = true);
    S.attrKeys = null; applyFilters();
  };
  for (const r of S.rows) {
    const m = L.circleMarker([r[S.col.lat], r[S.col.lon]], { renderer: canvas, radius: 5, weight: 1, color: '#222', fillOpacity: 0.9,
      fillColor: S.groupColor[r[S.col.grp]] || '#9a9893' });
    m.key = r[S.col.key];
    m.on('click', () => openPopup(m));
    S.markers.set(m.key, m);
  }
  try { const wn = await api('/api/update/whatsnew'); S.newKeys = new Set(wn.keys || []); } catch (e) { /* none */ }
  applyFilters();
  document.body.dataset.ready = '1';
  const st = await api('/api/settings');
  if (st.check_on_startup) startupCheck();
}

function visible(r) {
  const c = S.col, v = id => $(id).value;
  if (v('#f_cty') && r[c.cty] != +v('#f_cty')) return false;
  if (v('#f_ft') && r[c.ft] != +v('#f_ft')) return false;
  if (v('#f_own') && r[c.own] != +v('#f_own')) return false;
  if (v('#f_last0') && r[c.last] < +v('#f_last0')) return false;
  if (v('#f_last1') && r[c.last] > +v('#f_last1')) return false;
  if (r[c.nv] < +(v('#f_nv') || 1)) return false;
  if (v('#f_des') && r[c.des] !== v('#f_des')) return false;
  if (v('#f_inv') !== '' && r[c.inv] != +v('#f_inv')) return false;
  if (v('#f_new') === 'only' && !S.newKeys.has(r[c.key])) return false;
  const g = document.querySelector(`#legend input[data-grp="${r[c.grp]}"]`);
  if (g && !g.checked) return false;
  if (S.attrKeys && !S.attrKeys.has(r[c.key])) return false;
  return true;
}

function applyFilters() {
  const hl = $('#f_new').value === 'hl';
  const layers = [], hiLayers = [];
  for (const r of S.rows) {
    if (!visible(r)) continue;
    const m = S.markers.get(r[S.col.key]);
    const isNew = S.newKeys.has(r[S.col.key]);
    m.setStyle(hl && isNew ? { radius: 8, weight: 3, color: '#e34948' } : { radius: 5, weight: 1, color: '#222' });
    (hl && isNew ? hiLayers : layers).push(m);
  }
  cluster.clearLayers();
  newLayer.clearLayers();
  cluster.addLayers(layers);
  hiLayers.forEach(m => newLayer.addLayer(m));
  $('#count').textContent = (layers.length + hiLayers.length).toLocaleString() + (hl ? ` (${hiLayers.length} with new data, outlined red)` : '');
  document.body.dataset.visible = layers.length + hiLayers.length;
}

async function openPopup(m) {
  m.bindPopup('Loading…', { maxWidth: 460 }).openPopup();
  try {
    const p = await api('/api/popup/' + encodeURIComponent(m.key));
    const r = S.rows.find(x => x[S.col.key] === m.key);
    const rows = p.visits.map(v => `<tr><td>${esc(v.date)}</td><td>${esc(v.design)}</td><td class="n">${fmt(v.ba)}</td><td class="n">${fmt(v.tpa, 0)}</td>
        <td class="n">${fmt(v.carbon)}</td><td class="n">${v.mort ?? '—'}</td><td class="n">${v.ing ?? '—'}</td><td class="n">${v.inv}</td></tr>`).join('');
    m.setPopupContent(`<b>Plot ${esc(m.key)}</b>${S.newKeys.has(m.key) ? ' <span class="tag">new data</span>' : ''}<br>
      <span class="muted">public location ${r[S.col.lat].toFixed(4)}, ${r[S.col.lon].toFixed(4)} (fuzzed)</span>
      <table><thead><tr><th>Survey</th><th>Design</th><th class="n">BA ft²/ac</th><th class="n">TPA</th><th class="n">C t/ac</th><th class="n">Died</th><th class="n">Ingr.</th><th class="n">Inv.</th></tr></thead>
      <tbody>${rows}</tbody></table>
      <p style="margin:6px 0 0"><a href="/plot/${encodeURIComponent(m.key)}" target="_blank" rel="noopener">Open plot page →</a></p>`);
  } catch (e) { m.setPopupContent('Could not load: ' + esc(e.message)); }
}

function focusKey(key, open = true) {
  const m = S.markers.get(key);
  if (!m) return;
  if (newLayer.hasLayer(m)) { map.setView(m.getLatLng(), Math.max(map.getZoom(), 12)); if (open) openPopup(m); return; }
  cluster.zoomToShowLayer(m, () => { if (open) openPopup(m); });
}

// ---------------------------------------------------------------- drawer
function drawer(tplId) {
  const d = $('#drawer');
  d.innerHTML = '';
  d.append($(tplId).content.cloneNode(true));
  d.classList.remove('hidden');
  $('.close', d).onclick = () => { if (tplId === '#tpl-loc') clearLocation(); d.classList.add('hidden'); };
  return d;
}

// ---------------------------------------------------------------- search by plot ID (server)
async function idSearch() {
  const q = $('#idq').value.trim();
  if (!q) return;
  const d = drawer('#tpl-attr');
  d.innerHTML = `<h3>Plot ID search <button class="close" type="button" aria-label="Close">×</button></h3><div id="id_out">Searching…</div>`;
  $('.close', d).onclick = () => d.classList.add('hidden');
  try {
    const r = await api('/api/search/id?q=' + encodeURIComponent(q));
    if (!r.results.length) { $('#id_out').innerHTML = `<p>No plot matches <b>${esc(q)}</b>. Use county-plot (91-25), the full key (45-3-91-25), county name and plot (York 25), or a PLOT CN.</p>`; return; }
    $('#id_out').innerHTML = '<ul class="results">' + r.results.map(x => `<li data-key="${esc(x.KEY)}"><a href="#" data-focus="${esc(x.KEY)}">Plot ${esc(x.KEY)}</a>
        · ${x.N_VISITS} visits · last ${esc(x.LAST_DATE)} · ${esc(x.DESIGNS)} · <a href="/plot/${encodeURIComponent(x.KEY)}" target="_blank" rel="noopener">plot page</a></li>`).join('') + '</ul>';
    d.querySelectorAll('[data-focus]').forEach(a => a.onclick = e => { e.preventDefault(); focusKey(a.dataset.focus); });
    if (r.results.length === 1) focusKey(r.results[0].KEY);
  } catch (e) { $('#id_out').textContent = 'Search failed: ' + e.message; }
}
$('#idgo').onclick = idSearch;
$('#idq').addEventListener('keydown', e => { if (e.key === 'Enter') idSearch(); });

// ---------------------------------------------------------------- search by location (client-side only)
function parseCoord(txt, isLat) {
  if (txt == null) return NaN;
  let s = String(txt).trim().toUpperCase().replace(/,/g, ' ');
  if (!s) return NaN;
  let sign = 1;
  const hemi = s.match(/[NSEW]/);
  if (hemi) { if ('SW'.includes(hemi[0])) sign = -1; s = s.replace(/[NSEW]/g, ' '); }
  if (/^\s*-/.test(s)) { sign = -sign; s = s.replace('-', ' '); }
  const parts = s.replace(/[°º˚'’′"”″:]/g, ' ').trim().split(/\s+/).filter(Boolean).map(Number);
  if (!parts.length || parts.some(isNaN) || parts.length > 3) return NaN;
  const [d, m = 0, sec = 0] = parts;
  if (m < 0 || m >= 60 || sec < 0 || sec >= 60) return NaN;
  const v = sign * (Math.abs(d) + m / 60 + sec / 3600);
  if (isLat ? Math.abs(v) > 90 : Math.abs(v) > 180) return NaN;
  return v;
}
window.parseCoord = parseCoord;
function haversineMi(a, b, c, d) {
  const R = 3958.8, r = Math.PI / 180;
  const x = Math.sin((c - a) * r / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin((d - b) * r / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}
function nearest(lat, lon, radius, limit = 50) {
  const c = S.col, out = [];
  for (const r of S.rows) {
    const dmi = haversineMi(lat, lon, r[c.lat], r[c.lon]);
    if (dmi <= radius) out.push({ key: r[c.key], d: dmi, r });
  }
  out.sort((a, b) => a.d - b.d);
  return out.slice(0, limit);
}
window.nearestPlots = nearest;
function clearLocation() {
  if (S.locLayer) { map.removeLayer(S.locLayer); S.locLayer = null; }
  ['#l_lat', '#l_lon'].forEach(s => { const el = $(s); if (el) el.value = ''; });
  const o = $('#l_out'); if (o) o.innerHTML = '';
}
$('#locbtn').onclick = () => {
  const d = drawer('#tpl-loc');
  $('#l_note').textContent = S.meta.coord_note;
  $('#l_clear').onclick = clearLocation;
  const run = () => {
    const lat = parseCoord($('#l_lat').value, true), lon = parseCoord($('#l_lon').value, false), rad = +$('#l_rad').value || 2;
    if (isNaN(lat) || isNaN(lon)) { $('#l_out').innerHTML = '<p class="bad">Could not read the coordinates. Use decimal degrees (dd.dddd and -dd.dddd) or degrees-minutes-seconds (dd° mm\' ss" N and dd° mm\' ss" W).</p>'; return; }
    const res = nearest(lat, lon, rad);
    if (S.locLayer) map.removeLayer(S.locLayer);
    S.locLayer = L.layerGroup([L.circle([lat, lon], { radius: rad * 1609.344, color: '#2a78d6', weight: 1, fillOpacity: 0.05, interactive: false }),
                               L.circleMarker([lat, lon], { radius: 6, color: '#2a78d6', fillColor: '#fff', fillOpacity: 1, weight: 2, interactive: false })]).addTo(map);
    $('#l_out').innerHTML = res.length ? `<p>${res.length} public plot location${res.length > 1 ? 's' : ''} within ${rad} mi, nearest first. The map does not move
      automatically; use “Zoom to results”.</p><button type="button" id="l_zoom">Zoom to results</button><ol class="results" id="l_list">` + res.map(x =>
      `<li data-key="${esc(x.key)}" data-dist="${x.d.toFixed(3)}"><a href="#" data-focus="${esc(x.key)}">Plot ${esc(x.key)}</a> · ${x.d.toFixed(2)} mi ·
        ${x.r[S.col.nv]} visits, last ${esc(x.r[S.col.date])} · <a href="/plot/${encodeURIComponent(x.key)}" target="_blank" rel="noopener">plot page</a></li>`).join('') + '</ol>'
      : `<p>No public plot location within ${rad} mi. Try a larger radius.</p>`;
    $('#l_out').querySelectorAll('[data-focus]').forEach(a => a.onclick = e => { e.preventDefault(); focusKey(a.dataset.focus); });
    const z = $('#l_zoom'); if (z) z.onclick = () => map.fitBounds(L.latLngBounds(res.map(x => [x.r[S.col.lat], x.r[S.col.lon]]).concat([[lat, lon]])).pad(0.2));
  };
  $('#l_go').onclick = run;
  ['#l_lat', '#l_lon', '#l_rad'].forEach(s => $(s).addEventListener('keydown', e => { if (e.key === 'Enter') run(); }));
};
window.addEventListener('pagehide', clearLocation);

// ---------------------------------------------------------------- search by attributes (server)
$('#attrbtn').onclick = () => {
  const d = drawer('#tpl-attr');
  for (const c of S.meta.counties) $('#a_cty').append(new Option(c.name, c.code));
  for (const g of S.meta.groups) if (g.code > 0) $('#a_grp').append(new Option(g.name, g.code));
  for (const t of S.meta.types) $('#a_ft').append(new Option(`${t.code} ${t.name}`, t.code));
  for (const o of S.meta.owners) $('#a_own').append(new Option(o.name, o.code));
  let keys = [];
  $('#a_go').onclick = async () => {
    const p = new URLSearchParams();
    const add = (k, s) => { const v = $(s).value; if (v !== '') p.set(k, v); };
    add('county', '#a_cty'); add('grp', '#a_grp'); add('fortyp', '#a_ft'); add('own', '#a_own'); add('age_min', '#a_age0'); add('age_max', '#a_age1');
    add('last_min', '#a_last0'); add('last_max', '#a_last1'); add('design', '#a_des'); add('inv', '#a_inv');
    $('#a_out').textContent = 'Searching…';
    try {
      const r = await api('/api/search/attr?' + p.toString());
      keys = r.results.map(x => x.KEY);
      $('#a_map').disabled = !keys.length;
      $('#a_out').innerHTML = `<p>${r.n} plot location${r.n === 1 ? '' : 's'}${r.n >= 2000 ? ' (first 2,000)' : ''}.</p><div class="tables-wrap"><table><thead><tr><th>Plot</th><th>County</th>
        <th>Forest type</th><th class="n">Age</th><th>Last visit</th><th class="n">BA</th></tr></thead><tbody>` + r.results.map(x =>
        `<tr><td><a href="#" data-focus="${esc(x.KEY)}">${esc(x.KEY)}</a></td><td>${esc(x.county)}</td><td>${esc(x.fortyp)}</td><td class="n">${fmt(x.STDAGE, 0)}</td>
         <td>${esc(x.LAST_DATE)}</td><td class="n">${fmt(x.BA)}</td></tr>`).join('') + '</tbody></table></div>';
      $('#a_out').querySelectorAll('[data-focus]').forEach(a => a.onclick = e => { e.preventDefault(); focusKey(a.dataset.focus); });
    } catch (e) { $('#a_out').textContent = 'Search failed: ' + e.message; }
  };
  $('#a_map').onclick = () => { S.attrKeys = new Set(keys); applyFilters(); };
};

// ---------------------------------------------------------------- data panel and updates
let jobTimer = null, logFrom = 0;
async function startupCheck() {
  try {
    const r = await api('/api/update/check', { method: 'POST' });
    $('#updbadge').classList.toggle('hidden', !r.any_changed);
  } catch (e) { /* offline: no badge */ }
}
function tableRows(tables, check) {
  const ch = new Map((check?.tables || []).map(t => [t.table, t]));
  return `<table><thead><tr><th>Table</th><th class="n">Rows</th><th>DataMart Last-Modified</th><th>Latest MODIFIED_DATE</th><th>Check</th></tr></thead><tbody>` +
    tables.map(t => { const c = ch.get(t.table_name);
      return `<tr class="${c && c.fields.length ? 'changed' : ''}"><td>${esc(t.table_name)}</td><td class="n">${(t.rows ?? 0).toLocaleString()}</td>
        <td>${esc(t.last_modified)}</td><td>${esc(t.max_modified_date || '—')}</td><td>${c ? esc(c.status + (c.fields.length ? ' (' + c.fields.join(', ') + ')' : '')) : '—'}</td></tr>`; }).join('') + '</tbody></table>';
}
function renderCheck(r) {
  if (!r) { $('#d_checkout').innerHTML = '<p class="muted">Not checked yet.</p>'; return; }
  const fv = r.fiadb_version || {};
  const rec = fv.recorded?.version, now = fv.now?.version;
  $('#d_checkout').innerHTML = `<p>Checked ${esc(r.checked_at)}: ${r.any_changed ? `<b>${r.changed.length} table(s) changed</b>: ${esc(r.changed.join(', '))}` :
    '<span class="ok">no changes since the live build</span>'}. FIADB version: ${esc(rec || '?')}${now && now !== rec ? ` → <b>${esc(now)}</b>` : ''}.</p>`;
  $('#d_import').disabled = !r.any_changed;
  $('#updbadge').classList.toggle('hidden', !r.any_changed);
}
async function openData() {
  const d = drawer('#tpl-data');
  const s = await api('/api/data/status');
  const fv = s.fiadb_version || {};
  $('#d_status').innerHTML = `<div class="kv">
    <div>Live build</div><div>${esc(s.build)} (${fmt(s.db_mb, 0)} MB)</div>
    <div>Built</div><div>${esc(s.built_at)}</div>
    <div>FIADB version</div><div>${esc(fv.version || '?')} — ${esc(fv.descr || '')} (${esc(fv.created || '')})</div>
    <div>Plot locations</div><div>${(s.locations ?? 0).toLocaleString()}</div>
    <div>Visits</div><div>${(s.visits ?? 0).toLocaleString()}</div>
    <div>Latest INVYR</div><div>${esc(s.latest_invyr)}</div>
    <div>Validation</div><div>${s.validation?.errors?.length ? '<span class="bad">errors</span>' : '<span class="ok">passed</span>'}; tests ${s.tests ? (s.tests.passed ? '<span class="ok">passed</span>' : '<span class="bad">failed</span>') : '—'}</div>
    <div>Previous builds</div><div>${s.previous_builds.length ? esc(s.previous_builds.join(', ')) : 'none'}</div>
    ${s.missing_tables?.length ? `<div>Not on DataMart</div><div>${esc(s.missing_tables.join(', '))}</div>` : ''}</div>`;
  $('#d_tables').innerHTML = tableRows(s.tables, s.last_check);
  renderCheck(s.last_check);
  $('#d_rollback').disabled = !s.previous_builds.length || !!s.active_job;
  $('#d_startup').checked = !!s.settings.check_on_startup;
  $('#d_startup').onchange = e => api('/api/settings', { method: 'POST', body: JSON.stringify({ check_on_startup: e.target.checked }) });
  $('#d_check').onclick = async () => {
    $('#d_check').disabled = true; $('#d_checkout').innerHTML = '<p class="muted">Sending HEAD requests to the DataMart…</p>';
    try { const r = await api('/api/update/check', { method: 'POST' }); renderCheck(r); $('#d_tables').innerHTML = tableRows(s.tables, r); }
    catch (e) { $('#d_checkout').innerHTML = `<p class="bad">${esc(e.message)}</p>`; }
    $('#d_check').disabled = false;
  };
  $('#d_import').onclick = async () => {
    try { await api('/api/update/import', { method: 'POST', body: '{}' }); logFrom = 0; $('#d_log').textContent = ''; pollJob(); }
    catch (e) { alertBox(e.message); }
  };
  $('#d_rollback').onclick = async () => {
    $('#d_rollback').disabled = true;
    try { const p = await api('/api/update/rollback', { method: 'POST', body: '{}' }); $('#d_whatsnew').innerHTML = `<p class="ok">Restored ${esc(p.current)}. Reloading…</p>`; setTimeout(() => location.reload(), 900); }
    catch (e) { alertBox(e.message); $('#d_rollback').disabled = false; }
  };
  $('#d_cancel').onclick = () => api('/api/update/cancel', { method: 'POST', body: '{}' }).then(pollJob).catch(e => alertBox(e.message));
  $('#d_confirm').onclick = () => api('/api/update/confirm', { method: 'POST', body: '{}' }).then(pollJob).catch(e => alertBox(e.message));
  $('#d_logtoggle').onclick = () => { $('#d_log').classList.toggle('hidden'); $('#d_logtoggle').textContent = $('#d_log').classList.contains('hidden') ? 'Show log' : 'Hide log'; };
  if (s.active_job) pollJob();
  else if (s.whats_new_summary) renderWhatsNew(await api('/api/update/whatsnew'), false);
}
function alertBox(msg) { const w = $('#d_whatsnew'); if (w) w.innerHTML = `<p class="bad">${esc(msg)}</p>`; }
async function pollJob() {
  clearTimeout(jobTimer);
  let j;
  try { j = await api('/api/update/job?log_from=' + logFrom); } catch (e) { return; }
  const box = $('#d_job'); if (!box) return;
  box.classList.remove('hidden');
  $('#d_jobstate').textContent = `${j.id} · ${j.state}`;
  $('#d_bar').style.width = (j.pct || 0) + '%';
  $('#d_msg').textContent = `${j.stage || ''} ${j.message ? '— ' + j.message : ''}`;
  if (j.log?.length) { $('#d_log').textContent += j.log.join('\n') + '\n'; logFrom = j.log_total; $('#d_log').scrollTop = 1e9; }
  const running = ['queued', 'running'].includes(j.state);
  $('#d_cancel').disabled = !(running || j.state === 'needs_confirmation');
  $('#d_confirm').classList.toggle('hidden', j.state !== 'needs_confirmation');
  $('#d_import').disabled = true; $('#d_rollback').disabled = running;
  if (j.state === 'needs_confirmation') $('#d_msg').innerHTML = '<b>Row counts dropped:</b> ' + esc((j.confirm || []).join('; ')) + ' — confirm to switch or cancel to keep the current build.';
  if (running || j.state === 'needs_confirmation') { jobTimer = setTimeout(pollJob, 1500); return; }
  if (j.state === 'done') { renderWhatsNew(await api('/api/update/whatsnew'), true); }
  else if (j.state === 'failed') $('#d_whatsnew').innerHTML = `<p class="bad">Update failed; the current build stays live. Reason: ${esc(j.message)}</p>`;
  else if (j.state === 'cancelled') $('#d_whatsnew').innerHTML = `<p>Cancelled; the current build stays live.</p>`;
}
function keyLinks(keys, max = 40) {
  return keys.slice(0, max).map(k => `<a href="/plot/${encodeURIComponent(k)}" target="_blank" rel="noopener">${esc(k)}</a>`).join(', ') + (keys.length > max ? ` … (+${keys.length - max})` : '');
}
function renderWhatsNew(w, fresh) {
  const s = w.summary;
  if (!s || s.note) { $('#d_whatsnew').innerHTML = s?.note ? `<p class="muted">${esc(s.note)}</p>` : ''; return; }
  S.newKeys = new Set(w.keys || []);
  const nv = (w.new_visits || []).map(x => `<li>${esc(x.county)} County, INVYR ${x.invyr}: ${x.n} visit${x.n > 1 ? 's' : ''} — ${keyLinks(x.keys, 12)}</li>`).join('');
  $('#d_whatsnew').innerHTML = `<h3 style="font-size:14px;margin-top:12px">What's new ${fresh ? '' : `in the live build`} (compared with ${esc(w.compared_to)})</h3>
    <div class="kv"><div>New visits</div><div>${s.new_visits}</div><div>Newly installed plots</div><div>${s.installed}</div><div>Remeasured plots</div><div>${s.remeasured}</div>
    <div>Plots with changed records</div><div>${s.changed_plots}</div><div>Visits removed</div><div>${s.removed_visits}</div>
    <div>Species new to the data</div><div>${s.new_species}</div><div>Invasives new to the data</div><div>${s.new_invasives_state}</div>
    <div>New invasive detections</div><div>${s.new_invasive_detections} plot(s)</div></div>
    ${nv ? `<b>New visits by county and INVYR</b><ul class="results">${nv}</ul>` : ''}
    ${w.installed?.length ? `<b>Newly installed:</b> ${keyLinks(w.installed)}<br>` : ''}
    ${w.remeasured?.length ? `<b>Remeasured:</b> ${keyLinks(w.remeasured)}<br>` : ''}
    ${w.changed?.length ? `<b>Changed records:</b> ${w.changed.slice(0, 30).map(c => `<a href="/plot/${encodeURIComponent(c.key)}" target="_blank" rel="noopener">${esc(c.key)}</a> (${esc(c.tables.join(', '))})`).join(', ')}${w.changed.length > 30 ? ' …' : ''}<br>` : ''}
    ${w.new_species?.length ? `<b>New species:</b> ${w.new_species.map(x => `${esc(x.name)} (SPCD ${x.spcd}): ${keyLinks(x.keys, 8)}`).join('; ')}<br>` : ''}
    ${w.new_invasives_state?.length ? `<b>New invasive species:</b> ${w.new_invasives_state.map(x => `${esc(x.name)} (${esc(x.symbol)}): ${keyLinks(x.keys, 8)}`).join('; ')}<br>` : ''}
    ${w.new_invasives_plot?.length ? `<b>Invasives newly detected on a plot:</b> ${w.new_invasives_plot.slice(0, 30).map(x => `<a href="/plot/${encodeURIComponent(x.key)}" target="_blank" rel="noopener">${esc(x.key)}</a> (${esc(x.symbols.join(', '))})`).join(', ')}<br>` : ''}
    <p><button type="button" id="d_hl">Highlight these ${S.newKeys.size} plots on the map</button>${fresh ? ' <button type="button" id="d_reload">Reload map with the new build</button>' : ''}</p>`;
  $('#d_hl').onclick = () => { $('#f_new').value = 'hl'; applyFilters(); };
  const rl = $('#d_reload'); if (rl) rl.onclick = () => location.reload();
}
$('#databtn').onclick = () => openData().catch(e => alertBox(e.message));

init().catch(e => { document.body.dataset.ready = 'error'; $('#count').textContent = 'error: ' + e.message; });

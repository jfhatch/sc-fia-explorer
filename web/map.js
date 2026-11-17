// SC FIA plot explorer (static site): map page. Adapted from app/static/app.js; every former API call is a static
// fetch, and filtering, plot-ID / attribute search and the location search run in the browser.
// Privacy: the location entered is never sent anywhere, stored, or put in the URL; "Clear and forget" wipes it.
'use strict';
const S = { meta: null, rows: [], col: {}, markers: new Map(), attrKeys: null, locLayer: null };
window.APP = S;     // read by the headless test

// ---------------------------------------------------------------- map and USGS National Map basemaps
const map = L.map('map', { preferCanvas: true, zoomControl: true }).setView([0, 0], 2);   // fitted to the county boundaries on load
const TNM = s => `https://basemap.nationalmap.gov/arcgis/rest/services/${s}/MapServer/tile/{z}/{y}/{x}`;
const ATTR = 'Basemap: <a href="https://www.usgs.gov/programs/national-geospatial-program/national-map" rel="noopener noreferrer">USGS The National Map</a>';
const tileOpts = { maxZoom: 16, maxNativeZoom: 16, attribution: ATTR, referrerPolicy: 'no-referrer', crossOrigin: false };
const BASE = {
  topo: [L.tileLayer(TNM('USGSTopo'), tileOpts)],
  imgtopo: [L.tileLayer(TNM('USGSImageryOnly'), tileOpts), L.tileLayer(TNM('USGSTopo'), Object.assign({}, tileOpts, { opacity: 0.45 }))],
  img: [L.tileLayer(TNM('USGSImageryOnly'), tileOpts)],
  plain: []
};
let current = null, tileErrors = 0, tileOk = 0;
window.TILES = { ok: () => tileOk, err: () => tileErrors };
function setBasemap(kind, why) {
  for (const k in BASE) BASE[k].forEach(l => map.hasLayer(l) && map.removeLayer(l));
  BASE[kind].forEach(l => l.addTo(map));
  map.getContainer().classList.toggle('plain-bg', kind === 'plain');
  current = kind; tileErrors = 0;
  $('#basemap').value = kind;
  $('#basenote').textContent = why || (kind === 'plain' ? 'No tiles are requested with the plain basemap.' :
    'Tiles from basemap.nationalmap.gov; the map area you view is sent to that server.');
}
for (const k in BASE) BASE[k].forEach(l => {
  l.on('tileerror', () => { if (++tileErrors >= 6 && current !== 'plain') setBasemap('plain', 'Switched to the plain basemap after repeated tile errors (offline or the USGS server is unavailable).'); });
  l.on('tileload', () => { tileOk++; });
});
setBasemap(navigator.onLine === false ? 'plain' : 'topo');
$('#basemap').onchange = e => setBasemap(e.target.value);
const cluster = L.markerClusterGroup({ chunkedLoading: true, maxClusterRadius: 45, disableClusteringAtZoom: 12, showCoverageOnHover: false });
map.addLayer(cluster);
const canvas = L.canvas({ padding: 0.3 });
getJSON('data/counties.geojson').then(gj => {
  const lyr = L.geoJSON(gj, { style: { color: '#6b6a66', weight: 1, fill: false, opacity: 0.8 }, interactive: false }).addTo(map);
  map.fitBounds(lyr.getBounds(), { padding: [10, 10] });
}).catch(() => {});

// mobile: collapsible filter panel
function toggleSide(open) {
  document.body.classList.toggle('side-open', open);
  $('#filtbtn').setAttribute('aria-expanded', String(open));
  setTimeout(() => map.invalidateSize(), 220);
}
$('#filtbtn').onclick = () => toggleSide(!document.body.classList.contains('side-open'));
$('#sideclose').onclick = () => toggleSide(false);

// ---------------------------------------------------------------- data + filters
async function init() {
  const [meta, P] = await Promise.all([loadMeta(), loadPlots(), loadCodes()]);
  S.meta = meta; S.col = P.col; S.rows = P.rows;
  S.groupColor = Object.fromEntries(meta.groups.map(g => [g.code, g.color]));
  footer();
  $('#coordnote').textContent = meta.coord_note;
  for (const c of meta.counties) $('#f_cty').append(new Option(`${c.name} (${c.code})`, c.code));
  for (const t of meta.types) $('#f_ft').append(new Option(`${t.code} ${t.name} (${t.n})`, t.code));
  for (const o of meta.owners) $('#f_own').append(new Option(`${o.name} (${o.n})`, o.code));
  $('#f_last0').value = meta.last_invyr[0]; $('#f_last1').value = meta.last_invyr[1];
  $('#legend').innerHTML = meta.groups.map(g => `<label class="legend-item"><input type="checkbox" data-grp="${g.code}" checked>
      <span class="sw" style="background:${g.color}"></span>${esc(g.name)}<span class="n">${g.n.toLocaleString()}</span></label>`).join('');
  document.querySelectorAll('#side select:not(#basemap), #side input').forEach(el => el.addEventListener('change', applyFilters));
  $('#f_reset').onclick = () => {
    ['#f_cty', '#f_ft', '#f_own', '#f_des', '#f_inv'].forEach(s => $(s).value = '');
    $('#f_nv').value = 1; $('#f_last0').value = meta.last_invyr[0]; $('#f_last1').value = meta.last_invyr[1];
    document.querySelectorAll('#legend input').forEach(i => i.checked = true);
    S.attrKeys = null; applyFilters();
  };
  const c = S.col;
  for (const r of S.rows) {
    const m = L.circleMarker([r[c.la], r[c.lo]], { renderer: canvas, radius: 6, weight: 1, color: '#222', fillOpacity: 0.9, fillColor: S.groupColor[r[c.g]] || '#9a9893' });
    m.key = r[c.k];
    m.on('click', () => openPopup(m));
    S.markers.set(m.key, m);
  }
  applyFilters();
  document.body.dataset.ready = '1';
}
function visible(r) {
  const c = S.col, v = id => $(id).value;
  if (v('#f_cty') && r[c.y] != +v('#f_cty')) return false;
  if (v('#f_ft') && r[c.f] != +v('#f_ft')) return false;
  if (v('#f_own') && r[c.o] != +v('#f_own')) return false;
  if (v('#f_last0') && r[c.l] < +v('#f_last0')) return false;
  if (v('#f_last1') && r[c.l] > +v('#f_last1')) return false;
  if (r[c.n] < +(v('#f_nv') || 1)) return false;
  if (v('#f_des') && r[c.d] !== v('#f_des')) return false;
  if (v('#f_inv') !== '' && r[c.i] != +v('#f_inv')) return false;
  const g = document.querySelector(`#legend input[data-grp="${r[c.g]}"]`);
  if (g && !g.checked) return false;
  if (S.attrKeys && !S.attrKeys.has(r[c.k])) return false;
  return true;
}
function applyFilters() {
  const layers = [];
  for (const r of S.rows) if (visible(r)) layers.push(S.markers.get(r[S.col.k]));
  cluster.clearLayers();
  cluster.addLayers(layers);
  $('#count').textContent = layers.length.toLocaleString();
  document.body.dataset.visible = layers.length;
}
async function openPopup(m) {
  m.bindPopup('Loading…', { maxWidth: 460 }).openPopup();
  try {
    const P = await getJSON(`p/${encodeURIComponent(m.key)}.json`);
    if (!m.isPopupOpen()) return;                 // closed (or another plot opened) while loading
    const M = S.meta.metrics, ix = k => M.indexOf(k);
    const ev = rowsOf(P.ev);
    const rows = P.v.map((v, i) => {
      const e = ev.filter(x => x.Y1 === v.y);
      const died = i ? e.filter(x => x.t === 0).length : '—', ing = i ? e.filter(x => x.t === 3).length : '—';
      return `<tr><td>${esc(v.d)}</td><td>${esc(v.ds)}</td><td class="n">${fmt(v.m[ix('ba')])}</td><td class="n">${fmt(v.m[ix('live_tpa')], 0)}</td>
        <td class="n">${fmt(v.m[ix('carbon')])}</td><td class="n">${died}</td><td class="n">${ing}</td><td class="n">${v.ni ?? 0}</td></tr>`;
    }).join('');
    m.setPopupContent(`<b>Plot ${esc(m.key)}</b><br><span class="muted">public location ${P.la.toFixed(4)}, ${P.lo.toFixed(4)} (fuzzed)</span>
      <div class="popscroll"><table><thead><tr><th>Survey</th><th>Design</th><th class="n">BA ft²/ac</th><th class="n">TPA</th><th class="n">C t/ac</th><th class="n">Died</th><th class="n">Ingr.</th><th class="n">Inv.</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
      <p style="margin:6px 0 0"><a href="${plotUrl(m.key)}">Open plot page →</a></p>`);
  } catch (e) { if (m.isPopupOpen()) m.setPopupContent('Could not load: ' + esc(e.message)); }
}
function focusKey(key, open = true) {
  const m = S.markers.get(key);
  if (!m) return;
  if (window.innerWidth < 760) toggleSide(false);
  cluster.zoomToShowLayer(m, () => { if (open) openPopup(m); });
}
function drawer(tplId) {
  const d = $('#drawer');
  d.innerHTML = '';
  d.append($(tplId).content.cloneNode(true));
  d.classList.remove('hidden');
  $('.close', d).onclick = () => { if (tplId === '#tpl-loc') clearLocation(); d.classList.add('hidden'); };
  return d;
}

// ---------------------------------------------------------------- plot-ID search (client-side: plots.json + ids.json)
let IDS = null;
async function resolveId(q) {
  const t = q.trim(), c = S.col, out = [];
  let m = t.match(/^\s*(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(\d{1,3})\s*-\s*(\d{1,6})\s*$/);
  if (m) { const k = m.slice(1).map(Number).join('-'); return FIA.plots.byKey.has(k) ? [k] : []; }
  m = t.match(/^\s*(\d{1,3})\s*[-/ ]\s*(\d{1,6})\s*$/);
  if (m) return S.rows.filter(r => r[c.y] === +m[1] && r[c.p] === +m[2]).map(r => r[c.k]);
  m = t.match(/^\s*(?:cn\s*)?(\d{6,20})\s*$/i);
  if (m) { IDS = IDS || await getJSON('data/ids.json'); const i = IDS[m[1]]; return i === undefined ? [] : [S.rows[i][c.k]]; }
  m = t.match(/^\s*([A-Za-z][A-Za-z .']+?)\s*[-/ ]?\s*(\d{1,6})\s*$/);
  if (m) {
    const cty = S.meta.counties.find(x => x.name.toLowerCase() === m[1].trim().toLowerCase().replace(/ county$/, ''));
    if (cty) return S.rows.filter(r => r[c.y] === cty.code && r[c.p] === +m[2]).map(r => r[c.k]);
  }
  return out;
}
async function idSearch() {
  const q = $('#idq').value.trim();
  if (!q) return;
  const d = drawer('#tpl-attr');
  d.innerHTML = `<h3>Plot ID search <button class="close" type="button" aria-label="Close">×</button></h3><div id="id_out">Searching…</div>`;
  $('.close', d).onclick = () => d.classList.add('hidden');
  const keys = await resolveId(q);
  if (!keys.length) { $('#id_out').innerHTML = `<p>No plot matches <b>${esc(q)}</b>. Use county-plot (91-25), the full key (45-3-91-25), county name and plot (York 25), or a PLOT CN.</p>`; return; }
  const c = S.col;
  $('#id_out').innerHTML = '<ul class="results">' + keys.map(k => { const r = S.rows[FIA.plots.byKey.get(k)];
    return `<li data-key="${esc(k)}"><a href="#" data-focus="${esc(k)}">Plot ${esc(k)}</a> · ${r[c.n]} visits · last ${esc(r[c.t])} ·
      <a href="${plotUrl(k)}">plot page</a></li>`; }).join('') + '</ul>';
  d.querySelectorAll('[data-focus]').forEach(a => a.onclick = e => { e.preventDefault(); focusKey(a.dataset.focus); });
  if (keys.length === 1) focusKey(keys[0]);
}
$('#idgo').onclick = idSearch;
$('#idq').addEventListener('keydown', e => { if (e.key === 'Enter') idSearch(); });

// ---------------------------------------------------------------- location search (client-side only)
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
  for (const r of S.rows) { const dmi = haversineMi(lat, lon, r[c.la], r[c.lo]); if (dmi <= radius) out.push({ key: r[c.k], d: dmi, r }); }
  out.sort((a, b) => a.d - b.d);
  return out.slice(0, limit);
}
function clearLocation() {
  if (S.locLayer) { map.removeLayer(S.locLayer); S.locLayer = null; }
  ['#l_lat', '#l_lon'].forEach(s => { const el = $(s); if (el) el.value = ''; });
  const o = $('#l_out'); if (o) o.innerHTML = '';
}
$('#locbtn').onclick = () => {
  drawer('#tpl-loc');
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
        ${x.r[S.col.n]} visits, last ${esc(x.r[S.col.t])} · <a href="${plotUrl(x.key)}">plot page</a></li>`).join('') + '</ol>'
      : `<p>No public plot location within ${rad} mi. Try a larger radius.</p>`;
    $('#l_out').querySelectorAll('[data-focus]').forEach(a => a.onclick = e => { e.preventDefault(); focusKey(a.dataset.focus); });
    const z = $('#l_zoom'); if (z) z.onclick = () => map.fitBounds(L.latLngBounds(res.map(x => [x.r[S.col.la], x.r[S.col.lo]]).concat([[lat, lon]])).pad(0.2));
  };
  $('#l_go').onclick = run;
  ['#l_lat', '#l_lon', '#l_rad'].forEach(s => $(s).addEventListener('keydown', e => { if (e.key === 'Enter') run(); }));
};
window.addEventListener('pagehide', clearLocation);

// ---------------------------------------------------------------- attribute search (client-side over plots.json)
$('#attrbtn').onclick = () => {
  drawer('#tpl-attr');
  for (const c of S.meta.counties) $('#a_cty').append(new Option(c.name, c.code));
  for (const g of S.meta.groups) if (g.code > 0) $('#a_grp').append(new Option(g.name, g.code));
  for (const t of S.meta.types) $('#a_ft').append(new Option(`${t.code} ${t.name}`, t.code));
  for (const o of S.meta.owners) $('#a_own').append(new Option(o.name, o.code));
  let keys = [];
  $('#a_go').onclick = () => {
    const c = S.col, v = s => $(s).value, n = s => v(s) === '' ? null : +v(s);
    const res = S.rows.filter(r =>
      (n('#a_cty') === null || r[c.y] === n('#a_cty')) && (n('#a_grp') === null || r[c.g] === n('#a_grp')) &&
      (n('#a_ft') === null || r[c.f] === n('#a_ft')) && (n('#a_own') === null || r[c.o] === n('#a_own')) &&
      (n('#a_age0') === null || (r[c.a] != null && r[c.a] >= n('#a_age0'))) && (n('#a_age1') === null || (r[c.a] != null && r[c.a] <= n('#a_age1'))) &&
      (n('#a_last0') === null || r[c.l] >= n('#a_last0')) && (n('#a_last1') === null || r[c.l] <= n('#a_last1')) &&
      (!v('#a_des') || r[c.d].includes(v('#a_des')[0])) && (n('#a_inv') === null || r[c.i] === n('#a_inv')))
      .sort((a, b) => a[c.y] - b[c.y] || a[c.p] - b[c.p]);
    keys = res.map(r => r[c.k]);
    $('#a_map').disabled = !keys.length;
    const cn = Object.fromEntries(S.meta.counties.map(x => [x.code, x.name]));
    $('#a_out').innerHTML = `<p>${res.length.toLocaleString()} plot location${res.length === 1 ? '' : 's'}${res.length > 2000 ? ' (first 2,000 listed)' : ''}.</p><div class="tables-wrap"><table><thead><tr><th>Plot</th><th>County</th>
      <th>Forest type</th><th class="n">Age</th><th>Last visit</th><th class="n">BA</th></tr></thead><tbody>` + res.slice(0, 2000).map(r =>
      `<tr><td><a href="#" data-focus="${esc(r[c.k])}">${esc(r[c.k])}</a></td><td>${esc(cn[r[c.y]])}</td><td>${esc(ftName(r[c.f]))}</td><td class="n">${fmt(r[c.a], 0)}</td>
       <td>${esc(r[c.t])}</td><td class="n">${fmt(r[c.b])}</td></tr>`).join('') + '</tbody></table></div>';
    $('#a_out').querySelectorAll('[data-focus]').forEach(a => a.onclick = e => { e.preventDefault(); focusKey(a.dataset.focus); });
  };
  $('#a_map').onclick = () => { S.attrKeys = new Set(keys); applyFilters(); };
};

init().catch(e => { document.body.dataset.ready = 'error'; $('#count').textContent = 'error: ' + e.message; });

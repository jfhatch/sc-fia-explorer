// Shared helpers for the static site: data loading, FIADB decoding (port of fiasc.core.decode), formatting, footer.
'use strict';
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (v, d = 1) => v == null || v === '' || isNaN(v) ? '—' : Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const FIA = { meta: null, codes: null, plots: null };
const BA_K = 0.005454154;

async function getJSON(url) {
  const r = await fetch(url, { cache: 'default' });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}
async function loadMeta() { return FIA.meta || (FIA.meta = await getJSON('data/meta.json')); }
async function loadCodes() { return FIA.codes || (FIA.codes = await getJSON('data/codes.json')); }
async function loadPlots() {
  if (FIA.plots) return FIA.plots;
  const p = await getJSON('data/plots.json');
  const col = {}; p.c.forEach((c, i) => col[c] = i);
  return (FIA.plots = { col, rows: p.r, byKey: new Map(p.r.map((r, i) => [r[col.k], i])) });
}
const plotUrl = key => `plot.html?k=${encodeURIComponent(key)}`;

// ---------------------------------------------------------------- decoding
// Texts were rendered by fiasc.core.decode at export time; values not in the guide are flagged, never guessed.
const REF_CODED = { SPCD: 'sp', FORTYPCD: 'ft', FLDTYPCD: 'ft', FORTYPCDCALC: 'ft', VEG_SPCD: 'pl' };
function blank(v) { return v === null || v === undefined || v === '' || (typeof v === 'number' && isNaN(v)); }
function decode(key, v) {
  const C = FIA.codes;
  if (blank(v)) return { code: null, text: '', status: 'blank' };
  const t = C.t[key] || C.t[C.al[key]];
  if (!t) {
    const why = C.nt[key] || 'no code list transcribed from the User Guide';
    return { code: v, text: `${v} (no code table: ${why})`, status: 'no_table' };
  }
  let s = t[String(v)];
  if (s === undefined) {
    const sv = String(v).replace(/^0+/, '');
    for (const k in t) if (k.trim() && k.replace(/^0+/, '') === sv) { s = t[k]; break; }
  }
  if (s === undefined) {
    const rn = (C.rn[key] || {})[String(v)];
    return { code: v, text: rn ? `${v} (${rn})` : `${v} (not in guide)`, status: 'undecoded' };
  }
  return { code: v, text: s, status: 'decoded' };
}
function decodeRef(col, v) {
  const C = FIA.codes, kind = REF_CODED[col];
  if (blank(v)) return { code: null, text: '', status: 'blank' };
  if (kind === 'sp') { const n = C.sp[v]; return n ? { code: v, text: `${v} = ${n[0]}`, status: 'decoded' } : { code: v, text: `${v} (not in REF_SPECIES)`, status: 'undecoded' }; }
  if (kind === 'ft') { const n = C.ft[v]; return n ? { code: v, text: `${v} = ${n}`, status: 'decoded' } : { code: v, text: `${v} (not in REF_FOREST_TYPE)`, status: 'undecoded' }; }
  const p = C.pl[v]; return p && p[1] ? { code: v, text: `${v} = ${p[0]}` + (p[1] !== p[0] ? ` (${p[1]})` : ''), status: 'decoded' } : { code: v, text: `${v} (not in REF_PLANT_DICTIONARY)`, status: 'undecoded' };
}
function isCoded(table, col) {
  const k = `${table}.${col}`, C = FIA.codes;
  return k in C.t || k in C.al || k in C.nt;
}
function decodeCell(table, col, v) {
  if (isCoded(table, col)) return decode(`${table}.${col}`, v);
  if (col in REF_CODED && !blank(v)) return decodeRef(col, v);
  return v;
}
const spName = c => blank(c) ? '' : (FIA.codes.sp[c] ? FIA.codes.sp[c][0] : `SPCD ${c} (not in REF_SPECIES)`);
const ftName = c => blank(c) ? '' : `${c} = ${FIA.codes.ft[c] ?? '(not in REF_FOREST_TYPE)'}`;
const plant = s => FIA.codes.pl[s] || [s, ''];
function dv(x) {
  if (x && typeof x === 'object' && 'status' in x) {
    if (x.status === 'blank') return '';
    if (x.status !== 'decoded') return `<span class="flag" title="${x.status === 'no_table' ? 'no code list in the FIADB User Guide v9.4' : 'value not in the FIADB User Guide v9.4 code list'}">⚠ ${esc(x.text)}</span>`;
    return esc(x.text);
  }
  if (typeof x === 'number') return Number.isInteger(x) ? String(x) : fmt(x, 3);
  return esc(x);
}
function dvs(x, n = 48) {   // compact: first clause, full text on hover
  if (!x || typeof x !== 'object' || x.status !== 'decoded') return dv(x);
  let t = x.text.split(' - ')[0].split('. ')[0];
  if (t.length > n) t = t.slice(0, n - 1).replace(/\s+\S*$/, '') + '…';
  return `<span title="${esc(x.text)}">${esc(t)}</span>`;
}
// {c: cols, r: rows} -> array of objects
const rowsOf = b => b ? b.r.map(r => Object.fromEntries(b.c.map((c, i) => [c, r[i]]))) : [];

// ---------------------------------------------------------------- footer
async function footer() {
  const m = await loadMeta();
  const b = m.build, fv = b.fiadb_version || {};
  const el = document.getElementById('footer');
  if (el) el.innerHTML = `Data current as of FIADB ${esc((fv.version || '?').replace('FIADB_', ''))} (${esc((fv.created || '').slice(0, 10))}) · latest INVYR ${esc(b.latest_invyr)} ·
    built ${esc((b.built_at || '').slice(0, 10))} · public FIADB data only · <a href="about.html">About &amp; caveats</a>`;
}

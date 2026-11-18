'use strict';
// ---------------------------------------------------------------- plot page, section 8: full-size per-species diameter view
// Opened from a small-multiple panel (click, tap, Enter/Space) or a shared link (#species=<SPCD>). The URL hash holds the
// species so the back button closes the view; prev/next (buttons, ←/→, swipe) replace the hash instead of adding history.
// Same encoding as the small panels, plus a dot at every measurement placed at its actual date, with its DBH printed
// beside it (labels that cannot be placed without overlap are dropped and stay in the tooltip; see SPV.last).
(() => {
  const SPV = window.SPV = { cur: null, pushed: false, same: false, pin: null, after: null, last: null, printW: null };
  const LIVE = '#2a78d6', ENDC = '#8a8984', DEAD = '#b3261e', CUT = '#52514e';
  const STW = { 1: 'live', 2: 'dead', 3: 'cut', 0: 'left the sample' };
  const isOpen = () => SPV.cur != null;
  const el = id => document.getElementById(id);
  const spOf = t => t.pts[t.pts.length - 1].spcd;
  const fate = t => FATE(t);
  function species() {
    const sm = PL.sm;
    if (!sm) return [];
    return sm.order.map(name => { const trees = sm.T.filter(t => t.sp === name); return { name, code: trees.length ? spOf(trees[0]) : null, trees }; })
      .filter(s => s.trees.length);
  }
  const hashCode = () => { const m = hashParts().map(x => /^species=(\d+)$/.exec(x)).find(Boolean); return m ? +m[1] : null; };
  function hashUrl(code) {
    const u = new URL(location.href), parts = hashParts().filter(x => !/^species=/.test(x));
    if (code != null) parts.push('species=' + code);
    u.hash = parts.join('&');
    return u.hash ? u.href : u.pathname + u.search;
  }

  // ------------------------------------------------------------ DOM (built once)
  function build() {
    if (el('spview')) return;
    document.body.insertAdjacentHTML('beforeend', `<div id="spview" class="spview" hidden>
  <div class="spback" data-close="1"></div>
  <div class="spbox" role="dialog" aria-modal="true" aria-labelledby="sp_title">
    <div class="sphead">
      <button type="button" class="spnav" id="sp_prev" aria-label="Previous species" title="Previous species (←)">‹</button>
      <div class="sptitle"><h2 id="sp_title"></h2><div class="muted" id="sp_sub"></div></div>
      <button type="button" class="spnav" id="sp_next" aria-label="Next species" title="Next species (→)">›</button>
      <button type="button" class="spclose" id="sp_close" aria-label="Close" title="Close (Esc)">×</button>
    </div>
    <div class="spctl"><label><input type="checkbox" id="sp_same"> Same axes as overview</label>
      <button type="button" class="linkbtn" id="sp_print">Print this view</button>
      <span class="muted sphint">Hover or tap a dot for details; hover a line or a tree in the list to pick it out.</span></div>
    <div class="spmain"><div class="spchart" id="sp_chart"></div><div class="splist" id="sp_list"></div></div>
    <div id="sp_leg"></div>
  </div>
  <div class="sptip" id="sp_tip" role="status" hidden></div>
</div>`);
    const root = el('spview');
    root.addEventListener('click', e => { if (e.target.dataset.close) close(); });
    el('sp_close').onclick = () => close();
    el('sp_prev').onclick = () => step(-1);
    el('sp_next').onclick = () => step(1);
    el('sp_same').onchange = e => { SPV.same = e.target.checked; draw(); };
    el('sp_print').onclick = () => window.print();
    const ch = el('sp_chart');
    // hover follows the pointer's own movements, not enter/leave events (Chrome can re-fire those at a stale position once the
    // tooltip appears, which closed it at once): over a dot -> its tooltip; over a line -> that tree; elsewhere the tooltip
    // closes once the pointer is more than 14 px from its dot. Touch uses taps (click below).
    ch.addEventListener('pointermove', e => {
      if (e.pointerType === 'touch') return;
      const h = e.target.closest('.dhit, .lhit');
      if (h) { hl(+h.dataset.ti); if (h.classList.contains('dhit')) { if (SPV.tipEl !== h) tip(h); } else if (!SPV.pinTip) tip(null); return; }
      const t = SPV.tipEl;
      if (t && t.isConnected) { const r = t.getBoundingClientRect(); if (Math.hypot(e.clientX - r.left - r.width / 2, e.clientY - r.top - r.height / 2) <= 14) return; }
      hl(SPV.pin); if (!SPV.pinTip) tip(null);
    });
    ch.addEventListener('pointerleave', e => { if (e.pointerType === 'touch') return; hl(SPV.pin); if (!SPV.pinTip) tip(null); });
    // a tap is judged by what was under the finger when it went down (the click can land on the chart after the press)
    ch.addEventListener('pointerdown', e => { SPV.down = e.target.closest('.dhit, .lhit'); });
    ch.addEventListener('click', e => {
      const h = e.target.closest('.dhit, .lhit') || (SPV.down && SPV.down.isConnected ? SPV.down : null);
      SPV.down = null;
      if (!h) { SPV.pin = null; SPV.pinTip = false; hl(null); tip(null); return; }
      SPV.pin = +h.dataset.ti; hl(SPV.pin);
      if (h.classList.contains('dhit')) { SPV.pinTip = true; tip(h); } else { SPV.pinTip = false; tip(null); }
    });
    // the tooltip is fixed to the viewport: hide it when the dialog scrolls under it
    root.querySelector('.spbox').addEventListener('scroll', () => { SPV.pinTip = false; tip(null); }, { passive: true });
    const list = el('sp_list');
    list.addEventListener('pointerover', e => { const r = e.target.closest('tr[data-ti]'); if (r) hl(+r.dataset.ti); });
    list.addEventListener('pointerout', e => { const r = e.target.closest('tr[data-ti]'); if (r && !(e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest('tr[data-ti]'))) hl(SPV.pin); });
    list.addEventListener('focusin', e => { const r = e.target.closest('tr[data-ti]'); if (r) hl(+r.dataset.ti); });
    list.addEventListener('click', e => { const r = e.target.closest('tr[data-ti]'); if (r && !e.target.closest('.sortb, .hb')) openTree(+r.dataset.ti); });
    list.addEventListener('keydown', e => { const r = e.target.closest('tr[data-ti]'); if (r && e.key === 'Enter') openTree(+r.dataset.ti); });
    // swipe between species on touch screens
    let t0 = null;
    root.querySelector('.spmain').addEventListener('touchstart', e => { const t = e.touches[0]; t0 = e.touches.length === 1 ? [t.clientX, t.clientY] : null; }, { passive: true });
    root.querySelector('.spmain').addEventListener('touchend', e => {
      if (!t0) return; const t = e.changedTouches[0], dx = t.clientX - t0[0], dy = t.clientY - t0[1]; t0 = null;
      if (Math.abs(dx) > 60 && Math.abs(dx) > 2 * Math.abs(dy)) step(dx < 0 ? 1 : -1);
    }, { passive: true });
  }

  // ------------------------------------------------------------ open / close / navigate
  function open(code, how = {}) {
    const S = species(), sp = S.find(s => s.code === code);
    if (!sp) return false;
    build();
    if (!isOpen()) {
      SPV.ret = document.activeElement;
      if (how.push) { history.pushState({ spv: 1 }, '', hashUrl(code)); SPV.pushed = true; }
      else if (how.deep) {        // a shared link: put a closed state behind it so back closes the view, not the page
        history.replaceState(null, '', hashUrl(null)); history.pushState({ spv: 1 }, '', hashUrl(code)); SPV.pushed = true;
      }
      document.body.classList.add('spopen');
      el('spview').hidden = false;
    } else if (!how.pop) history.replaceState(history.state, '', hashUrl(code));
    SPV.cur = code; SPV.pin = null; SPV.pinTip = false;
    tip(null);
    draw();
    if (!how.keepFocus) el('sp_close').focus({ preventScroll: true });
    return true;
  }
  function close(how = {}) {
    if (!isOpen()) return;
    if (!how.pop && SPV.pushed) { history.back(); return; }      // popstate closes it
    if (!how.pop) history.replaceState(history.state, '', hashUrl(null));
    SPV.cur = null; SPV.pushed = false;
    el('spview').hidden = true;
    document.body.classList.remove('spopen');
    tip(null);
    const after = SPV.after; SPV.after = null;
    if (after) after();
    else if (SPV.ret && SPV.ret.isConnected) SPV.ret.focus({ preventScroll: true });
    else { const f = document.querySelector(`.sm figure.smz[data-sp="${SPV.lastCode}"]`); if (f) f.focus({ preventScroll: true }); }
  }
  function step(d) {
    const S = species(), i = S.findIndex(s => s.code === SPV.cur);
    if (i < 0 || S.length < 2) return;
    open(S[(i + d + S.length) % S.length].code, { keepFocus: true });
  }
  function openTree(ti) {
    SPV.after = () => {
      const tr = document.querySelector(`#trees_t tr.trow[data-ti="${ti}"]`);
      if (!tr) return;
      if (tr.getAttribute('aria-expanded') !== 'true') toggleTree(tr);
      tr.scrollIntoView({ block: 'start' }); tr.focus({ preventScroll: true });
    };
    close();
  }
  // follow the URL: back / forward / an edited hash
  function sync() {
    const code = hashCode();
    if (code != null && PL.sm) { if (!isOpen()) open(code, { deep: !SPV.seen, pop: SPV.seen }); else if (code !== SPV.cur) open(code, { pop: true, keepFocus: true }); }
    else if (code == null && isOpen()) close({ pop: true });
    SPV.seen = true;
  }
  SPV.sync = () => { if (!SPV.seen) sync(); };
  addEventListener('popstate', () => { SPV.seen = true; const c = hashCode(); if (c != null && !isOpen()) { open(c, { pop: true }); SPV.pushed = true; } else sync(); });
  addEventListener('hashchange', () => { SPV.seen = true; sync(); });
  SPV.open = open; SPV.close = close; SPV.step = step;

  // keyboard: Esc closes, ←/→ step, Tab stays inside the dialog; panels open with Enter/Space
  document.addEventListener('keydown', e => {
    if (!isOpen()) {
      const f = e.target.closest && e.target.closest('.sm figure.smz');
      if (f && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); open(+f.dataset.sp, { push: true }); }
      return;
    }
    if (e.key === 'Escape') { const hp = el('hpop'); if (hp && hp.offsetParent !== null && getComputedStyle(hp).visibility !== 'hidden') return;   // Esc first closes an open ⓘ
      e.preventDefault(); close(); return; }
    const typing = /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName) && e.target.type !== 'checkbox';
    if (!typing && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) { e.preventDefault(); step(e.key === 'ArrowRight' ? 1 : -1); return; }
    if (e.key === 'Tab') {
      const f = [...el('spview').querySelectorAll('button, input, [tabindex="0"]')].filter(x => x.offsetParent !== null);
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    }
  });
  document.addEventListener('click', e => {
    const f = e.target.closest('.sm figure.smz');
    if (f && !isOpen()) open(+f.dataset.sp, { push: true });
  });
  let rt = null;
  // redraw only when the chart width changes: phones fire resize when the address bar hides or shows while scrolling, and a
  // redraw then would drop the tooltip and highlight under the finger
  addEventListener('resize', () => { if (isOpen()) { clearTimeout(rt); rt = setTimeout(() => { const w = Math.floor(el('sp_chart').clientWidth || 0); if (!SPV.printW && w && SPV.last && w !== SPV.last.W) draw(); }, 120); } });
  // print: draw at a fixed page width with every label, then back to the screen size
  addEventListener('beforeprint', () => { if (isOpen()) { SPV.printW = 960; draw(); } });
  addEventListener('afterprint', () => { if (isOpen() && SPV.printW) { SPV.printW = null; draw(); } });

  // ------------------------------------------------------------ highlight + tooltip
  function hl(ti) {
    const root = el('spview');
    if (!root) return;
    el('sp_chart').classList.toggle('hl', ti != null);
    root.querySelectorAll('.sptree, .splab, .splead, #sp_list tr[data-ti]').forEach(n => n.classList.toggle('on', ti != null && +n.dataset.ti === ti));
  }
  function tip(h) {
    const T = el('sp_tip');
    if (!T) return;
    SPV.tipEl = h || null;
    if (!h) { T.hidden = true; return; }
    const t = PL.sm.T.find(x => x.ti === +h.dataset.ti), p = t && t.pts.find(q => q.vi === +h.dataset.vi);
    if (!p) { T.hidden = true; return; }
    // fixed to the viewport (not inside the scrolling dialog): measuring it there could add a scrollbar, narrow the chart and
    // slide the dot out from under the pointer, which closed the tooltip again (seen in Chrome)
    T.innerHTML = tipHtml(t, p);
    T.style.left = '0px'; T.style.top = '0px';
    T.hidden = false;
    const r = h.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const w = T.offsetWidth, hgt = T.offsetHeight;
    let x = cx + 14, y = cy - hgt - 10;
    if (x + w > innerWidth - 6) x = cx - w - 14;
    if (x < 6) x = 6;
    if (y < 6) y = cy + 14;
    if (y + hgt > innerHeight - 6) y = Math.max(6, innerHeight - hgt - 6);
    T.style.left = x + 'px'; T.style.top = y + 'px';
  }
  function tipHtml(t, p) {
    const V = PL.P.v, pp = t.pts.filter(q => q.dia != null), k = pp.indexOf(p), prev = k > 0 ? pp[k - 1] : null;
    let ch = 'first measurement of this tree';
    if (prev) {
      const d = p.dia - prev.dia, yrs = V[p.vi].dy - V[prev.vi].dy;
      ch = `${(d < 0 ? '−' : '+') + fmt(Math.abs(d), 1)} in since ${esc(V[prev.vi].d)}` + (yrs > 0 ? ` (${(d < 0 ? '−' : '+') + fmt(Math.abs(d / yrs), 2)} in/yr over ${fmt(yrs, 1)} yr)` : '');
    }
    return `<b>Tree ${esc(t.id)}</b> <span class="muted">(subplot-tree)</span><br>${esc(V[p.vi].d)} <span class="muted">· INVYR ${V[p.vi].y}</span><br>`
      + `DBH <b>${fmt(p.dia, 1)} in</b> · height ${p.ht != null ? fmt(p.ht, 0) + ' ft' : '—'}<br>Status: ${STW[p.st] || 'code ' + p.st}<br>${ch}`;
  }

  // ------------------------------------------------------------ the chart
  const niceStep = s => [0.5, 1, 2, 5, 10, 20, 50].find(k => s / k <= 7) || 100;
  function draw() {
    if (!isOpen()) return;
    const S = species(), i = S.findIndex(s => s.code === SPV.cur), sp = S[i];
    if (!sp) return;
    SPV.lastCode = sp.code;
    const R = (PL.treeRows || []).filter(r => sp.trees.some(t => t.ti === r.ti));
    const nLive = sp.trees.filter(t => fate(t) === 'live').length;
    el('sp_title').textContent = sp.name;
    el('sp_sub').textContent = `${sp.trees.length} tree${sp.trees.length === 1 ? '' : 's'} (${nLive} live at the last survey) · SPCD ${sp.code} · species ${i + 1} of ${S.length}`;
    el('sp_prev').disabled = el('sp_next').disabled = S.length < 2;
    el('sp_same').checked = SPV.same;
    el('sp_leg').innerHTML = PL.sm.legend.replace('<div class="smleg">', '<div class="smleg"><span><svg width="10" height="10"><circle cx="5" cy="5" r="2.6" fill="#2a78d6"/></svg> measurement (DBH printed beside it)</span>');
    const wrap = el('sp_chart'), W = SPV.printW || Math.max(280, Math.floor(wrap.clientWidth || 600));
    const out = chart(sp, W);
    wrap.innerHTML = out.svg;
    SPV.last = { code: sp.code, W, placed: out.placed.map(l => ({ ti: l.ti, vi: l.vi, txt: l.txt })), dropped: out.dropped.map(l => ({ ti: l.ti, vi: l.vi, txt: l.txt })) };
    // the species' trees: subplot-tree, latest DBH, total increase; hover picks out the line, click opens the history
    el('sp_list').innerHTML = `<h3>Trees</h3>` + tbl([{ k: 'd:tree_id' }, { k: 'd:last_dbh', n: 1 }, { k: 'd:dbh_total', n: 1 }],
      R.map(r => ({ attrs: ` data-ti="${r.ti}" tabindex="0" title="Open the full history of tree ${esc(r.id)}"`,
        cells: [{ h: esc(r.id), v: r.id }, { h: r.last ? fmt(r.last.dia, 1) : '', v: r.last ? r.last.dia : null },
          { h: r.total == null ? '' : r.total < 0 ? `<span class="negchg">${fmt(r.total, 1)}</span>` : fmt(r.total, 1), v: r.total }] })),
      { sort: true, id: 'sp_tbl', noMax: true }) + `<p class="muted noprint">Click a tree to open its full history.</p>`;
    hl(SPV.pin);
  }
  function chart(sp, W) {
    const V = PL.P.v, narrow = W < 520;
    const H = Math.round(Math.max(narrow ? 320 : 360, Math.min(560, W * (narrow ? 0.95 : 0.55))));
    const L = 42, R = narrow ? 34 : 44, T = 24, B = 34;
    const dys = V.map(v => v.dy), x0 = Math.min(...dys), x1 = Math.max(...dys), pad = Math.max(0.5, (x1 - x0) * 0.035);
    const X = d => L + (W - L - R) * (d - (x0 - pad)) / ((x1 + pad) - (x0 - pad));
    const dias = sp.trees.flatMap(t => t.pts.filter(p => p.dia != null).map(p => p.dia));
    let lo, hi, st;
    if (SPV.same) { lo = 0; hi = PL.sm.ymax; st = hi > 20 ? 10 : 5; }
    else {
      const mn = Math.min(...dias), mx = Math.max(...dias), span = Math.max(2, mx - mn);
      st = niceStep(span * 1.2);
      lo = Math.max(0, Math.floor((mn - span * 0.08) / st) * st); hi = Math.ceil((mx + span * 0.1) / st) * st;
      if (hi <= lo) hi = lo + st;
    }
    const Y = d => T + (H - T - B) * (1 - (d - lo) / (hi - lo));
    let g = '';
    for (let d = lo; d <= hi + 1e-9; d += st) g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(d)}" y2="${Y(d)}"/><text class="tick" x="${L - 5}" y="${Y(d) + 3.5}" text-anchor="end">${+d.toFixed(1)}</text>`;
    g += `<text class="tick" x="${L - 5}" y="${T - 10}" text-anchor="end">DBH, in</text>`;
    let lastX = -1e9;
    V.forEach(v => {
      const xx = X(v.dy);
      g += `<line class="grid sv" x1="${xx}" x2="${xx}" y1="${T}" y2="${H - B}"/>`;
      if (xx - lastX >= 30) { g += `<text class="tick" x="${xx}" y="${H - B + 15}" text-anchor="middle">${v.y}</text>`; lastX = xx; }
    });
    g += `<text class="tick" x="${(L + W - R) / 2}" y="${H - 4}" text-anchor="middle">survey (placed at the measurement date)</text>`;
    g += `<line class="ax" x1="${L}" y1="${T}" x2="${L}" y2="${H - B}"/><line class="ax" x1="${L}" y1="${H - B}" x2="${W - R}" y2="${H - B}"/>`;
    if (lo < 5 && hi > 5) g += `<line x1="${L}" x2="${W - R}" y1="${Y(5)}" y2="${Y(5)}" stroke="var(--muted)" stroke-dasharray="2 3"/><text class="tick ref" x="${L + 4}" y="${Y(5) - 4}">5.0 in</text>`;
    // trees: segments, measurement dots, end markers; label candidates
    const labs = [];
    let trees = '', hits = '', lhits = '';
    for (const t of sp.trees) {
      const pp = t.pts.filter(p => p.dia != null), f = fate(t);
      if (!pp.length) continue;
      const P = p => [X(V[p.vi].dy), Y(p.dia)];
      let s = '';
      for (let k = 1; k < pp.length; k++) {
        const a = pp[k - 1], b = pp[k], [ax, ay] = P(a), [bx, by] = P(b);
        s += `<line x1="${ax}" y1="${ay}" x2="${bx}" y2="${by}" stroke="${b.st !== 1 ? ENDC : LIVE}" stroke-width="2"${a.dia < 5 ? ' stroke-dasharray="4 3"' : ''}/>`;
      }
      pp.forEach((p, k) => {
        const [px, py] = P(p);
        if (k < pp.length - 1) s += `<circle cx="${px}" cy="${py}" r="2.6" fill="${p.st === 1 ? LIVE : ENDC}"/>`;
        labs.push({ ti: t.ti, vi: p.vi, x: px, y: py, txt: fmt(p.dia, 1) });
        hits += `<circle class="dhit" data-ti="${t.ti}" data-vi="${p.vi}" cx="${px}" cy="${py}" r="9"/>`;
      });
      const [ex, ey] = P(pp[pp.length - 1]);
      s += f === 'live' ? `<circle cx="${ex}" cy="${ey}" r="4" fill="${LIVE}"/>`
        : f === 'dead' ? `<path d="M${ex - 4} ${ey - 4}L${ex + 4} ${ey + 4}M${ex - 4} ${ey + 4}L${ex + 4} ${ey - 4}" stroke="${DEAD}" stroke-width="2.2"/>`
        : f === 'cut' ? `<rect x="${ex - 4}" y="${ey - 4}" width="8" height="8" fill="${CUT}"/>`
        : `<circle cx="${ex}" cy="${ey}" r="4" fill="var(--panel)" stroke="${CUT}" stroke-width="1.6"/>`;
      trees += `<g class="sptree" data-ti="${t.ti}">${s}</g>`;
      if (pp.length > 1) lhits += `<polyline class="lhit" data-ti="${t.ti}" points="${pp.map(p => P(p).join(',')).join(' ')}"/>`;
    }
    // labels: per survey, beside the dot (right, else left); pushed down a little with a leader line when crowded; dropped
    // when that would move them too far (the value stays in the tooltip)
    const GAP = 11.5, MAXSH = 24, WL = 26, placed = [], dropped = [];
    const cols = [...new Set(labs.map(l => l.vi))].sort((a, b) => V[a].dy - V[b].dy);
    cols.forEach((vi, ci) => {
      const arr = labs.filter(l => l.vi === vi).sort((a, b) => a.y - b.y), ax = arr[0].x;
      const prevX = ci ? X(V[cols[ci - 1]].dy) : -1e9, nextX = ci < cols.length - 1 ? X(V[cols[ci + 1]].dy) : 1e9;
      const sides = [];
      if (ax + 6 + WL <= W - 2 && nextX - ax >= 6 + WL + 4) sides.push({ dx: 6, anchor: 'start', last: -1e9 });
      if (ax - 6 - WL >= L + 2 && ax - prevX >= 2 * (6 + WL) + 6) sides.push({ dx: -6, anchor: 'end', last: -1e9 });
      for (const lb of arr) {
        let best = null;
        for (const s of sides) {
          const want = lb.y + 3.5, yy = Math.max(want, s.last + GAP), d = yy - want;
          if (d <= MAXSH && yy <= H - B + 2 && (!best || d < best.d)) best = { s, yy, d };
        }
        if (!best) { dropped.push(lb); continue; }
        best.s.last = best.yy;
        placed.push({ ...lb, lx: lb.x + best.s.dx, ly: best.yy, anchor: best.s.anchor, lead: best.d > 10 });
      }
    });
    let lt = '';
    for (const l of placed) {
      if (l.lead) lt += `<line class="splead" data-ti="${l.ti}" x1="${l.x}" y1="${l.y}" x2="${l.lx + (l.anchor === 'start' ? 1 : -1)}" y2="${l.ly - 8}"/>`;
      lt += `<text class="splab" data-ti="${l.ti}" data-vi="${l.vi}" x="${l.lx}" y="${l.ly}" text-anchor="${l.anchor}">${l.txt}</text>`;
    }
    const svg = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(sp.name)}: diameter of ${sp.trees.length} trees at each survey">`
      + `${g}<g class="trees">${trees}</g><g class="labs">${lt}</g><g class="hits">${lhits}${hits}</g></svg>`
      + (dropped.length ? `<p class="muted spdrop">${dropped.length} label${dropped.length === 1 ? '' : 's'} hidden to avoid overlap; hover or tap a dot for its value.</p>` : '');
    return { svg, placed, dropped };
  }
})();

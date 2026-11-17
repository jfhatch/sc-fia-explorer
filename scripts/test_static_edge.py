"""Headless Edge test of the static site (local folder or the live URL).

Usage: python -I scripts/test_static_edge.py --latlon "<lat>,<lon>" (--site DIR | --url https://.../) [--pdf plot25_summary.pdf] [--shots DIR]

--browser: path of another Chromium browser (e.g. Chrome) instead of Edge.
--pdf: the Plot 25 summary PDF to compare the 91-25 plot page with (numbers in the survey, tree-total, volume/carbon and
       species tables, the headline tiles and the highlights). The file is read only; nothing from it is stored.

The location is typed into the page only: never written to disk or printed, and the test asserts no request carried it.
Checks: map loads every plot and shows only active plots (last MEASYEAR within 7 years of the current year) by default;
"Show historical plots" adds the rest as hollow markers and is kept in the URL (?historical=1); USGS tiles answer HTTP 200;
plot 91-25 and a periodic-only (historical) plot via ID search; 91-25 via location search, with historical plots listed
separately; plot page
totals = 35/82/82/101/92 ft²/ac; history charts and tabs render; phone viewport (filter panel collapses, map and plot
page usable without horizontal scrolling); no CSP violations, no cookies, no requests to hosts other than the site
and basemap.nationalmap.gov.
"""
import os, sys, io, json, math, time, base64, datetime, shutil, subprocess, tempfile, urllib.request, functools, threading, http.server
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
from test_ui_edge import CDP, free_port
from fiasc import summary_pdf, core

KEY = "45-3-91-25"
POPUP_KEY = "45-3-91-5"          # the popup reported with unreadable headers / a clipped last column
# WCAG contrast of every element matching SEL against its effective (first non-transparent ancestor) background
CONTRAST_JS = """((sel) => {
  const rgb = c => c.match(/[\\d.]+/g).map(Number);
  const lum = c => { const f = v => (v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; const [r, g, b] = rgb(c); return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const bg = el => { for (let e = el; e; e = e.parentElement) { const c = getComputedStyle(e).backgroundColor, a = rgb(c); if (a.length < 4 || a[3] > 0.5) return c; } return 'rgb(255, 255, 255)'; };
  const els = [...document.querySelectorAll(sel)];
  const r = els.map(el => { const a = lum(getComputedStyle(el).color), b = lum(bg(el)); return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05); });
  return { n: els.length, min: r.length ? Math.min(...r) : null };
})"""
HELP_JS = """((sel) => {
  const ths = [...document.querySelectorAll(sel || 'th')].filter(t => t.getClientRects().length);
  const bad = ths.filter(t => { const k = t.dataset.hk, h = k && helpFor(k); return !t.querySelector('.hb') || !h || !h.text; })
    .map(t => (t.dataset.hk || '?') + ':' + t.textContent.trim().slice(0, 30));
  return { n: ths.length, bad: bad.slice(0, 8), nbad: bad.length };
})"""
NUMS = lambda t: [x.replace(",", "") for x in __import__("re").findall(r"(?<![\d.-])\d[\d,]*(?:\.\d+)?", t.replace("†", ""))]
POPUP_FIT_JS = """(() => {
  const w = document.querySelector('.leaflet-popup-content-wrapper'), pc = document.querySelector('.leaflet-popup-content'),
        ps = pc && pc.querySelector('.popscroll'), t = ps && ps.querySelector('table');
  if (!t) return null;
  const W = w.getBoundingClientRect(), C = pc.getBoundingClientRect(), R = ps.getBoundingClientRect(), M = map.getContainer().getBoundingClientRect();
  const ox = getComputedStyle(ps).overflowX;
  return { fits: t.scrollWidth <= ps.clientWidth + 1, scroll: ox === 'auto' || ox === 'scroll',
           inside: R.left >= C.left - 1 && R.right <= C.right + 1 && W.left >= M.left - 1 && W.right <= M.right + 1,
           tw: t.scrollWidth, bw: ps.clientWidth, pw: Math.round(W.width), mw: Math.round(M.width) };
})()"""
TILE_HOST = "basemap.nationalmap.gov"


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def main():
    a = sys.argv[1:]
    if "--latlon" not in a or not ("--site" in a or "--url" in a):
        print(__doc__); return 2
    lat_s, lon_s = [x.strip() for x in a[a.index("--latlon") + 1].split(",")]
    httpd = None
    if "--site" in a:
        site = os.path.abspath(a[a.index("--site") + 1])
        port = free_port()
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Quiet, directory=site))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}/"
    else:
        base = a[a.index("--url") + 1].rstrip("/") + "/"
    host = base.split("/")[2]
    prof = tempfile.mkdtemp(prefix="edge_static_test_")
    dport = free_port()
    edge = subprocess.Popen([a[a.index("--browser") + 1] if "--browser" in a else summary_pdf.find_edge(), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                             f"--user-data-dir={prof}", f"--remote-debugging-port={dport}", "--window-size=1400,900", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    results = []
    c = None

    seen = [0]

    def check(name, cond, detail=""):
        results.append(bool(cond))
        print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")
        if "--debug" in a and c is not None:
            ex = [e for e in c.events if e.get("method") == "Runtime.exceptionThrown"]
            if len(ex) != seen[0]:
                print("   DEBUG new JS exception(s) during this step:", ex[-1]["params"]["exceptionDetails"].get("exception", {}).get("description", "")[:1200])
            seen[0] = len(ex)

    try:
        for _ in range(80):
            try:
                page = next(t for t in json.load(urllib.request.urlopen(f"http://127.0.0.1:{dport}/json", timeout=2)) if t.get("type") == "page"); break
            except Exception:
                time.sleep(0.25)
        c = CDP(page["webSocketDebuggerUrl"])
        for d in ("Page", "Runtime", "Network", "Log"):
            c.call(f"{d}.enable")
        c.call("Network.setCacheDisabled", cacheDisabled=True)

        def responses():
            return [e["params"]["response"] for e in c.events if e.get("method") == "Network.responseReceived"]

        def requests():
            return [e["params"]["request"] for e in c.events if e.get("method") == "Network.requestWillBeSent"]

        def csp_errors():
            out = []
            for e in c.events:
                if e.get("method") == "Log.entryAdded":
                    t = e["params"]["entry"].get("text", "")
                    if "Content Security Policy" in t or "Content-Security-Policy" in t:
                        out.append(t[:160])
                if e.get("method") == "Runtime.exceptionThrown":
                    out.append("JS exception: " + json.dumps(e["params"]["exceptionDetails"].get("exception", {}).get("description", ""))[:1500])
            return out

        def wait_or_dump(expr, t, what):
            try:
                return c.wait(expr, t, what)
            except TimeoutError:
                print("   DEBUG", what, c.js("JSON.stringify({w: innerWidth, z: map.getZoom(), onmap: !!APP.markers.get('" + KEY + "')._map, open: APP.markers.get('" + KEY + "').isPopupOpen(), "
                      "inCl: cluster.hasLayer(APP.markers.get('" + KEY + "')), pop: !!document.querySelector('.leaflet-popup'), tok: focusKey.token})"))
                return False
        # 1. map + tiles
        t0 = time.time()
        c.goto(base + "index.html")
        c.wait("document.body.dataset.ready === '1' || document.body.dataset.ready === 'error'", what="map ready")
        n_rows = c.js("APP.rows.length"); n_vis = int(c.js("document.body.dataset.visible || 0"))
        n_meta = c.js("FIA.meta.build.locations")
        # expected counts, computed here from the published plots.json (not from the page's own logic)
        P = json.load(urllib.request.urlopen(base + "data/plots.json", timeout=60))
        ci = {k: i for i, k in enumerate(P["c"])}
        act_from = datetime.date.today().year - 7
        is_act = lambda r: r[ci["m"]] >= act_from
        n_act = sum(map(is_act, P["r"])); n_hist = len(P["r"]) - n_act
        per_key = next(r[ci["k"]] for r in P["r"] if r[ci["d"]] == "p")          # a periodic-only plot: historical
        try:
            c.wait("document.querySelectorAll('.marker-cluster').length > 0", 20, "cluster icons")
        except TimeoutError:
            pass
        cl0 = c.js("({z: map.getZoom(), icons: document.querySelectorAll('.marker-cluster').length,"
                   " inView: cluster.getLayers().filter(m => map.getBounds().contains(m.getLatLng())).length})")
        vreq = [r["url"] for r in requests() if "/data/plots.json" in r["url"] or r["url"].split("?")[0].endswith("/map.js")]
        check("numbered cluster circles are drawn on load, the view is fitted to the plots, and scripts/data are versioned (?v=)",
              cl0["icons"] > 0 and cl0["z"] >= 6 and cl0["inView"] == n_act and vreq and all("?v=" in u for u in vreq),
              f"{cl0['icons']} cluster icons at zoom {cl0['z']}; {cl0['inView']:,} active plots in view; {len(vreq)} versioned requests")
        st0 = c.js("({act: +document.body.dataset.active, hist: +document.body.dataset.historical, txt: document.querySelector('#count').textContent,"
                   " onMap: cluster.getLayers().length, histOnMap: histCluster.getLayers().length, box: document.querySelector('#f_hist').checked,"
                   " note: document.querySelector('#histnote').textContent,"
                   " legend: [...document.querySelectorAll('#legend [data-gn]')].reduce((t, e) => t + +e.textContent.replace(/[^0-9]/g, ''), 0)})")
        check("map loads every plot location", n_rows == n_meta == len(P["r"]) and n_rows > ("--allow-subset" in a and 100 or 1000), f"{n_rows:,} locations in {time.time() - t0:.1f}s")
        check(f"default view: active plots only (last measured {act_from}+): map, count and legend",
              st0["act"] == n_act and st0["hist"] == 0 and n_vis == n_act and st0["onMap"] == n_act and st0["histOnMap"] == 0 and not st0["box"]
              and f"{n_act:,} active plot locations" in st0["txt"] and str(act_from) in st0["note"] and st0["legend"] == n_act,
              f"{n_act:,} active of {n_rows:,}; count '{st0['txt']}'; legend total {st0['legend']:,}")
        c.js("map.setView([34.0, -81.0], 9); true")
        c.wait("TILES.ok() >= 4", 60, "tiles")
        time.sleep(1.5)
        c.js("1")
        tiles = [r for r in responses() if TILE_HOST in r["url"]]
        bad = [r["status"] for r in tiles if r["status"] != 200]
        check("USGS Topo tiles return HTTP 200", tiles and not bad, f"{len(tiles)} tile responses, statuses {sorted(set(r['status'] for r in tiles))}")
        n0 = c.js("TILES.ok()")
        c.js("document.querySelector('#basemap').value='imgtopo'; document.querySelector('#basemap').dispatchEvent(new Event('change')); true")
        c.wait(f"TILES.ok() >= {n0} + 8", 60, "imagery tiles")
        time.sleep(1)
        c.js("1")                                   # drain pending DevTools events
        img = [r for r in responses() if "USGSImageryOnly" in r["url"]]
        check("Imagery + Topo basemap tiles return HTTP 200", img and all(r["status"] == 200 for r in img), f"{len(img)} imagery tiles")
        c.js("document.querySelector('#basemap').value='plain'; document.querySelector('#basemap').dispatchEvent(new Event('change')); true")
        # 1b. "Show historical plots" toggle, kept in the URL
        c.js("document.querySelector('#f_hist').click(); true")
        c.wait("+document.body.dataset.historical > 0", 30, "historical plots")
        st1 = c.js("({act: +document.body.dataset.active, hist: +document.body.dataset.historical, txt: document.querySelector('#count').textContent,"
                   " onMap: cluster.getLayers().length, histOnMap: histCluster.getLayers().length, q: location.search,"
                   " legend: !document.querySelector('#histlegend').classList.contains('hidden'),"
                   " hollow: (m => m.options.fill === false && m.options.color !== '#222')(histCluster.getLayers()[0])})")
        check("toggle on: historical plots added as hollow markers in their own clusters; count 'N active + M historical'; ?historical=1",
              st1["act"] == n_act and st1["hist"] == n_hist and st1["onMap"] == n_act and st1["histOnMap"] == n_hist and st1["hollow"] and st1["legend"]
              and f"{n_act:,} active + {n_hist:,} historical" in st1["txt"] and st1["q"] == "?historical=1", f"'{st1['txt']}', URL {st1['q']}")
        c.goto(base + "index.html?historical=1")
        c.wait("document.body.dataset.ready === '1'", what="map with ?historical=1")
        st2 = c.js("[document.querySelector('#f_hist').checked, +document.body.dataset.visible]")
        c.js("document.querySelector('#f_hist').click(); true")
        c.wait("+document.body.dataset.historical === 0", 30, "toggle off")
        st3 = c.js("[location.search, +document.body.dataset.visible, histCluster.getLayers().length]")
        check("shared link ?historical=1 opens with the toggle on; turning it off restores the active-only view and URL",
              st2 == [True, n_rows] and st3 == ["", n_act, 0], f"link: {st2}; off: {st3}")
        # 1c. map popup: header contrast (light + dark) and no clipped table (1280 px and 390 px)
        pop = []
        pkey = POPUP_KEY if any(r[ci["k"]] == POPUP_KEY for r in P["r"]) else KEY      # subset builds may not contain it
        for width, height, mobile in ((1280, 900, False), (390, 844, True)):
            c.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=mobile)
            for scheme in ("light", "dark"):
                c.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
                c.goto(base + "index.html")
                c.wait("document.body.dataset.ready === '1'", what="map for popup")
                c.js(f"focusKey('{pkey}'); true")
                try:
                    c.wait("!!document.querySelector('.leaflet-popup-content .popscroll table')", 60, "popup table")
                    # measure only once the map has finished panning to the popup (position unchanged over 400 ms)
                    pos = lambda: c.js("JSON.stringify(document.querySelector('.leaflet-popup-content-wrapper').getBoundingClientRect())")
                    for _ in range(40):
                        p0 = pos(); time.sleep(0.4)
                        if pos() == p0:
                            break
                    con_ = c.js(CONTRAST_JS + "('.leaflet-popup-content th')")
                    fit = c.js(POPUP_FIT_JS)
                except TimeoutError:
                    con_, fit = {"n": 0, "min": 0}, None
                pop.append((width, scheme, con_, fit))
        c.call("Emulation.setEmulatedMedia", features=[])
        c.call("Emulation.clearDeviceMetricsOverride")
        check(f"popup ({pkey}) header contrast ≥ 4.5:1 in light and dark mode",
              all(p[2]["n"] >= 8 and p[2]["min"] >= 4.5 for p in pop), "; ".join(f"{w}px {sc}: {cn['min'] and round(cn['min'], 1)}:1 over {cn['n']} headers" for w, sc, cn, _ in pop))
        check("popup table not clipped: fits at 1280 px; at 390 px fits or scrolls inside the popup",
              all(f and f["inside"] and (f["fits"] if w == 1280 else (f["fits"] or f["scroll"])) for w, _, _, f in pop),
              "; ".join(f"{w}px {sc}: table {f and f['tw']}px in {f and f['bw']}px box, popup {f and f['pw']}px, scroll={f and f['scroll']}, inside={f and f['inside']}" for w, sc, _, f in pop))
        c.goto(base + "index.html")
        c.wait("document.body.dataset.ready === '1'", what="map")
        # 2. ID search
        c.js("document.querySelector('#idq').value = '91-25'; document.querySelector('#idgo').click(); true")
        check("search by plot ID 91-25 (active)", c.wait(f"document.querySelector('#id_out li[data-key=\"{KEY}\"]')?.dataset.active === '1'", what="ID result")
              and wait_or_dump(f"APP.markers.get('{KEY}').isPopupOpen() && !!document.querySelector('.leaflet-popup-content table')", 60, "91-25 popup"))
        c.js("document.querySelector('#idq').value = '809203876290487'; document.querySelector('#idgo').click(); true")
        check("search by PLOT CN (2021 visit of 91-25)", c.wait(f"!!document.querySelector('#id_out li[data-key=\"{KEY}\"]')", what="CN result"))
        c.js(f"document.querySelector('#idq').value = '{per_key}'; document.querySelector('#idgo').click(); true")
        ok = c.wait(f"document.querySelector('#id_out li[data-key=\"{per_key}\"]')?.dataset.active === '0' && /Historical plot — last measured/.test(document.querySelector('#id_out').textContent)", what="periodic ID result")
        ok = ok and c.wait(f"APP.markers.get('{per_key}').isPopupOpen() && /Historical plot — last measured/.test(document.querySelector('.leaflet-popup-content').textContent)", 60, "historical popup")
        st4 = c.js("[+document.body.dataset.historical, document.querySelector('#count').textContent, document.querySelector('.leaflet-popup-content .histbadge').textContent]")
        check(f"ID search finds a periodic-only historical plot ({per_key}) while historical plots are hidden; opened with badge",
              ok and st4[0] == 0 and "+ 1 search result" in st4[1], f"badge '{st4[2]}'; count '{st4[1]}'")
        # 3. location search (client-side only)
        c.events.clear(); seen[0] = 0
        c.js("document.querySelector('#locbtn').click(); true")
        c.wait("!!document.querySelector('#l_lat')")
        c.js(f"document.querySelector('#l_lat').value = {json.dumps(lat_s)}; document.querySelector('#l_lon').value = {json.dumps(lon_s)};"
             "document.querySelector('#l_rad').value = '2'; document.querySelector('#l_go').click(); true")
        c.wait("!!document.querySelector('#l_list') || /No active public plot/.test(document.querySelector('#l_out').textContent)")
        items = c.js("[...document.querySelectorAll('#l_list li')].map(li => [li.dataset.key, +li.dataset.dist, li.dataset.active])")
        keys = [k for k, _, _ in items]
        rank = keys.index(KEY) + 1 if KEY in keys else None
        check("location search finds 91-25", rank is not None, f"rank {rank} of {len(items)} within 2 mi" if rank else "")

        def mi(la1, lo1, la2, lo2):
            r = math.pi / 180
            x = math.sin((la2 - la1) * r / 2) ** 2 + math.cos(la1 * r) * math.cos(la2 * r) * math.sin((lo2 - lo1) * r / 2) ** 2
            return 2 * 3958.8 * math.asin(math.sqrt(x))
        near = [r for r in P["r"] if mi(float(lat_s), float(lon_s), r[ci["la"]], r[ci["lo"]]) <= 2]
        e_act = min(50, sum(map(is_act, near))); e_hist = min(50, len(near) - sum(map(is_act, near)))
        hl = c.js("[document.querySelectorAll('#l_hist_list li').length, !!document.querySelector('#l_hist') && !document.querySelector('#l_hist').open,"
                  " [...document.querySelectorAll('#l_hist_list li')].every(li => li.dataset.active === '0')]")
        check("location results: active plots listed; historical plots in a collapsed 'Historical plots nearby' section",
              all(x[2] == "1" for x in items) and len(items) == e_act and hl[0] == e_hist and (hl[1] or e_hist == 0) and hl[2],
              f"{len(items)} active + {hl[0]} historical within 2 mi (expected {e_act} + {e_hist}); collapsed={hl[1]}")
        del near
        time.sleep(0.5)
        reqs = requests()
        leaked = [r["url"] for r in reqs if lat_s in r["url"] or lon_s in r["url"] or lat_s in (r.get("postData") or "") or lon_s in (r.get("postData") or "")]
        check("location search made no network request containing the point", not leaked, f"{len(reqs)} requests during the search")
        c.js("document.querySelector('#l_clear').click(); true")
        check("'Clear and forget' wipes the point; nothing in storage, cookies or URL",
              c.js("document.querySelector('#l_lat').value === '' && APP.locLayer === null && !location.search && !location.hash "
                   "&& localStorage.length === 0 && sessionStorage.length === 0 && document.cookie === ''"))
        # 4. plot page
        c.goto(f"{base}plot.html?k={KEY}")
        c.wait("document.body.dataset.ready === '1' || document.body.dataset.ready === 'error'", what="plot page")
        got = {int(k): v for k, v in (c.js("Object.fromEntries([...document.querySelectorAll('#totals tr[data-invyr]')].map(tr => [tr.dataset.invyr, +tr.querySelector('[data-ba]').dataset.ba]))") or {}).items()}
        exp = core.REGRESSION_BA[KEY]
        check("plot page totals match the report (35/82/82/101/92 ft²/ac)", all(int(round(got.get(y, -1))) == v for y, v in exp.items()),
              " / ".join(f"{y}: {got.get(y, float('nan')):.1f}" for y in exp))
        charts = c.js("['c_vol','c_c','c_stack','c_growth','c_mort'].filter(id => document.getElementById(id)?.querySelector('.main-svg')).length")
        mp = c.js("PLOT.hist.microplot_moved.join(',')")
        relo = c.js("PLOT.hist.events.filter(e => e.cls === 'microplot relocation addition').length")
        sm = c.js("document.querySelectorAll('#smult figure').length")
        check("charts render (volume, carbon, BA by species, growth, mortality, small multiples); microplot relocation separated",
              charts == 5 and sm >= 10 and mp == "2006" and relo == 17, f"{charts}/5 charts; {sm} species panels; moved {mp}; {relo} relocation additions")
        ntr = c.js("document.querySelectorAll('.vsect[data-ds=trees] tbody tr').length")
        cond = c.js("(document.querySelector('.vsect[data-ds=cond]') || {}).textContent || ''")
        nsec = c.js("document.querySelectorAll('#details .vsect').length")
        check("visit details: every section expanded, decoded", ntr > 10 and "Private" in cond and nsec >= 6, f"{nsec} sections open; {ntr} tree rows; conditions decoded")
        # survey summary, tree totals, KPIs, highlights from the shared summary (fiasc.summary = the PDF's computations)
        st = c.js("JSON.stringify({pred: [...document.querySelectorAll('#totals tr.predrow')].map(r => r.textContent.replace(/\\s+/g, ' ').trim()), kpi: document.querySelector('#kpis').textContent.replace(/\\s+/g, ' '), "
                  "tt: [...document.querySelectorAll('#treetot_t tbody tr')].map(r => [...r.cells].map(x => x.textContent.trim())), hl: document.querySelector('#hl').textContent, drops: (document.querySelector('#drops')||{}).textContent || '', comp: document.querySelector('#compcap').textContent})")
        st = json.loads(st)
        ok_pred = len(st["pred"]) == 2 and all(x in st["pred"][0] for x in ["Dec 1985", "41", "160†", "120†", "91.0†", "7.7†", "2,205†", "23.6†"]) and "9 cut" in st["pred"][1]
        ok_tt = st["tt"][1] == ["2006", "2006-08-03", "40", "22", "18", "3", "18", "1", "11", "17"]
        ok_kpi = all(x in st["kpi"] for x in ["35 → 92", "peak 101 in 2016", "5.7 → 21.5", "346 → 1,628", "10 → 34"])
        check("survey summary with predecessor rows, tree totals, KPI tiles and generated highlights / captions",
              ok_pred and ok_tt and ok_kpi and "0.73" in st["hl"] and "-15.1" in st["drops"] and "2 saplings crossing 5.0 in" in st["drops"] and "From 2000 to 2021" in st["comp"],
              f"pred rows {ok_pred}; tree totals {ok_tt}; KPIs {ok_kpi}; drop text {'yes' if st['drops'] else 'no'}")
        if "--pdf" in a:
            from pypdf import PdfReader
            ptxt = "\n".join((pg.extract_text() or "") for pg in PdfReader(a[a.index("--pdf") + 1]).pages)
            # drop the PDF's running header/footer (build date, page numbers)
            ptxt = __import__("re").sub(r"FIA Plot \d+ · [^\n]*?summary|Built \d{4}-\d{2}-\d{2}|Page \d+ of \d+", "", ptxt)
            s0 = ptxt.index("1. Survey summary") if "1. Survey summary" in ptxt else 0          # dates also appear in the PDF's header line
            seg = lambda start, n=260: ptxt[ptxt.index(start, s0):ptxt.index(start, s0) + n] if start in ptxt[s0:] else ""
            rows = c.js("[...document.querySelectorAll('#totals tbody tr')].map(r => [...r.cells].slice(1, 9).map(x => x.textContent.trim()).filter((x, i) => i !== 1))")
            labels = c.js("[...document.querySelectorAll('#totals tbody tr')].map(r => r.cells[0].querySelector('b').textContent.trim())")
            bad = []
            for lab_, cells in zip(labels, rows):
                want = [NUMS(x)[0] for x in cells if NUMS(x)]
                got = NUMS(seg(lab_))
                pos = 0
                for w in want:
                    while pos < len(got) and got[pos] != w:
                        pos += 1
                    if pos == len(got):
                        bad.append(f"survey {lab_}: {w}"); break
            for row in st["tt"]:
                if " ".join(NUMS(" ".join(row))) not in " ".join(NUMS(seg(row[0] + " " + row[1], 120))):
                    bad.append(f"tree totals {row[0]}")
            for tid in ("vc", "species"):
                for r in c.js(f"[...document.querySelectorAll('#{tid} table.sp tbody tr')].map(r => [...r.cells].map(x => x.textContent.trim()))"):
                    nm = r[0].replace("All species", "All species")
                    if nm not in ptxt:
                        bad.append(f"{tid} species {nm} missing from PDF"); continue
                    vals = " ".join(NUMS(" ".join(r[1:])))
                    hits = [m.start() for m in __import__("re").finditer(__import__("re").escape(nm), ptxt)]
                    if not any(vals in " ".join(NUMS(ptxt[h + len(nm):h + len(nm) + 160])) for h in hits):
                        bad.append(f"{tid} row {nm}")
            hl_pdf = ptxt[ptxt.index("Stand origin."):ptxt.index("1. Survey summary")] if "Stand origin." in ptxt else ""
            hl_page = " ".join(NUMS(st["hl"] + " " + c.js("document.querySelector('#title').textContent + ' ' + document.querySelector('#subtitle').textContent")))
            missing = sorted({n for n in NUMS(hl_pdf) if n not in hl_page.split()})
            if missing:
                bad.append(f"highlight numbers not on the page: {missing}")
            check("Plot 91-25 numbers match the Plot 25 summary PDF (survey, tree totals, volume/carbon, species, KPIs, highlights)",
                  not bad, f"{len(labels)} survey rows, {len(st['tt'])} tree-total rows compared" + (f"; differences: {bad[:6]}" if bad else ""))
        flag = 0
        hc = []
        for scheme in ("light", "dark"):
            c.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
            time.sleep(0.3)
            hc.append((scheme, c.js(CONTRAST_JS + "('th')")))
        c.goto(base + "index.html")
        c.wait("document.body.dataset.ready === '1'", what="map")
        c.js("document.querySelector('#attrbtn').click(); document.querySelector('#a_cty').value = '91'; document.querySelector('#a_go').click(); true")
        c.wait("document.querySelectorAll('#a_out th').length > 0", what="attribute results")
        for scheme in ("light", "dark"):
            c.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
            time.sleep(0.3)
            hc.append((scheme + " (attribute search)", c.js(CONTRAST_JS + "('th')")))
        c.call("Emulation.setEmulatedMedia", features=[])
        check("table headers elsewhere (plot page, attribute search) ≥ 4.5:1 in light and dark mode",
              all(x["n"] and x["min"] >= 4.5 for _, x in hc), "; ".join(f"{s_}: {round(x['min'], 1)}:1 over {x['n']}" for s_, x in hc))
        hcov = [("attribute search", c.js(HELP_JS + "('#a_out th')"))]
        c.js(f"focusKey('{KEY}'); true"); c.wait("!!document.querySelector('.leaflet-popup-content th')", 60, "popup")
        hcov.append(("map popup", c.js(HELP_JS + "('.leaflet-popup-content th')")))
        # ---------------- plot page: help, tooltips, view switch, expert view
        t0p = time.time()
        c.goto(f"{base}plot.html?k={KEY}&view=standard")
        c.wait("document.body.dataset.ready === '1'", what="plot page")
        t_load = time.time() - t0p
        hcov.append(("plot page, standard", c.js(HELP_JS + "()")))
        hover = False
        for _ in range(3):        # the pointer can land mid-scroll: move away and back, up to three times
            hb = c.js("(() => { const b = document.querySelector('#totals .hb'); b.scrollIntoView({block: 'center'}); const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
            time.sleep(0.3)
            c.call("Input.dispatchMouseEvent", type="mouseMoved", x=5, y=5)
            c.call("Input.dispatchMouseEvent", type="mouseMoved", x=hb[0], y=hb[1])
            try:
                hover = c.wait("!!document.querySelector('#hpop:not([hidden])') && document.querySelector('#hpop').textContent.length > 20", 4, "hover help")
                break
            except TimeoutError:
                pass
        c.call("Input.dispatchMouseEvent", type="mouseMoved", x=5, y=5); c.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'})); true")
        c.js("document.querySelector('#treetot_t .hb').focus(); true")
        kb = c.wait("document.querySelector('#hpop') && !document.querySelector('#hpop').hidden && /Glossary/.test(document.querySelector('#hpop').textContent)", 5, "keyboard help")
        con2 = []
        for scheme in ("light", "dark"):
            c.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}]); time.sleep(0.3)
            con2.append(c.js(CONTRAST_JS + "('#hpop p, #hpop .hp-t, #hpop a')")["min"])
        c.call("Emulation.setEmulatedMedia", features=[])
        c.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'})); true")
        esc_ok = c.js("document.querySelector('#hpop').hidden")
        tl = c.js("(() => { const b = document.querySelector('#timeline .tc.pred'); b.scrollIntoView({block: 'center'}); const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + 10]; })()")
        c.call("Input.dispatchMouseEvent", type="mouseMoved", x=tl[0], y=tl[1])
        tl_ok = c.wait("!!document.querySelector('#tltip:not([hidden])') && /inferred, not database-linked/i.test(document.querySelector('#tltip').textContent)", 5, "timeline tooltip")
        c.js("document.querySelector('#timeline .tc[data-vi=\"4\"]').focus(); true")
        tl2 = c.js("document.querySelector('#tltip').textContent")
        check("help: ⓘ on hover and keyboard focus, Escape closes; contrast ≥ 4.5:1 light and dark; timeline tooltips explain card styles",
              hover and kb and esc_ok and min(con2) >= 4.5 and tl_ok and "Blue 2-px border" in tl2 and "92.2" in tl2,
              f"hover {bool(hover)}, keyboard {bool(kb)}, contrast {round(min(con2), 1)}:1; timeline: '{tl2[:90]}…'")
        # view switch: URL and localStorage round trip
        c.js("document.querySelector('.viewsw button[data-v=expert]').click(); true")
        c.wait("document.body.dataset.expertReady === '1'", 60, "expert panels")
        v1 = c.js("[location.search.includes('view=expert'), localStorage.getItem('fia_view')]")
        hcov.append(("plot page, expert", c.js(HELP_JS + "()")))
        c.goto(f"{base}plot.html?k={KEY}")
        c.wait("document.body.dataset.ready === '1'", what="plot page (stored view)")
        v2 = c.js("document.documentElement.dataset.view")
        c.wait("document.body.dataset.expertReady === '1'", 60, "expert panels")
        # expert values: same calculations as standard; SDI and 2-in classes against a hand calculation from the plot's tree records
        PJ = json.load(urllib.request.urlopen(f"{base}p/{KEY}.json", timeout=60))
        tc = {k_: i for i, k_ in enumerate(PJ["tr"]["c"])}
        vi4 = len(PJ["v"]) - 1
        L4 = [r for r in PJ["tr"]["r"] if r[tc["vi"]] == vi4 and r[tc["STATUSCD"]] == 1 and r[tc["TPA_UNADJ"]] is not None and r[tc["DIA"]] is not None]
        tpa = sum(r[tc["TPA_UNADJ"]] for r in L4); qmd = math.sqrt(sum(r[tc["DIA"]] ** 2 * r[tc["TPA_UNADJ"]] for r in L4) / tpa)
        sdi = tpa * (qmd / 10) ** 1.605
        hand = {}
        for r in L4:
            k_ = (math.floor((r[tc["DIA"]] - 1) / 2), r[tc["SPCD"]])
            o = hand.setdefault(k_, [0.0, 0.0, 0.0])
            o[0] += r[tc["TPA_UNADJ"]]; o[1] += 0.005454154 * r[tc["DIA"]] ** 2 * r[tc["TPA_UNADJ"]]; o[2] += (r[tc["VOLCFNET"]] or 0) * r[tc["TPA_UNADJ"]]
        page = {(x["k"], x["sp"]): [x["tpa"], x["ba"], x["vol"]] for x in c.js(f"EXPERT_standTable(PLOT.P, {vi4})")}
        dcl_ok = set(page) == set(hand) and all(all(abs(a_ - b_) < 1e-6 for a_, b_ in zip(page[k_], hand[k_])) for k_ in hand)
        sdi_pg = float(c.js("document.querySelector('#x_sdi').dataset.sdi"))
        exp_ba = c.js("Object.fromEntries([...document.querySelectorAll('#totals tr[data-invyr]')].map(tr => [tr.dataset.invyr, +tr.querySelector('[data-ba]').dataset.ba]))")
        check("Standard | Expert switch round-trips via URL and localStorage; expert 91-25 values = report/PDF; SDI and 2-in classes = hand calculation",
              v1 == [True, "expert"] and v2 == "expert" and all(int(round(exp_ba[str(y)])) == v for y, v in core.REGRESSION_BA[KEY].items())
              and abs(sdi_pg - sdi) < 0.01 and dcl_ok and abs(sum(x[1] for x in hand.values()) - 92.2444) < 0.001,
              f"URL/storage {v1}, reload → {v2}; SDI page {sdi_pg:.2f} vs hand {sdi:.2f} (TPA {tpa:.1f}, QMD {qmd:.3f}); {len(hand)} class×species cells {'equal' if dcl_ok else 'DIFFER'}")
        # print to PDF (Chromium print engine via CDP): standard and expert
        pr = {}
        for view in ("standard", "expert"):
            c.goto(f"{base}plot.html?k={KEY}&view={view}")
            c.wait("document.body.dataset.ready === '1'", what="plot page for print")
            if view == "expert":
                c.wait("document.body.dataset.expertReady === '1'", 60, "expert panels")
            time.sleep(1.5)
            c.js("window.__pp = 0; PLOT.preparePrint({secs: null, trees: true, raw: false}).then(() => { window.__pp = 1; }); true")
            c.wait("window.__pp === 1", 90, "print preparation")
            n_img = c.js("document.querySelectorAll('img.chartimg').length")
            raw_ = c.js("!!document.querySelector('.rawappendix')")
            c.call("Emulation.setEmulatedMedia", media="print")
            c.call("Emulation.setDeviceMetricsOverride", width=701, height=1000, deviceScaleFactor=1, mobile=False)
            time.sleep(0.5)
            clip = c.js("[...document.querySelectorAll('section.psec[data-print=on] table')].filter(t => t.getClientRects().length && t.getBoundingClientRect().right > document.querySelector('.page').getBoundingClientRect().right + 1).length")
            c.call("Emulation.clearDeviceMetricsOverride"); c.call("Emulation.setEmulatedMedia", media="")
            pdfb = base64.b64decode(c.call("Page.printToPDF", preferCSSPageSize=True, printBackground=True)["data"])
            c.js("PLOT.printRestore(); true")
            from pypdf import PdfReader
            rd = PdfReader(io.BytesIO(pdfb)); texts = [pg.extract_text() or "" for pg in rd.pages]; imgs = [len(pg.images) for pg in rd.pages]
            blank = [i + 1 for i, (t, k_) in enumerate(zip(texts, imgs)) if len(t.strip()) < 80 and k_ == 0]
            allt = "\n".join(texts)
            pr[view] = dict(pages=len(rd.pages), imgs=sum(imgs), n_img=n_img, blank=blank, clip=clip, raw=raw_,
                            nums=all(x in allt for x in ["35.3", "81.5", "100.7", "92.2", "91.0", "2,205", "Terms used"]),
                            head=f"FIA Plot {KEY}" in allt, letter=abs(float(rd.pages[0].mediabox.width) - 612) < 1)
            if "--shots" in a:
                d = a[a.index("--shots") + 1]; os.makedirs(d, exist_ok=True)
                open(os.path.join(d, f"print_{view}.pdf"), "wb").write(pdfb)
        check("print to PDF (standard and expert): US Letter, every chart an image, no blank pages, no clipped tables, numbers and terms list present",
              all(x["letter"] and x["imgs"] == x["n_img"] >= 5 and not x["blank"] and x["clip"] == 0 and x["nums"] and x["head"] and 8 <= x["pages"] <= 45 and not x["raw"] for x in pr.values()),
              "; ".join(f"{v_}: {x['pages']} pages, {x['imgs']}/{x['n_img']} chart images, blank {x['blank']}, clipped tables {x['clip']}" for v_, x in pr.items()))
        # map print: one landscape page with legend and active filters
        c.goto(base + "index.html?view=standard"); c.wait("document.body.dataset.ready === '1'", what="map for print")
        c.js("window.print = () => { window.__printed = 1; }; document.querySelector('#printmap').click(); true")
        c.wait("window.__printed === 1", 20, "map print")
        mp_pdf = base64.b64decode(c.call("Page.printToPDF", preferCSSPageSize=True, printBackground=True)["data"])
        c.js("MAPX.printRestore(); true")
        from pypdf import PdfReader
        rm = PdfReader(io.BytesIO(mp_pdf)); mt = rm.pages[0].extract_text() or ""
        check("map print: one landscape page with extent, legend and active filters",
              len(rm.pages) == 1 and float(rm.pages[0].mediabox.width) > float(rm.pages[0].mediabox.height) and "Active filters" in mt and "Loblolly" in mt,
              f"{len(rm.pages)} page(s), {float(rm.pages[0].mediabox.width):.0f}×{float(rm.pages[0].mediabox.height):.0f} pt")
        if "--shots" in a:
            open(os.path.join(a[a.index("--shots") + 1], "print_map.pdf"), "wb").write(mp_pdf)
        # a periodic-only plot and a plot without a predecessor: no empty sections, no errors (standard and expert)
        other = []
        per_key2 = per_key
        nopred = next((r[ci["k"]] for r in P["r"] if r[ci["d"]] == "a" and r[ci["q"]] == 0 and r[ci["n"]] >= 3), None)
        for k_ in (per_key2, nopred):
            for view in ("standard", "expert"):
                n0 = len(c.events)
                c.goto(f"{base}plot.html?k={k_}&view={view}")
                c.wait("document.body.dataset.ready === '1' || document.body.dataset.ready === 'error'", what="other plot")
                if view == "expert":
                    c.wait("document.body.dataset.expertReady === '1'", 60, "expert panels")
                time.sleep(1)
                exc = [e for e in c.events[n0:] if e.get("method") == "Runtime.exceptionThrown"]
                empty = c.js("[...document.querySelectorAll('section.psec')].filter(s_ => s_.getClientRects().length).filter(s_ => { const t = s_.cloneNode(true); t.querySelectorAll('.intro, h2').forEach(x => x.remove()); return t.textContent.trim().length < 20; }).map(s_ => s_.dataset.sec)")
                etab = c.js("[...document.querySelectorAll('table')].filter(t => t.getClientRects().length && !t.querySelector('tbody tr')).length")
                hc_ = c.js(HELP_JS + "()")
                other.append((k_, view, len(exc), empty, etab, hc_["nbad"]))
        check("periodic-only plot and plot without predecessor render with no empty sections or tables, no errors, help on every header",
              all(o[2] == 0 and not o[3] and o[4] == 0 and o[5] == 0 for o in other) and nopred is not None,
              "; ".join(f"{o[0]} {o[1]}: errors {o[2]}, empty {o[3]}, empty tables {o[4]}, headers without help {o[5]}" for o in other))
        check("every visible column header has help text (map popup, attribute search, plot page standard and expert)",
              all(x["n"] and x["nbad"] == 0 for _, x in hcov), "; ".join(f"{n_}: {x['n']} headers, {x['nbad']} without help {x['bad'] if x['nbad'] else ''}" for n_, x in hcov))
        check("plot page loads fast", t_load < (12 if "--url" in a else 6), f"91-25 plot page ready in {t_load:.1f}s")
        # 5. phone viewport
        c.call("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=3, mobile=True)
        c.call("Emulation.setTouchEmulationEnabled", enabled=True)
        c.goto(base + "index.html")
        c.wait("document.body.dataset.ready === '1'", what="mobile map")
        try:
            mcl = c.wait("document.querySelectorAll('.marker-cluster').length > 0 && map.getZoom() >= 5", 20, "phone cluster icons")
        except TimeoutError:
            mcl = False
        check("phone: numbered cluster circles drawn on load", mcl, c.js("`${document.querySelectorAll('.marker-cluster').length} icons at zoom ${map.getZoom()}`"))
        st = c.js("(() => { const s = document.querySelector('#side').getBoundingClientRect(), m = document.querySelector('#map').getBoundingClientRect();"
                  " return [s.right <= 1, m.width, m.height, document.documentElement.scrollWidth]; })()")
        c.js("document.querySelector('#filtbtn').click(); true")
        try:
            # headless Edge can report the page as hidden and then never advances CSS transitions: finish them, then
            # measure the panel's final position
            opened = c.wait("document.getAnimations().forEach(x => x.finish()), "
                            "document.body.classList.contains('side-open') && document.querySelector('#side').getBoundingClientRect().left >= 0", 10, "filter panel")
        except TimeoutError:
            opened = False
            print("   DEBUG panel state:", c.js("JSON.stringify({cls: document.body.className, left: document.querySelector('#side').getBoundingClientRect().left, "
                  "tf: getComputedStyle(document.querySelector('#side')).transform, vis: document.visibilityState, anims: document.getAnimations().length, "
                  "w: innerWidth, btn: getComputedStyle(document.querySelector('#filtbtn')).display, exp: document.querySelector('#filtbtn').getAttribute('aria-expanded')})"))
        check("phone: filter panel collapsed by default and opens; map fills the screen; no horizontal scroll",
              st[0] and opened and st[1] >= 380 and st[2] > 500 and st[3] <= 390, f"collapsed={st[0]} opens={opened} map {st[1]:.0f}×{st[2]:.0f}px, page width {st[3]}px")
        c.goto(f"{base}plot.html?k={KEY}")
        c.wait("document.body.dataset.ready === '1'", what="mobile plot page")
        sw = c.js("document.documentElement.scrollWidth")
        check("phone: plot page fits the screen width", sw <= 392, f"scrollWidth {sw}px")
        def tap(sel_):
            xy = c.js(f"(() => {{ const b = document.querySelector({json.dumps(sel_)}); b.scrollIntoView({{block: 'center'}}); const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + Math.min(r.height / 2, 12)]; }})()")
            for t_ in ("mousePressed", "mouseReleased"):        # with touch emulation on, a press/release is delivered as a tap
                c.call("Input.dispatchMouseEvent", type=t_, x=xy[0], y=xy[1], button="left", clickCount=1)
        tap("#totals .hb")
        t1_ = c.wait("!!document.querySelector('#hpop:not([hidden])')", 5, "tap help")
        pw = c.js("document.querySelector('#hpop').getBoundingClientRect().right <= innerWidth + 1")
        tap("#timeline .tc[data-vi]")
        t2_ = c.wait("!!document.querySelector('#tltip:not([hidden])') && /Solid border/.test(document.querySelector('#tltip').textContent)", 5, "tap timeline")
        c.js("document.querySelector('.viewsw button[data-v=expert]').click(); true")
        c.wait("document.body.dataset.expertReady === '1'", 60, "phone expert")
        sw2 = c.js("document.documentElement.scrollWidth")
        c.js("document.querySelector('.viewsw button[data-v=standard]').click(); true")
        check("phone: help and timeline tooltips open on tap and fit the screen; expert view usable (no page-wide horizontal scroll)",
              t1_ and pw and t2_ and sw2 <= 392, f"help tap {bool(t1_)}, fits {pw}; timeline tap {bool(t2_)}; expert scrollWidth {sw2}px")
        shot = c.call("Page.captureScreenshot", format="png")["data"]
        if "--shots" in a:
            d = a[a.index("--shots") + 1]; os.makedirs(d, exist_ok=True)
            open(os.path.join(d, "mobile_plot.png"), "wb").write(base64.b64decode(shot))
        # 6. CSP, cookies, third parties
        hosts = sorted({r["url"].split("/")[2] for r in requests() if r["url"].startswith("http")})
        third = [h for h in hosts if h not in (host, TILE_HOST)]
        errs = csp_errors()
        check("no CSP violations or JS errors; only site + USGS tile hosts contacted", not errs and not third, f"hosts {hosts}" + (f"; {errs[:3]}" if errs else ""))
        c.ws.close()
    finally:
        edge.terminate()
        try:
            edge.wait(10)
        except Exception:
            edge.kill()
        if httpd:
            httpd.shutdown()
        time.sleep(1)
        shutil.rmtree(prof, ignore_errors=True)
    print(f"\n{'ALL PASSED' if all(results) else 'FAILED'}: {sum(results)}/{len(results)} checks against {base}; temporary Edge profile deleted")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())

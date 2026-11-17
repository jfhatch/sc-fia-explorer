"""Headless Edge test of the static site (local folder or the live URL).

Usage: python -I scripts/test_static_edge.py --latlon "<lat>,<lon>" (--site DIR | --url https://.../)

The location is typed into the page only: never written to disk or printed, and the test asserts no request carried it.
Checks: map loads every plot and shows only active plots (last MEASYEAR within 7 years of the current year) by default;
"Show historical plots" adds the rest as hollow markers and is kept in the URL (?historical=1); USGS tiles answer HTTP 200;
plot 91-25 and a periodic-only (historical) plot via ID search; 91-25 via location search, with historical plots listed
separately; plot page
totals = 35/82/82/101/92 ft²/ac; history charts and tabs render; phone viewport (filter panel collapses, map and plot
page usable without horizontal scrolling); no CSP violations, no cookies, no requests to hosts other than the site
and basemap.nationalmap.gov.
"""
import os, sys, json, math, time, datetime, shutil, subprocess, tempfile, urllib.request, functools, threading, http.server
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
from test_ui_edge import CDP, free_port
from fiasc import summary_pdf, core

KEY = "45-3-91-25"
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
    edge = subprocess.Popen([summary_pdf.find_edge(), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
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
        # 2. ID search
        c.js("document.querySelector('#idq').value = '91-25'; document.querySelector('#idgo').click(); true")
        check("search by plot ID 91-25 (active)", c.wait(f"document.querySelector('#id_out li[data-key=\"{KEY}\"]')?.dataset.active === '1'", what="ID result")
              and c.wait(f"APP.markers.get('{KEY}').isPopupOpen() && !!document.querySelector('.leaflet-popup-content table')", 60, "91-25 popup"))
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
        charts = c.js("['c_stack','c_trees','c_growth','c_mort','c_ing'].filter(id => document.getElementById(id)?.querySelector('.main-svg')).length")
        mp = c.js("PLOT.hist.microplot_moved.join(',')")
        relo = c.js("PLOT.hist.events.filter(e => e.cls === 'microplot relocation addition').length")
        check("history charts render; microplot relocation separated", charts == 5 and mp == "2006" and relo == 17, f"{charts}/5 charts; moved {mp}; {relo} relocation additions")
        c.js("document.querySelector('#tabs button[data-t=trees]').click(); true")
        ntr = c.js("document.querySelectorAll('#tab tbody tr').length")
        c.js("document.querySelector('#tabs button[data-t=cond]').click(); true")
        cond = c.js("document.querySelector('#tab').textContent")
        check("visit tabs render decoded data", ntr > 10 and "Private" in cond, f"{ntr} tree rows; conditions decoded")
        flag = c.js("[...document.querySelectorAll('#tab .flag')].length")
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
        shot = c.call("Page.captureScreenshot", format="png")["data"]
        if "--shots" in a:
            import base64
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

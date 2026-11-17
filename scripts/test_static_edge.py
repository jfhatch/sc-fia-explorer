"""Headless Edge test of the static site (local folder or the live URL).

Usage: python -I scripts/test_static_edge.py --latlon "<lat>,<lon>" (--site DIR | --url https://.../)

The location is typed into the page only: never written to disk or printed, and the test asserts no request carried it.
Checks: map loads every plot; USGS tiles answer HTTP 200; plot 91-25 via ID search and via location search; plot page
totals = 35/82/82/101/92 ft²/ac; history charts and tabs render; phone viewport (filter panel collapses, map and plot
page usable without horizontal scrolling); no CSP violations, no cookies, no requests to hosts other than the site
and basemap.nationalmap.gov.
"""
import os, sys, json, time, shutil, subprocess, tempfile, urllib.request, functools, threading, http.server
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

    def check(name, cond, detail=""):
        results.append(bool(cond))
        print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")

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
                    out.append("JS exception: " + json.dumps(e["params"]["exceptionDetails"].get("exception", {}).get("description", ""))[:200])
            return out

        # 1. map + tiles
        t0 = time.time()
        c.goto(base + "index.html")
        c.wait("document.body.dataset.ready === '1' || document.body.dataset.ready === 'error'", what="map ready")
        n_rows = c.js("APP.rows.length"); n_vis = int(c.js("document.body.dataset.visible || 0"))
        n_meta = c.js("FIA.meta.build.locations")
        check("map loads every plot location", n_rows == n_meta and n_vis == n_rows and n_rows > ("--allow-subset" in a and 100 or 1000), f"{n_rows:,} locations in {time.time() - t0:.1f}s")
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
        # 2. ID search
        c.js("document.querySelector('#idq').value = '91-25'; document.querySelector('#idgo').click(); true")
        check("search by plot ID 91-25", c.wait(f"!!document.querySelector('#id_out li[data-key=\"{KEY}\"]')", what="ID result"))
        c.js("document.querySelector('#idq').value = '809203876290487'; document.querySelector('#idgo').click(); true")
        check("search by PLOT CN (2021 visit of 91-25)", c.wait(f"!!document.querySelector('#id_out li[data-key=\"{KEY}\"]')", what="CN result"))
        # 3. location search (client-side only)
        c.events.clear()
        c.js("document.querySelector('#locbtn').click(); true")
        c.wait("!!document.querySelector('#l_lat')")
        c.js(f"document.querySelector('#l_lat').value = {json.dumps(lat_s)}; document.querySelector('#l_lon').value = {json.dumps(lon_s)};"
             "document.querySelector('#l_rad').value = '2'; document.querySelector('#l_go').click(); true")
        c.wait("!!document.querySelector('#l_list') || /No public plot/.test(document.querySelector('#l_out').textContent)")
        items = c.js("[...document.querySelectorAll('#l_list li')].map(li => [li.dataset.key, +li.dataset.dist])")
        keys = [k for k, _ in items]
        rank = keys.index(KEY) + 1 if KEY in keys else None
        check("location search finds 91-25", rank is not None, f"rank {rank} of {len(items)} within 2 mi" if rank else "")
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
        st = c.js("(() => { const s = document.querySelector('#side').getBoundingClientRect(), m = document.querySelector('#map').getBoundingClientRect();"
                  " return [s.right <= 1, m.width, m.height, document.documentElement.scrollWidth]; })()")
        c.js("document.querySelector('#filtbtn').click(); true")
        try:
            opened = c.wait("document.querySelector('#side').getBoundingClientRect().left >= 0", 10, "filter panel")
        except TimeoutError:
            opened = False
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

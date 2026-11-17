"""Headless Edge end-to-end test of the explorer UI (Chrome DevTools Protocol over a local websocket).

Usage: .venv\\Scripts\\python.exe -I scripts\\test_ui_edge.py --latlon "<lat>,<lon>" [--port 8799]

1. loads the map and checks that every plot location is loaded
2. searches plot 91-25 by ID
3. searches by location with the coordinate given on the command line: the value is typed into the page only; it is
   not written to disk, not printed, and the test asserts that no network request carried it
4. opens the plot page and checks its per-visit totals against the published 35/82/82/101/92 ft²/ac
5. requests the printable PDF summary (validated server-side against the same totals)
A throw-away Edge profile is used and deleted afterwards.
"""
import os, sys, json, time, shutil, socket, subprocess, tempfile, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import websocket
from fiasc import core, summary_pdf

KEY = "45-3-91-25"


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=60, suppress_origin=True)
        self.i = 0
        self.events = []

    def call(self, method, **params):
        self.i += 1
        mid = self.i
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == mid:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})
            if "method" in m:
                self.events.append(m)

    def js(self, expr, await_promise=True):
        r = self.call("Runtime.evaluate", expression=expr, awaitPromise=await_promise, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError("JS error: " + json.dumps(r["exceptionDetails"])[:400])
        return r["result"].get("value")

    def wait(self, expr, timeout=90, what=""):
        t0 = time.time()
        while time.time() - t0 < timeout:
            v = self.js(expr)
            if v:
                return v
            time.sleep(0.25)
        raise TimeoutError(f"timed out waiting for {what or expr}")

    def goto(self, url):
        self.call("Page.navigate", url=url)
        time.sleep(0.5)


def main():
    args = sys.argv[1:]
    if "--latlon" not in args:
        print(__doc__); return 2
    lat_s, lon_s = [x.strip() for x in args[args.index("--latlon") + 1].split(",")]
    port = int(args[args.index("--port") + 1]) if "--port" in args else free_port()
    py = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    srv = subprocess.Popen([py, "-I", os.path.join(ROOT, "app", "server.py"), str(port)], cwd=ROOT,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            urllib.request.urlopen(base + "/api/meta", timeout=2); break
        except Exception:
            time.sleep(0.5)
    prof = tempfile.mkdtemp(prefix="edge_ui_test_")
    dport = free_port()
    edge = subprocess.Popen([summary_pdf.find_edge(), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                             f"--user-data-dir={prof}", f"--remote-debugging-port={dport}", "--window-size=1400,900", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    results, ok = [], True
    try:
        for _ in range(80):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{dport}/json", timeout=2))
                page = next(t for t in tabs if t.get("type") == "page"); break
            except Exception:
                time.sleep(0.25)
        c = CDP(page["webSocketDebuggerUrl"])
        c.call("Page.enable"); c.call("Runtime.enable"); c.call("Network.enable")

        def check(name, cond, detail=""):
            nonlocal ok
            ok &= bool(cond)
            results.append(("PASS" if cond else "FAIL", name, detail))
            print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")

        # 1. map
        t0 = time.time()
        c.goto(base + "/")
        c.wait("document.body.dataset.ready === '1' || document.body.dataset.ready === 'error'", what="map ready")
        n_rows = c.js("APP.rows.length")
        n_vis = int(c.js("document.body.dataset.visible || 0"))
        n_meta = json.load(urllib.request.urlopen(base + "/api/meta"))["build"]["locations"]
        check("map loads every plot location", n_rows == n_meta and n_vis == n_rows and n_rows > 1000,
              f"{n_rows:,} locations, {n_vis:,} markers, {time.time() - t0:.1f}s")
        # 2. search by plot ID
        c.js("document.querySelector('#idq').value = '91-25'; document.querySelector('#idgo').click(); true")
        found = c.wait(f"!!document.querySelector('#id_out li[data-key=\"{KEY}\"]')", what="ID search result")
        check("search by plot ID 91-25", found, f"result {KEY}")
        # 3. search by location (client-side only)
        c.events.clear()
        c.js("document.querySelector('#locbtn').click(); true")
        c.wait("!!document.querySelector('#l_lat')")
        c.js(f"document.querySelector('#l_lat').value = {json.dumps(lat_s)}; document.querySelector('#l_lon').value = {json.dumps(lon_s)};"
             "document.querySelector('#l_rad').value = '2'; document.querySelector('#l_go').click(); true")
        c.wait("!!document.querySelector('#l_list') || /No public plot/.test(document.querySelector('#l_out').textContent)", what="location results")
        items = c.js("[...document.querySelectorAll('#l_list li')].map(li => [li.dataset.key, +li.dataset.dist])")
        keys = [k for k, _ in items]
        rank = keys.index(KEY) + 1 if KEY in keys else None
        check("search by location finds 91-25 among the nearest public locations", rank is not None,
              f"rank {rank} of {len(items)} within 2 mi, {dict(items).get(KEY, float('nan')):.2f} mi from the entered point" if rank else f"{len(items)} results")
        time.sleep(0.5)
        reqs = [e["params"]["request"]["url"] for e in c.events if e.get("method") == "Network.requestWillBeSent"]
        bodies = [e["params"]["request"].get("postData", "") for e in c.events if e.get("method") == "Network.requestWillBeSent"]
        leaked = [u for u in reqs + bodies if lat_s in u or lon_s in u or lat_s[:6] in u or lon_s[:7] in u]
        api_calls = [u for u in reqs if u.startswith(base + "/api") and not u.startswith((base + "/api/update/check", base + "/api/settings"))]
        check("location search sent nothing to the server", not leaked and not api_calls,
              f"{len(reqs)} requests during the search, {len(api_calls)} to /api, 0 contain the coordinate" if not leaked else "LEAK")
        c.js("document.querySelector('#l_clear').click(); true")
        cleared = c.js("document.querySelector('#l_lat').value === '' && document.querySelector('#l_lon').value === '' && APP.locLayer === null "
                       "&& !location.href.includes('?') && !location.hash")
        stor = c.js("localStorage.length + sessionStorage.length")
        check("'Clear and forget' wipes the point; nothing in storage or the URL", cleared and stor == 0)
        # 4. plot page totals
        c.goto(f"{base}/plot/{KEY}")
        c.wait("document.body.dataset.ready === '1' || document.body.dataset.ready === 'error'", what="plot page")
        cells = c.js("Object.fromEntries([...document.querySelectorAll('#totals tr[data-invyr]')].map(tr => [tr.dataset.invyr, +tr.querySelector('[data-ba]').dataset.ba]))")
        exp = core.REGRESSION_BA[KEY]
        got = {int(k): v for k, v in cells.items()}
        match = all(int(round(got.get(y, -1))) == v for y, v in exp.items())
        check("plot page totals match the report (35/82/82/101/92 ft²/ac)", match,
              " / ".join(f"{y}: {got.get(y, float('nan')):.1f}" for y in exp))
        charts = c.js("['c_stack','c_trees','c_growth','c_mort','c_ing'].filter(id => document.getElementById(id) && document.getElementById(id).querySelector('.main-svg')).length")
        check("history charts render", charts == 5, f"{charts}/5 charts")
        tabs = c.js("[...document.querySelectorAll('#tabs button')].filter(b => !b.disabled).length")
        c.js("document.querySelector('#tabs button[data-t=trees]').click(); true")
        ntr = c.js("document.querySelectorAll('#tab tbody tr').length")
        check("visit tabs work", tabs >= 5 and ntr > 10, f"{tabs} tabs with data; {ntr} tree rows in the 2021 tab")
        # 5. PDF summary
        st = c.js(f"fetch('/api/plot/{KEY}/summary.pdf').then(r => r.status + ' ' + r.headers.get('content-type') + ' ' + r.headers.get('content-length'))")
        check("printable PDF summary (validated server-side)", st.startswith("200 application/pdf"), st)
        c.ws.close()
    finally:
        edge.terminate(); srv.terminate()
        try:
            edge.wait(10)
        except Exception:
            edge.kill()
        time.sleep(1)
        shutil.rmtree(prof, ignore_errors=True)
    print(f"\n{'ALL PASSED' if ok else 'FAILED'}: {sum(r[0] == 'PASS' for r in results)}/{len(results)} checks; temporary Edge profile deleted")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

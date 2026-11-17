"""End-to-end test of the one-click update flow, run in a sandbox copy of the data folder (the live build is untouched).

Usage: .venv\\Scripts\\python.exe -I scripts\\test_update_e2e.py [--keep]

A. Simulated change, real DataMart: the sandbox's recorded headers for SC_PLOT are modified; "Check for updates"
   (HEAD requests to apps.fs.usda.gov) must report exactly that table.
B. Import against a local copy: a mock DataMart on 127.0.0.1 serves the raw CSVs of the live build with their recorded
   headers, except a modified SC_PLOT (a 2026 remeasurement of 45-3-91-25, a newly installed plot, one edited record),
   SC_SEEDLING (a species new to SC), SC_INVASIVE_SUBPLOT_SPP (a new invasive) and SC_SITETREE (2 % of rows dropped).
   Through the app's HTTP API: check -> import (resumes a pre-seeded partial SC_PLOT download with HTTP Range) ->
   validation -> test suite -> needs confirmation (row drop) -> confirm -> atomic switch -> "What's new" -> single-job
   lock and cancel -> local-only guards -> rollback.
C. Restore the real manifest headers and confirm the check against the real DataMart reports no changes.
"""
import os, sys, json, time, shutil, socket, sqlite3, subprocess, threading, urllib.request, urllib.error, hashlib, csv
import http.server
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.path.join(ROOT, "_e2e")
os.environ["FIASC_DATA"] = os.path.join(SB, "data")          # must be set before importing fiasc
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import pandas as pd

REAL_DATA = os.path.join(ROOT, "data")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((bool(cond), name, detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}", flush=True)
    return bool(cond)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


# ---------------------------------------------------------------- mock DataMart (HEAD, GET, Range)
class Mock(http.server.ThreadingHTTPServer):
    files = {}          # fname -> {path, etag, last_modified}
    ranges = []


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _meta(self):
        f = self.path.rsplit("/", 1)[-1]
        return f, self.server.files.get(f)

    def do_HEAD(self):
        f, m = self._meta()
        if not m:
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Length", str(os.path.getsize(m["path"])))
        self.send_header("Last-Modified", m["last_modified"]); self.send_header("ETag", m["etag"]); self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

    def do_GET(self):
        f, m = self._meta()
        if not m:
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        size = os.path.getsize(m["path"])
        start = 0
        rg = self.headers.get("Range")
        if rg and (self.headers.get("If-Range") in (None, m["etag"])):
            start = int(rg.split("=")[1].split("-")[0])
            self.server.ranges.append((f, start))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{size - 1}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(size - start))
        self.send_header("Last-Modified", m["last_modified"]); self.send_header("ETag", m["etag"]); self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with open(m["path"], "rb") as fh:
            fh.seek(start)
            shutil.copyfileobj(fh, self.wfile, 1 << 20)


# ---------------------------------------------------------------- helpers
def http(method, url, body=None, headers=None):
    h = {"X-FIASC": "1", "Content-Type": "application/json"} if method != "GET" else {}
    h.update(headers or {})
    req = urllib.request.Request(url, method=method, data=json.dumps(body or {}).encode() if method != "GET" else None, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def poll(base, until, timeout=3600):
    t0, last = time.time(), None
    while time.time() - t0 < timeout:
        _, j = http("GET", base + "/api/update/job")
        msg = f"{j.get('state')} {j.get('stage')} {j.get('pct')}%"
        if msg != last:
            print("    job:", msg, "-", (j.get("message") or "")[:100], flush=True)
            last = msg
        if j.get("state") in until:
            return j
        time.sleep(2)
    raise TimeoutError("job did not finish")


def main():
    keep = "--keep" in sys.argv
    t_start = time.time()
    real_ptr = json.load(open(os.path.join(REAL_DATA, "current.json")))
    live_name = real_ptr["current"]
    real_db = os.path.join(REAL_DATA, "builds", live_name)
    real_digest = hashlib.sha256(json.dumps(sqlite3.connect(f"file:{real_db}?mode=ro", uri=True)
                                            .execute("SELECT * FROM manifest ORDER BY table_name").fetchall()).encode()).hexdigest()
    # ---------------------------------------------------------------- sandbox
    if os.path.exists(SB):
        shutil.rmtree(SB)
    D = os.environ["FIASC_DATA"]
    os.makedirs(os.path.join(D, "builds"))
    print(f"sandbox {SB}: copying live build {live_name} ...", flush=True)
    shutil.copy2(real_db, os.path.join(D, "builds", live_name))
    for t in os.listdir(os.path.join(REAL_DATA, "raw")):
        os.makedirs(os.path.join(D, "raw", t))
        for fn in os.listdir(os.path.join(REAL_DATA, "raw", t)):
            src, dst = os.path.join(REAL_DATA, "raw", t, fn), os.path.join(D, "raw", t, fn)
            (shutil.copy2 if fn.endswith(".json") else os.link)(src, dst)        # CSVs hard-linked (read-only use)
    json.dump({"current": live_name, "history": [live_name]}, open(os.path.join(D, "current.json"), "w"))
    from fiasc import store, updater, datamart
    sb_db = os.path.join(D, "builds", live_name)
    con = sqlite3.connect(sb_db)
    real_plot = dict(zip(["last_modified", "etag", "content_length"],
                         con.execute("SELECT last_modified, etag, content_length FROM manifest WHERE table_name='PLOT'").fetchone()))
    json.dump(real_plot, open(os.path.join(SB, "real_manifest_PLOT.json"), "w"))
    # ---------------------------------------------------------------- A. simulated change (recorded headers modified), real DataMart
    con.execute("UPDATE manifest SET last_modified='Thu, 01 Jan 2026 00:00:00 GMT', etag='\"e2e-simulated\"', content_length=content_length-1 "
                "WHERE table_name='PLOT'")
    con.commit(); con.close()
    r = updater.check(base_url="https://apps.fs.usda.gov/fia/datamart/CSV/")
    check("A. check against the real DataMart flags only the simulated table", r["changed"] == ["PLOT"],
          f"changed={r['changed']}; {len(r['tables'])} tables checked by HEAD")
    # ---------------------------------------------------------------- B. local copy with real changes
    mock_dir = os.path.join(SB, "mock")
    os.makedirs(mock_dir)
    man = pd.read_sql_query("SELECT * FROM manifest", sqlite3.connect(f"file:{sb_db}?mode=ro", uri=True))
    files = {}
    for rr in man.itertuples():
        files[rr.file] = {"path": os.path.join(REAL_DATA, rr.raw_path), "etag": rr.etag, "last_modified": rr.last_modified}
    raw = lambda t: os.path.join(REAL_DATA, man.set_index("table_name").loc[t, "raw_path"])
    # SC_PLOT: 2026 remeasurement of 45-3-91-25, a newly installed plot, an edited record
    pl = pd.read_csv(raw("PLOT"), dtype=str, keep_default_na=False)
    p25 = pl[(pl.STATECD == "45") & (pl.COUNTYCD == "91") & (pl.PLOT == "25")].sort_values("INVYR")
    last = p25.iloc[-1].copy()
    NEWCN, INSTCN = "990000000000001", "990000000000002"
    nv = last.copy(); nv["CN"], nv["PREV_PLT_CN"], nv["INVYR"], nv["MEASYEAR"], nv["MEASMON"], nv["MEASDAY"], nv["REMPER"], nv["KINDCD"] = \
        NEWCN, last.CN, "2026", "2026", "3", "18", "4.2", "2"
    inst = last.copy(); inst["CN"], inst["PREV_PLT_CN"], inst["INVYR"], inst["PLOT"], inst["MEASYEAR"], inst["MEASMON"], inst["MEASDAY"], inst["KINDCD"], inst["REMPER"] = \
        INSTCN, "", "2026", "999001", "2026", "4", "2", "1", ""
    inst["LAT"], inst["LON"] = str(round(float(last.LAT) + 0.05, 6)), str(round(float(last.LON) - 0.05, 6))
    edit_idx = pl[(pl.COUNTYCD == "45") & (pl.KINDCD == "2")].index[0]
    edit_key = "-".join(pl.loc[edit_idx, ["STATECD", "UNITCD", "COUNTYCD", "PLOT"]].astype(int).astype(str))
    pl.loc[edit_idx, "ELEV"] = str(int(float(pl.loc[edit_idx, "ELEV"] or 0)) + 7)
    pl = pd.concat([pl, nv.to_frame().T, inst.to_frame().T])
    pl.to_csv(os.path.join(mock_dir, "SC_PLOT.csv"), index=False)
    # SC_SEEDLING: a species never recorded in SC (Douglas-fir, SPCD 202) on the 2026 visit
    sd = pd.read_csv(raw("SEEDLING"), dtype=str, keep_default_na=False)
    assert "202" not in set(sd.SPCD)
    s0 = sd.iloc[0].copy(); s0["CN"], s0["PLT_CN"], s0["INVYR"], s0["SPCD"], s0["STATECD"], s0["COUNTYCD"], s0["PLOT"], s0["UNITCD"] = \
        "990000000000011", NEWCN, "2026", "202", "45", "91", "25", "3"
    pd.concat([sd, s0.to_frame().T]).to_csv(os.path.join(mock_dir, "SC_SEEDLING.csv"), index=False)
    # SC_INVASIVE_SUBPLOT_SPP: kudzu (PUMO) or another symbol new to SC on the 2026 visit
    iv = pd.read_csv(raw("INVASIVE_SUBPLOT_SPP"), dtype=str, keep_default_na=False)
    sym = next(s for s in ("PUMO", "PUMOL", "IMCY", "ARFO", "CEOR7") if s not in set(iv.VEG_SPCD))
    i0 = iv.iloc[0].copy(); i0["CN"], i0["PLT_CN"], i0["INVYR"], i0["VEG_SPCD"], i0["SUBP"], i0["COVER_PCT"], i0["COUNTYCD"], i0["PLOT"], i0["UNITCD"] = \
        "990000000000021", NEWCN, "2026", sym, "1", "3", "91", "25", "3"
    pd.concat([iv, i0.to_frame().T]).to_csv(os.path.join(mock_dir, "SC_INVASIVE_SUBPLOT_SPP.csv"), index=False)
    # SC_SITETREE: drop 2 % of rows (must require confirmation)
    st = pd.read_csv(raw("SITETREE"), dtype=str, keep_default_na=False)
    st.iloc[: int(len(st) * 0.98)].to_csv(os.path.join(mock_dir, "SC_SITETREE.csv"), index=False)
    for fn in ("SC_PLOT.csv", "SC_SEEDLING.csv", "SC_INVASIVE_SUBPLOT_SPP.csv", "SC_SITETREE.csv"):
        files[fn] = {"path": os.path.join(mock_dir, fn), "etag": f'"e2e-{fn}"', "last_modified": "Mon, 16 Nov 2026 12:00:00 GMT"}
    mport = free_port()
    mock = Mock(("127.0.0.1", mport), H)
    mock.files = files
    threading.Thread(target=mock.serve_forever, daemon=True).start()
    murl = f"http://127.0.0.1:{mport}/"
    # pre-seed a partial SC_PLOT download (as if a previous import was interrupted) to exercise HTTP Range resume
    os.makedirs(os.path.join(D, "staging"), exist_ok=True)
    plot_mock = files["SC_PLOT.csv"]
    with open(plot_mock["path"], "rb") as fh:
        open(os.path.join(D, "staging", "SC_PLOT.csv.part"), "wb").write(fh.read(3_000_000))
    open(os.path.join(D, "staging", "SC_PLOT.csv.part.meta"), "w").write(f'{plot_mock["etag"]}|{plot_mock["last_modified"]}|{os.path.getsize(plot_mock["path"])}')
    # app server on the sandbox, reading from the mock DataMart
    port = free_port()
    env = dict(os.environ, FIASC_DATA=D, FIASC_BASE_URL=murl)
    py = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    srv = subprocess.Popen([py, "-I", os.path.join(ROOT, "app", "server.py"), str(port)], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=open(os.path.join(SB, "server_stderr.txt"), "w"))
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(base + "/api/meta", timeout=2); break
            except Exception:
                time.sleep(0.5)
        # local-only guards
        c1, _ = http("POST", base + "/api/update/check", headers={"X-FIASC": ""})
        c2, _ = http("POST", base + "/api/update/check", headers={"Origin": "http://evil.example"})
        c3, _ = http("GET", base + "/api/meta", headers={"Host": "evil.example"})
        check("B. update endpoints refuse requests without the app header, cross-origin requests and foreign Host names",
              (c1, c2, c3) == (403, 403, 403), f"HTTP {c1}/{c2}/{c3}")
        _, s0 = http("GET", base + "/api/data/status")
        _, r = http("POST", base + "/api/update/check")
        check("B. check against the local copy reports the changed tables", sorted(r["changed"]) == ["INVASIVE_SUBPLOT_SPP", "PLOT", "SEEDLING", "SITETREE"],
              f"changed={sorted(r['changed'])}")
        t0 = time.time()
        code, j = http("POST", base + "/api/update/import", {})
        check("B. import job started", code == 200, j.get("id", ""))
        code2, _ = http("POST", base + "/api/update/import", {})
        check("B. a second import is refused while one runs", code2 == 409, f"HTTP {code2}")
        j = poll(base, ("needs_confirmation", "done", "failed", "cancelled"))
        _, s1 = http("GET", base + "/api/data/status")
        check("B. 2 % SITETREE drop stops the job for confirmation; current build still live",
              j["state"] == "needs_confirmation" and any("SITETREE" in x for x in j.get("confirm", [])) and s1["build"] == s0["build"],
              f"state={j['state']}; {j.get('confirm')}; live={s1['build']}")
        check("B. partial SC_PLOT download resumed with HTTP Range", any(f == "SC_PLOT.csv" and st_ == 3_000_000 for f, st_ in mock.ranges),
              f"range requests {mock.ranges}")
        _, jl = http("GET", base + "/api/update/job")
        log = "\n".join(jl.get("log", []))
        check("B. only changed tables were downloaded; the rest were reused", "downloaded 4 changed table(s)" in log,
              next((l for l in jl["log"] if "downloaded" in l and "changed table" in l), ""))
        check("B. validation and the full test suite passed against the new build", jl.get("tests") == "passed" and "pytest" in log,
              next((l for l in jl["log"] if "pytest:" in l), "").split("pytest:")[-1].strip())
        code, j = http("POST", base + "/api/update/confirm", {})
        j = poll(base, ("done", "failed", "cancelled"))
        _, s2 = http("GET", base + "/api/data/status")
        check("B. after confirmation the new build is live (atomic switch) and the previous build is kept",
              j["state"] == "done" and s2["build"] != s0["build"] and s0["build"] in s2["previous_builds"],
              f"live {s0['build']} -> {s2['build']}; previous {s2['previous_builds']}; import took {time.time() - t0:.0f}s")
        _, wn = http("GET", base + "/api/update/whatsnew")
        york = [x for x in wn.get("new_visits", []) if x["countycd"] == 91 and x["invyr"] == 2026]
        inst_key = "45-3-91-999001"
        ok = (wn["summary"]["new_visits"] == 2 and york and "45-3-91-25" in york[0]["keys"] and wn["installed"] == [inst_key]
              and wn["remeasured"] == ["45-3-91-25"] and any(c["key"] == edit_key and "PLOT" in c["tables"] for c in wn["changed"])
              and any(s["spcd"] == 202 and "45-3-91-25" in s["keys"] for s in wn["new_species"])
              and any(s["symbol"] == sym for s in wn["new_invasives_state"])
              and any(x["key"] == "45-3-91-25" and sym in x["symbols"] for x in wn["new_invasives_plot"])
              and {"45-3-91-25", inst_key, edit_key} <= set(wn["keys"]))
        check("B. What's new: new visits by county/INVYR, installed, remeasured, changed records, new species and invasives",
              ok, json.dumps(wn["summary"]))
        _, loc = http("GET", base + "/api/locations")
        keys = {row[0] for row in loc["rows"]}
        check("B. map data from the new build includes the new plot; the new-data filter keys resolve to map markers",
              inst_key in keys and set(wn["keys"]) <= keys, f"{len(keys):,} locations")
        _, pg = http("GET", base + "/api/plot/45-3-91-25")
        check("B. plot page of 45-3-91-25 shows the 2026 visit; 2000-2021 totals unchanged",
              [v["invyr"] for v in pg["visits"]][-1] == 2026 and [round(v["ba"]) for v in pg["visits"][:5]] == [35, 82, 82, 101, 92],
              " / ".join(f"{v['invyr']}: {v['ba']}" for v in pg["visits"]))
        # single job + cancel: start an import that has nothing to download and cancel it
        code, j = http("POST", base + "/api/update/import", {})
        time.sleep(4)
        code, jc = http("POST", base + "/api/update/cancel", {})
        j = poll(base, ("cancelled", "failed", "done"))
        _, s3 = http("GET", base + "/api/data/status")
        check("B. cancel stops a running import and keeps the current build", j["state"] == "cancelled" and s3["build"] == s2["build"],
              f"state={j['state']}; live={s3['build']}")
        # rollback
        code, rb = http("POST", base + "/api/update/rollback", {})
        _, s4 = http("GET", base + "/api/data/status")
        _, pg = http("GET", base + "/api/plot/45-3-91-25")
        check("B. Restore previous switches back to the original build", code == 200 and s4["build"] == s0["build"]
              and [v["invyr"] for v in pg["visits"]][-1] == 2021, f"live={s4['build']} (rolled back from {rb.get('rolled_back_from')})")
    finally:
        srv.terminate()
        mock.shutdown()
        time.sleep(1)
    # ---------------------------------------------------------------- C. restore the real manifest headers
    con = sqlite3.connect(os.path.join(D, "builds", live_name))
    con.execute("UPDATE manifest SET last_modified=?, etag=?, content_length=? WHERE table_name='PLOT'",
                (real_plot["last_modified"], real_plot["etag"], real_plot["content_length"]))
    con.commit(); con.close()
    r = updater.check(base_url="https://apps.fs.usda.gov/fia/datamart/CSV/")
    check("C. real manifest restored: the check against the real DataMart reports no changes", r["changed"] == [], f"changed={r['changed']}")
    now_digest = hashlib.sha256(json.dumps(sqlite3.connect(f"file:{real_db}?mode=ro", uri=True)
                                           .execute("SELECT * FROM manifest ORDER BY table_name").fetchall()).encode()).hexdigest()
    check("C. the real live build and its manifest were never modified",
          now_digest == real_digest and json.load(open(os.path.join(REAL_DATA, "current.json")))["current"] == live_name)
    if not keep:
        shutil.rmtree(SB, ignore_errors=True)
    n_ok = sum(r[0] for r in RESULTS)
    print(f"\n{'ALL PASSED' if n_ok == len(RESULTS) else 'FAILED'}: {n_ok}/{len(RESULTS)} checks in {time.time() - t_start:.0f}s"
          + ("" if keep else "; sandbox removed"))
    return 0 if n_ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())

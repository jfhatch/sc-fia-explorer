"""FIA SC plot explorer: FastAPI + SQLite backend, served on 127.0.0.1 only.

Privacy: the app never receives a user-entered location (location search runs in the browser over the public plot
coordinates already loaded by the map); there is no notes/annotation feature; the access log is disabled and the app
logs no request parameters.
"""
import os, sys, io, json, math, time, threading, subprocess, hashlib
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import pandas as pd
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fiasc import store, core, plotdata, updater, summary_pdf, datamart

STATIC = os.path.join(ROOT, "app", "static")


def _clean(o):
    """JSON-safe: NaN/inf -> null, numpy scalars -> Python numbers."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        try:
            o = o.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if o is pd.NA or o is pd.NaT:
        return None
    return o


class SafeJSON(JSONResponse):
    def render(self, content):
        return json.dumps(_clean(content), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


app = FastAPI(title="FIA SC plot explorer", docs_url=None, redoc_url=None, openapi_url=None, default_response_class=SafeJSON)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
LOCAL = {"127.0.0.1", "::1"}
_lock = threading.Lock()
_pdf_lock = threading.Lock()
_cache = {}


@app.middleware("http")
async def local_only(request: Request, call_next):
    host = request.client.host if request.client else ""
    if host not in LOCAL:
        return PlainTextResponse("local access only", status_code=403)
    hh = (request.headers.get("host") or "").split(":")[0]
    if hh not in ("127.0.0.1", "localhost", "[::1]"):            # DNS-rebinding guard
        return PlainTextResponse("bad host", status_code=403)
    p = request.url.path
    if request.method != "GET" and (p.startswith("/api/update") or p.startswith("/api/settings")):
        # state-changing endpoints: loopback client + custom header (forces a CORS preflight, which is never allowed)
        if request.headers.get("x-fiasc") != "1":
            return PlainTextResponse("missing X-FIASC header", status_code=403)
        origin = request.headers.get("origin")
        if origin and origin.split("//")[-1].split(":")[0] not in ("127.0.0.1", "localhost"):
            return PlainTextResponse("cross-origin request refused", status_code=403)
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store" if p.startswith("/api") else "max-age=300"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


def db():
    """(connection, Ref) for the live build; reopened when the pointer changes (atomic switch / rollback)."""
    path = store.current_db()
    if not path or not os.path.exists(path):
        raise HTTPException(503, "no database build yet: run scripts/build_db.py")
    with _lock:
        c = _cache.get("db")
        if not c or c[0] != path:
            con = store.connect_ro(path)
            _cache["db"] = (path, con, core.Ref(con))
            _cache.pop("locations", None)
            _cache.pop("meta", None)
        return _cache["db"][1], _cache["db"][2]


def build_info():
    con, _ = db()
    return {k: json.loads(v) for k, v in con.execute("SELECT key, value FROM build_info").fetchall()}


# ================================================================ pages
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/plot/{key}")
def plot_page(key: str):
    return FileResponse(os.path.join(STATIC, "plot.html"))


# ================================================================ map data
GROUP_EXTRA = {-1: ("Nonforest / no accessible forest", "#c9c8c2"), -2: ("Nonsampled", "#6b6a66")}


@app.get("/api/meta")
def meta():
    con, ref = db()
    if "meta" in _cache:
        return _cache["meta"]
    loc = pd.read_sql_query("SELECT FORTYP_GRP, FORTYPCD, OWNGRPCD, PLOT_STATUS_CD, LAST_INVYR, N_VISITS, COUNTYCD FROM plot_location", con)
    gcount = loc.FORTYP_GRP.dropna().astype(int).value_counts()
    groups = []
    for i, (g, n) in enumerate(gcount.items()):
        groups.append({"code": int(g), "name": ref.FGN.get(int(g), f"group {g}"), "n": int(n),
                       "color": core.PAL[i] if i < len(core.PAL) else core.GROUP_OTHER})
    groups.append({"code": -1, "name": GROUP_EXTRA[-1][0], "n": int(((loc.FORTYP_GRP.isna()) & (loc.PLOT_STATUS_CD != 3)).sum()), "color": GROUP_EXTRA[-1][1]})
    groups.append({"code": -2, "name": GROUP_EXTRA[-2][0], "n": int(((loc.FORTYP_GRP.isna()) & (loc.PLOT_STATUS_CD == 3)).sum()), "color": GROUP_EXTRA[-2][1]})
    ft = loc.FORTYPCD.dropna().astype(int).value_counts()
    types = [{"code": int(c), "name": ref.FTN.get(int(c), "?"), "group": ref.ftgroup(c), "n": int(n)} for c, n in ft.sort_index().items()]
    own = [{"code": int(c), "name": core.dec("COND.OWNGRPCD", int(c)).split(" = ", 1)[-1].split(" (")[0], "n": int(n)}
           for c, n in loc.OWNGRPCD.dropna().astype(int).value_counts().sort_index().items()]
    cty = [{"code": int(c), "name": n} for c, n in con.execute("SELECT COUNTYCD, NAME FROM county ORDER BY NAME")]
    bi = build_info()
    m = {"groups": groups, "types": types, "owners": own, "counties": cty,
         "last_invyr": [int(loc.LAST_INVYR.min()), int(loc.LAST_INVYR.max())], "max_visits": int(loc.N_VISITS.max()),
         "build": {k: bi.get(k) for k in ("build_name", "built_at", "fiadb_version", "locations", "visits", "latest_invyr")},
         "coord_note": "Public coordinates are fuzzed (usually within 0.5 mi, some up to 1 mi) and some private plots are swapped "
                       "within the county, so the true plot may not be the nearest."}
    _cache["meta"] = m
    return m


@app.get("/api/locations")
def locations():
    con, _ = db()
    if "locations" in _cache:
        return _cache["locations"]
    loc = pd.read_sql_query("SELECT KEY, LAT, LON, FORTYP_GRP, FORTYPCD, COUNTYCD, PLOT, OWNGRPCD, LAST_INVYR, N_VISITS, HAS_INVASIVES, DESIGNS, "
                            "PLOT_STATUS_CD, STDAGE, COORDS_DIFFER, N_PRED_CAND, LAST_DATE FROM plot_location", con)
    grp = loc.FORTYP_GRP.fillna(-1).astype(int)
    grp[(loc.FORTYP_GRP.isna()) & (loc.PLOT_STATUS_CD == 3)] = -2
    cols = ["key", "lat", "lon", "grp", "ft", "cty", "plot", "own", "last", "nv", "inv", "des", "age", "cd", "pc", "date"]
    rows = [[r.KEY, round(r.LAT, 5), round(r.LON, 5), int(g), None if pd.isna(r.FORTYPCD) else int(r.FORTYPCD), int(r.COUNTYCD), int(r.PLOT),
             None if pd.isna(r.OWNGRPCD) else int(r.OWNGRPCD), int(r.LAST_INVYR), int(r.N_VISITS), int(r.HAS_INVASIVES),
             {"annual": "a", "periodic": "p"}.get(r.DESIGNS, "ap" if "annual" in r.DESIGNS else "o"),
             None if pd.isna(r.STDAGE) else int(r.STDAGE), int(r.COORDS_DIFFER), int(r.N_PRED_CAND), r.LAST_DATE]
            for r, g in zip(loc.itertuples(), grp)]
    out = {"cols": cols, "rows": rows}
    _cache["locations"] = out
    return out


@app.get("/api/popup/{key}")
def popup(key: str):
    con, ref = db()
    v = pd.read_sql_query("SELECT v.PLT_CN, v.INVYR, v.DATE, v.DESIGN, v.ba, v.live_tpa, v.carbon, v.vol, v.FORTYPCD, v.STDAGE, v.N_INVASIVE_SPP, "
                          "s.mortality_n, s.mortality_ba_ac, s.ingrowth_n FROM visit v LEFT JOIN interval_summary s ON s.PLT_CN = v.PLT_CN "
                          "WHERE v.KEY=? ORDER BY v.DYEAR", con, params=(key,))
    if not len(v):
        raise HTTPException(404, "unknown plot")
    rows = []
    for i, r in enumerate(v.itertuples()):
        first = i == 0                      # no interval ends at the first visit
        rows.append({"invyr": int(r.INVYR), "date": r.DATE, "design": r.DESIGN, "ba": core.nz(r.ba, 1), "tpa": core.nz(r.live_tpa, 0),
                     "carbon": core.nz(r.carbon, 1), "vol": core.nz(r.vol, 0), "fortyp": ref.ftname(r.FORTYPCD) if not pd.isna(r.FORTYPCD) else "",
                     "age": core.nz(r.STDAGE, 0), "inv": int(r.N_INVASIVE_SPP or 0), "mort": None if first else (core.nz(r.mortality_n, 0) or 0),
                     "mort_ba": None if first else (core.nz(r.mortality_ba_ac, 1) or 0), "ing": None if first else (core.nz(r.ingrowth_n, 0) or 0)})
    return {"key": key, "visits": rows}


# ================================================================ search
@app.get("/api/search/id")
def search_id(q: str = Query(..., max_length=60)):
    con, _ = db()
    keys = plotdata.resolve_id(con, q)
    if not keys:
        return {"results": []}
    ph = ",".join("?" * len(keys))
    df = pd.read_sql_query(f"SELECT KEY, COUNTYCD, PLOT, LAT, LON, N_VISITS, LAST_DATE, DESIGNS FROM plot_location WHERE KEY IN ({ph})", con, params=keys)
    return {"results": plotdata.jsonable(df)}


@app.get("/api/search/attr")
def search_attr(county: int = None, grp: int = None, fortyp: int = None, own: int = None, age_min: float = None, age_max: float = None,
                design: str = None, inv: int = None, last_min: int = None, last_max: int = None, visits_min: int = None, limit: int = 2000):
    con, ref = db()
    w, p = [], []
    for col, val in (("COUNTYCD", county), ("FORTYP_GRP", grp), ("FORTYPCD", fortyp), ("OWNGRPCD", own), ("HAS_INVASIVES", inv)):
        if val is not None:
            w.append(f"{col} = ?"); p.append(val)
    if age_min is not None:
        w.append("STDAGE >= ?"); p.append(age_min)
    if age_max is not None:
        w.append("STDAGE <= ?"); p.append(age_max)
    if last_min is not None:
        w.append("LAST_INVYR >= ?"); p.append(last_min)
    if last_max is not None:
        w.append("LAST_INVYR <= ?"); p.append(last_max)
    if visits_min is not None:
        w.append("N_VISITS >= ?"); p.append(visits_min)
    if design in ("annual", "periodic"):
        w.append("DESIGNS LIKE ?"); p.append(f"%{design}%")
    sql = ("SELECT KEY, COUNTYCD, PLOT, FORTYPCD, STDAGE, OWNGRPCD, LAST_INVYR, LAST_DATE, N_VISITS, BA FROM plot_location"
           + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY COUNTYCD, PLOT LIMIT ?")
    df = pd.read_sql_query(sql, con, params=p + [min(limit, 5000)])
    cn = dict(con.execute("SELECT COUNTYCD, NAME FROM county").fetchall())
    df["county"] = df.COUNTYCD.map(cn)
    df["fortyp"] = df.FORTYPCD.map(lambda c: ref.ftname(c) if not pd.isna(c) else "")
    return {"n": len(df), "results": plotdata.jsonable(df)}


# ================================================================ plot page
@app.get("/api/plot/{key}")
def plot_header(key: str):
    con, ref = db()
    h = plotdata.header(con, ref, key)
    if not h:
        raise HTTPException(404, "unknown plot key")
    return h


@app.get("/api/plot/{key}/visit/{plt_cn}")
def plot_visit(key: str, plt_cn: str):
    con, ref = db()
    d = plotdata.visit_detail(con, ref, key, plt_cn)
    if not d:
        raise HTTPException(404, "unknown visit")
    return d


@app.get("/api/plot/{key}/history")
def plot_history(key: str):
    con, ref = db()
    h = plotdata.history(con, ref, key)
    if not h:
        raise HTTPException(404, "unknown plot key")
    return h


@app.get("/api/plot/{key}/export.csv")
def plot_export(key: str, what: str = "trees"):
    con, ref = db()
    df = plotdata.export_rows(con, ref, key) if what == "trees" else plotdata.export_visits(con, ref, key)
    if df is None:
        raise HTTPException(404, "unknown plot key")
    b = df.to_csv(index=False).encode("utf-8-sig")
    return Response(b, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="fia_{key}_{what}.csv"'})


@app.get("/api/plot/{key}/summary.pdf")
def plot_pdf(key: str):
    con, ref = db()
    if not con.execute("SELECT 1 FROM plot_location WHERE KEY=?", (key,)).fetchone():
        raise HTTPException(404, "unknown plot key")
    build = os.path.basename(store.current_db())[:-7]
    d = os.path.join(store.DATA, "cache", "pdf", build)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f"{key}.pdf")
    if not os.path.exists(out):
        try:
            with _pdf_lock:
                if not os.path.exists(out):
                    summary_pdf.build_pdf(store.connect_ro(), ref, key, out)
        except summary_pdf.PdfError as e:
            raise HTTPException(500, f"PDF validation failed: {e}")
    return FileResponse(out, media_type="application/pdf", filename=f"fia_{key}_summary.pdf")


# ================================================================ data panel + updates
@app.get("/api/data/status")
def data_status():
    con, _ = db()
    bi = build_info()
    man = pd.read_sql_query("SELECT table_name, file, url, last_modified, etag, content_length, sha256, rows, columns, max_modified_date, "
                            "downloaded_at, load_s, download_s FROM manifest ORDER BY table_name", con)
    p = store.pointer()
    prev = store.previous_builds()
    job = updater.active_job()
    wn = bi.get("whats_new") or {}
    return {"build": bi.get("build_name"), "built_at": bi.get("built_at"), "fiadb_version": bi.get("fiadb_version"),
            "locations": bi.get("locations"), "visits": bi.get("visits"), "latest_invyr": bi.get("latest_invyr"),
            "db_mb": round(os.path.getsize(store.current_db()) / 2 ** 20, 1), "timings": bi.get("timings"),
            "tables": plotdata.jsonable(man), "missing_tables": bi.get("missing_tables"), "validation": bi.get("validation"),
            "tests": bi.get("tests"), "previous_builds": prev, "switched_at": p.get("switched_at"),
            "rolled_back_from": p.get("rolled_back_from"), "last_check": updater.last_check(), "settings": store.settings(),
            "active_job": updater.read_state(job["dir"]) if job else None,
            "whats_new_summary": wn.get("summary"), "whats_new_compared_to": wn.get("compared_to")}


@app.post("/api/update/check")
def update_check():
    try:
        return updater.check()
    except Exception as e:
        raise HTTPException(502, f"update check failed: {e}")


@app.get("/api/update/last_check")
def update_last_check():
    return updater.last_check() or {}


@app.post("/api/update/import")
async def update_import(request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    if updater.active_job():
        raise HTTPException(409, "an update job is already running")
    d = updater.acquire("import")
    args = [sys.executable, "-I", os.path.join(ROOT, "scripts", "update_job.py"), "import", d]
    if body.get("accept_row_drops"):
        args.append("--accept-row-drops")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    pr = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=open(os.path.join(d, "stderr.txt"), "w"), creationflags=flags)
    st = updater.read_state(d)
    if st.get("state") == "queued" and not st.get("pid"):   # the job records its own pid once it starts; never overwrite its state
        st["pid"] = pr.pid
        updater.write_state(d, st)
    return st


def _job_dir(jid=None):
    a = updater.active_job()
    if jid:
        d = os.path.join(store.JOBS, os.path.basename(jid))
        if not os.path.isdir(d):
            raise HTTPException(404, "unknown job")
        return d
    if a:
        return a["dir"]
    jobs = sorted(os.listdir(store.JOBS)) if os.path.isdir(store.JOBS) else []
    jobs = [j for j in jobs if os.path.isdir(os.path.join(store.JOBS, j))]
    if not jobs:
        raise HTTPException(404, "no update job yet")
    return os.path.join(store.JOBS, jobs[-1])


@app.get("/api/update/job")
def update_job(id: str = None, log_from: int = 0):
    d = _job_dir(id)
    st = updater.read_state(d)
    lp = os.path.join(d, "log.txt")
    lines = open(lp, encoding="utf-8").read().splitlines() if os.path.exists(lp) else []
    st["log"] = lines[log_from:]
    st["log_total"] = len(lines)
    return st


@app.post("/api/update/cancel")
def update_cancel():
    a = updater.active_job()
    if not a:
        raise HTTPException(409, "no running job")
    return updater.cancel(a["dir"])


@app.post("/api/update/confirm")
def update_confirm():
    a = updater.active_job()
    if not a:
        raise HTTPException(409, "no job waiting for confirmation")
    st = updater.confirm(a["dir"])
    _cache.clear()
    return st


@app.post("/api/update/rollback")
def update_rollback():
    try:
        p = updater.rollback()
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    _cache.clear()
    return p


@app.get("/api/update/whatsnew")
def whatsnew():
    bi = build_info()
    return bi.get("whats_new") or {"summary": None, "keys": []}


@app.get("/api/settings")
def get_settings():
    return store.settings()


@app.post("/api/settings")
async def set_settings(request: Request):
    body = await request.json()
    s = store.settings()
    if "check_on_startup" in body:
        s["check_on_startup"] = bool(body["check_on_startup"])
    store.save_settings(s)
    return s


if __name__ == "__main__":
    import uvicorn
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8742
    # bound to loopback only; no access log, so request URLs and parameters are never logged
    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")

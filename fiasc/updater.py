"""Update workflow shared by the app (background job) and scripts/update.ps1.

check()     HEAD every table on the DataMart and compare Last-Modified / Content-Length / ETag with the live build's
            manifest; also compares REF_FIADB_VERSION (the FIADB load/version history). Downloads nothing
            (except the 4 KB REF_FIADB_VERSION file when its headers changed, to name the new version).
run_import(job) download changed tables (resumable) -> new build from scratch -> validation -> test suite ->
            atomic switch, or stop with the reason. Row-count drops > 1 % stop at 'needs_confirmation'.
confirm(job) continue a job waiting for confirmation. rollback() restore the previous build.
Only one job runs at a time (data/jobs/active.json lock).
"""
import os, sys, json, time, sqlite3, datetime, traceback, io, csv, urllib.request
import pandas as pd
from . import store, datamart, fetch, build, testrun

LOCK = lambda: os.path.join(store.JOBS, "active.json")
LAST_CHECK = lambda: os.path.join(store.DATA, "last_check.json")
STAGES = [("download", 0.30), ("load", 0.40), ("metrics", 0.12), ("validate", 0.08), ("tests", 0.08), ("switch", 0.02)]


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def live_manifest():
    db = store.current_db()
    if not db or not os.path.exists(db):
        return {}, None
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        df = pd.read_sql_query("SELECT * FROM manifest", con)
        bi = dict(con.execute("SELECT key, value FROM build_info").fetchall())
    finally:
        con.close()
    recs = {r["table_name"]: r for r in df.astype(object).where(df.notna(), None).to_dict(orient="records")}
    return recs, {k: json.loads(v) for k, v in bi.items()}


# ================================================================ check
def check(base_url=None, log=lambda *a: None):
    base = base_url or datamart.BASE_URL
    recs, bi = live_manifest()
    rows, changed = [], []
    for t, fname in datamart.files():
        h = datamart.head(base + fname)
        rec = recs.get(t)
        if h["status"] == 404:
            st = "missing on DataMart" if rec else "not on DataMart"
            diff = ["removed"] if rec else []
        elif h["status"] != 200:
            st, diff = f"HTTP {h['status']}", []
        elif not rec:
            st, diff = "new table", ["new"]
        else:
            diff = datamart.changed(rec, h)
            st = "changed" if diff else "unchanged"
        if diff and h["status"] in (200, 404):
            changed.append(t)
        rows.append({"table": t, "file": fname, "status": st, "fields": diff,
                     "recorded": {k: rec.get(k) for k in ("last_modified", "content_length", "etag")} if rec else None,
                     "now": {k: h.get(k) for k in ("last_modified", "content_length", "etag")}})
        log(f"{fname}: {st}{' (' + ', '.join(diff) + ')' if diff else ''}")
    fv = {"recorded": (bi or {}).get("fiadb_version"), "now": None}
    if "REF_FIADB_VERSION" in changed:
        try:
            req = urllib.request.Request(base + "REF_FIADB_VERSION.csv", headers={"User-Agent": datamart.UA})
            txt = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
            vs = sorted(csv.DictReader(io.StringIO(txt)), key=lambda r: r.get("CREATED_DATE") or "")
            if vs:
                fv["now"] = {"version": vs[-1]["VERSION"], "descr": vs[-1]["DESCR"], "created": vs[-1]["CREATED_DATE"]}
        except Exception as e:
            fv["now"] = {"error": str(e)}
    else:
        fv["now"] = fv["recorded"]
    res = {"checked_at": now(), "base_url": base, "live_build": os.path.basename(store.current_db() or ""), "tables": rows,
           "changed": changed, "any_changed": bool(changed), "fiadb_version": fv}
    store.ensure()
    json.dump(res, open(LAST_CHECK(), "w"), indent=1)
    return res


def last_check():
    try:
        return json.load(open(LAST_CHECK()))
    except (OSError, ValueError):
        return None


# ================================================================ job bookkeeping
def _pid_alive(pid):
    if not pid:
        return False
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259                                            # STILL_ACTIVE
    except AttributeError:
        try:
            os.kill(int(pid), 0)
            return True
        except OSError:
            return False


def active_job():
    a = None
    for i in range(20):
        try:
            with open(LOCK()) as f:
                a = json.load(f)
            break
        except FileNotFoundError:
            return None
        except (PermissionError, ValueError):
            time.sleep(0.05)
    if not a:
        return None
    st = read_state(a["dir"])
    young = (datetime.datetime.now() - datetime.datetime.fromisoformat(st.get("started_at", now()))).total_seconds() < 120
    pid = st.get("pid") or a.get("pid")
    if (st.get("state") == "running" or (st.get("state") == "queued" and not young)) and not _pid_alive(pid):
        st.update(state="failed", message="job process ended unexpectedly", finished_at=now())
        write_state(a["dir"], st)
    if st.get("state") not in ("running", "queued", "needs_confirmation"):
        return None
    return a


def acquire(kind, pid=None):
    """Create a job directory and take the single-job lock. Raises RuntimeError if a job is active."""
    store.ensure()
    if active_job():
        raise RuntimeError("another update job is already running")
    jid = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{kind}"
    d = os.path.join(store.JOBS, jid)
    os.makedirs(d, exist_ok=True)
    write_state(d, {"id": jid, "kind": kind, "state": "queued", "stage": None, "pct": 0, "message": "", "started_at": now(), "pid": pid})
    tmp = LOCK() + f".{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump({"id": jid, "dir": d, "pid": pid}, f)
    store.replace_retry(tmp, LOCK())
    return d


def release(d):
    try:
        a = json.load(open(LOCK()))
        if a["dir"] == d:
            os.remove(LOCK())
    except (OSError, ValueError):
        pass


def read_state(d):
    p = os.path.join(d, "state.json")
    for i in range(20):
        try:
            with open(p) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except (PermissionError, ValueError):
            time.sleep(0.05)
    return {}


def write_state(d, st):
    p = os.path.join(d, "state.json")
    tmp = p + f".{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=1, default=str)
    store.replace_retry(tmp, p)


class Job:
    def __init__(self, d, echo=False):
        self.d = d
        self.st = read_state(d)
        self.echo = echo
        self.logf = open(os.path.join(d, "log.txt"), "a", encoding="utf-8")

    def log(self, msg):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        self.logf.write(line + "\n"); self.logf.flush()
        if self.echo:
            print(line, flush=True)

    def set(self, **kw):
        self.st.update(kw)
        write_state(self.d, self.st)

    def stage(self, name, frac=0.0, message=""):
        t = time.time()
        if name == self.st.get("stage") and t - getattr(self, "_last", 0) < 0.5:
            return                                  # at most two progress writes a second within a stage
        self._last = t
        base = 0.0
        for s, w in STAGES:
            if s == name:
                pct = 100 * (base + w * max(0.0, min(1.0, frac)))
                break
            base += w
        else:
            pct = self.st.get("pct", 0)
        self.set(stage=name, pct=round(pct, 1), message=message)

    def cancelled(self):
        return os.path.exists(os.path.join(self.d, "cancel"))


# ================================================================ import
def run_import(d, accept_row_drops=False, base_url=None, echo=False, only_changed=None):
    """Run in the job process. Produces data/builds/<name> and switches to it when every check passes."""
    job = Job(d, echo)
    job.set(state="running", pid=os.getpid(), started_at=now())
    try:
        base = base_url or datamart.BASE_URL
        old_db = store.current_db()
        recs, _ = live_manifest()
        job.log(f"live build: {os.path.basename(old_db) if old_db else '(none)'}; source {base}")
        job.stage("download", 0, "checking tables")

        def dprog(i, n, fname, a, b):
            job.stage("download", (i + (a / b if b else 0)) / max(n, 1), f"{fname}: {a / 2**20:,.1f} of {b / 2**20:,.1f} MB" if b > 1 else fname)
        fetched, missing = fetch.fetch(only=only_changed, reuse=recs, base_url=base, log=job.log, progress=dprog, cancel=job.cancelled)
        changed = [t for t, r in fetched.items() if not r.get("reused")]
        job.log(f"downloaded {len(changed)} changed table(s): {', '.join(changed) or 'none'}; reused {len(fetched) - len(changed)}")
        if missing:
            job.log("not on the DataMart (404): " + ", ".join(missing))
        name = store.new_build_name()
        job.set(build=name, changed_tables=changed)
        job.log(f"building {name} from scratch")

        def bprog(stage, i, n, what):
            job.stage(stage, i / max(n, 1), what)
        info = build.build(name, fetched, missing, log=job.log, progress=bprog, cancel=job.cancelled, prev_db=old_db, base_url=base)
        job.set(build_path=info["path"], timings=info["timings"], db_mb=info["db_mb"])
        v = info["validation"]
        if v["errors"]:
            raise build.BuildError("validation failed: " + "; ".join(v["errors"]))
        job.stage("tests", 0, "running test suite against the new database")
        ok, tail = testrun.run_tests(info["path"], log=job.log)
        build.set_build_info(info["path"], "tests", {"passed": ok, "tail": tail})
        if not ok:
            raise build.BuildError("test suite failed against the new database:\n" + tail)
        job.set(tests="passed")
        if v["confirm"] and not accept_row_drops:
            job.set(state="needs_confirmation", confirm=v["confirm"], pct=95,
                    message="row counts dropped by more than 1%: confirm to switch, or cancel to keep the current build")
            job.log("waiting for confirmation: " + "; ".join(v["confirm"]))
            return job.st
        return _switch(job, info["path"], old_db)
    except datamart.Cancelled:
        _cleanup_partial(job)
        job.set(state="cancelled", message="cancelled; the current build stays live", finished_at=now())
        job.log("cancelled")
        release(d)
        return job.st
    except Exception as e:
        _cleanup_partial(job)
        job.log("FAILED: " + str(e))
        job.log(traceback.format_exc())
        job.set(state="failed", message=f"{e}".splitlines()[0][:400], error=str(e), finished_at=now())
        release(d)
        return job.st


def _cleanup_partial(job):
    p = job.st.get("build_path")
    if p and p.endswith(".building") and os.path.exists(p):
        try:
            os.remove(p)
        except OSError:
            pass


def _switch(job, building_path, old_db):
    job.stage("switch", 0, "computing what's new and switching")
    final = building_path[: -len(".building")] if building_path.endswith(".building") else building_path
    wn = whats_new(building_path, old_db)              # before the rename: a failure leaves no usable-looking build behind
    build.set_build_info(building_path, "whats_new", wn)
    if building_path != final:
        os.replace(building_path, final)
    store.switch_to(os.path.basename(final))
    job.log(f"switched live build to {os.path.basename(final)}")
    job.set(state="done", pct=100, stage="switch", message=f"live build is now {os.path.basename(final)}", finished_at=now(),
            build_path=final, whats_new_summary=wn.get("summary"))
    release(job.d)
    return job.st


def confirm(d, echo=False):
    job = Job(d, echo)
    if job.st.get("state") != "needs_confirmation":
        raise RuntimeError("job is not waiting for confirmation")
    job.set(state="running")
    job.log("row-count drops confirmed by the user")
    try:
        return _switch(job, job.st["build_path"], store.current_db())
    except Exception as e:
        _cleanup_partial(job)
        job.log("FAILED: " + str(e))
        job.set(state="failed", message=str(e), finished_at=now())
        release(d)
        return job.st


def cancel(d):
    st = read_state(d)
    open(os.path.join(d, "cancel"), "w").write(now())
    if st.get("state") == "needs_confirmation":
        job = Job(d)
        _cleanup_partial(job)
        job.set(state="cancelled", message="not switched; the current build stays live", finished_at=now())
        release(d)
    return read_state(d)


def rollback():
    if active_job():
        raise RuntimeError("an update job is running")
    p = store.rollback()
    return p


# ================================================================ what's new
def whats_new(new_db, old_db):
    con = sqlite3.connect(f"file:{new_db}?mode=ro", uri=True)
    out = {"compared_to": os.path.basename(old_db) if old_db else None, "computed_at": now()}
    if not old_db or not os.path.exists(old_db):
        out.update(summary={"note": "first build: nothing to compare"}, keys=[])
        con.close()
        return out
    con.execute("ATTACH DATABASE ? AS o", (f"file:{old_db}?mode=ro",))
    q = lambda s, params=(): pd.read_sql_query(s, con, params=params)
    cty = dict(con.execute("SELECT COUNTYCD, NAME FROM county").fetchall())
    nv = q("SELECT v.KEY, v.PLT_CN, v.INVYR, v.COUNTYCD, v.DATE FROM visit v WHERE NOT EXISTS (SELECT 1 FROM o.visit x WHERE x.PLT_CN = v.PLT_CN)")
    oldkeys = {r[0] for r in con.execute("SELECT KEY FROM o.plot_location")}
    nv["new_key"] = ~nv.KEY.isin(oldkeys)
    by = nv.groupby(["COUNTYCD", "INVYR"]).agg(n=("PLT_CN", "size"), keys=("KEY", lambda s: sorted(set(s)))).reset_index()
    new_visits = [{"county": cty.get(int(r.COUNTYCD), str(r.COUNTYCD)), "countycd": int(r.COUNTYCD), "invyr": int(r.INVYR), "n": int(r.n),
                   "keys": r.keys} for r in by.itertuples()]
    installed = sorted(set(nv.loc[nv.new_key, "KEY"]))
    remeasured = sorted(set(nv.loc[~nv.new_key, "KEY"]))
    # changed records in visits present in both builds (digest of all non-audit columns per PLT_CN and table)
    ch = q("SELECT n.PLT_CN, n.tbl, n.n AS n_new, o.n AS n_old FROM plot_digest n JOIN o.plot_digest o ON o.PLT_CN = n.PLT_CN AND o.tbl = n.tbl "
           "WHERE o.digest <> n.digest "
           "UNION ALL SELECT n.PLT_CN, n.tbl, n.n, 0 FROM plot_digest n WHERE EXISTS (SELECT 1 FROM o.visit x WHERE x.PLT_CN = n.PLT_CN) "
           "AND NOT EXISTS (SELECT 1 FROM o.plot_digest o WHERE o.PLT_CN = n.PLT_CN AND o.tbl = n.tbl) "
           "UNION ALL SELECT o.PLT_CN, o.tbl, 0, o.n FROM o.plot_digest o WHERE EXISTS (SELECT 1 FROM visit x WHERE x.PLT_CN = o.PLT_CN) "
           "AND NOT EXISTS (SELECT 1 FROM plot_digest n WHERE n.PLT_CN = o.PLT_CN AND n.tbl = o.tbl)")
    kmap = dict(con.execute("SELECT PLT_CN, KEY FROM visit").fetchall())
    ch["KEY"] = ch.PLT_CN.map(kmap)
    changed = [{"key": k, "tables": sorted(set(g.tbl)), "visits": sorted(set(g.PLT_CN))} for k, g in ch.groupby("KEY")]
    removed_visits = [r[0] for r in con.execute("SELECT PLT_CN FROM o.visit x WHERE NOT EXISTS (SELECT 1 FROM visit v WHERE v.PLT_CN = x.PLT_CN)")]
    # species / invasives new to the state data, and invasives newly detected on a plot
    sp_new = q("SELECT DISTINCT SPCD FROM (SELECT SPCD FROM TREE UNION SELECT SPCD FROM SEEDLING) WHERE SPCD NOT IN "
               "(SELECT SPCD FROM o.TREE UNION SELECT SPCD FROM o.SEEDLING)")
    new_species = []
    for s in sp_new.SPCD:
        ks = [r[0] for r in con.execute("SELECT DISTINCT v.KEY FROM visit v WHERE v.PLT_CN IN (SELECT PLT_CN FROM TREE WHERE SPCD=? "
                                        "UNION SELECT PLT_CN FROM SEEDLING WHERE SPCD=?)", (int(s), int(s)))]
        nm = con.execute("SELECT COMMON_NAME FROM REF_SPECIES WHERE SPCD=?", (int(s),)).fetchone()
        new_species.append({"spcd": int(s), "name": nm[0] if nm else f"SPCD {int(s)}", "keys": ks})
    inv_new_state = q("SELECT DISTINCT VEG_SPCD FROM INVASIVE_SUBPLOT_SPP WHERE VEG_SPCD NOT IN (SELECT VEG_SPCD FROM o.INVASIVE_SUBPLOT_SPP)")
    new_inv_state = []
    for s in inv_new_state.VEG_SPCD:
        ks = [r[0] for r in con.execute("SELECT DISTINCT v.KEY FROM visit v JOIN INVASIVE_SUBPLOT_SPP i ON i.PLT_CN = v.PLT_CN WHERE i.VEG_SPCD=?", (s,))]
        nm = con.execute("SELECT COALESCE(COMMON_NAME, SCIENTIFIC_NAME) FROM REF_PLANT_DICTIONARY WHERE SYMBOL=? LIMIT 1", (s,)).fetchone()
        new_inv_state.append({"symbol": s, "name": nm[0] if nm else s, "keys": ks})
    if len(nv):
        ph = ",".join("?" * len(nv))
        inv_plot = q(f"SELECT v.KEY, i.VEG_SPCD FROM INVASIVE_SUBPLOT_SPP i JOIN visit v ON v.PLT_CN = i.PLT_CN WHERE i.PLT_CN IN ({ph})"
                     if len(nv) < 900 else "SELECT v.KEY, i.VEG_SPCD FROM INVASIVE_SUBPLOT_SPP i JOIN visit v ON v.PLT_CN = i.PLT_CN "
                     "WHERE NOT EXISTS (SELECT 1 FROM o.visit x WHERE x.PLT_CN = i.PLT_CN)", tuple(nv.PLT_CN) if len(nv) < 900 else ())
        prior = q("SELECT v.KEY, i.VEG_SPCD FROM o.INVASIVE_SUBPLOT_SPP i JOIN o.visit v ON v.PLT_CN = i.PLT_CN")
        prior_set = set(zip(prior.KEY, prior.VEG_SPCD))
        newly = inv_plot.drop_duplicates()
        newly = newly[[(k, s) not in prior_set for k, s in zip(newly.KEY, newly.VEG_SPCD)]]
        new_inv_plot = [{"key": k, "symbols": sorted(set(g.VEG_SPCD))} for k, g in newly.groupby("KEY")]
    else:
        new_inv_plot = []
    con.close()
    keys = sorted(set(installed) | set(remeasured) | {c["key"] for c in changed})
    out.update(new_visits=new_visits, installed=installed, remeasured=remeasured, changed=changed, removed_visits=removed_visits,
               new_species=new_species, new_invasives_state=new_inv_state, new_invasives_plot=new_inv_plot, keys=keys,
               summary={"new_visits": int(len(nv)), "installed": len(installed), "remeasured": len(remeasured), "changed_plots": len(changed),
                        "removed_visits": len(removed_visits), "new_species": len(new_species), "new_invasives_state": len(new_inv_state),
                        "new_invasive_detections": len(new_inv_plot), "plots_with_new_data": len(keys)})
    return out

"""Data folder layout, the live-build pointer (atomic switch), build history/retention and settings.

data/
  current.json            {"current": "<build file>", "history": [newest ... oldest]}  (replaced atomically)
  builds/fia_sc_YYYYMMDD[_n].sqlite
  raw/<TABLE>/<sha256[:16]>.csv   content-addressed source CSVs referenced by the builds' manifests
  staging/                downloads in progress (.part files resume with HTTP Range)
  jobs/<id>/              update job state, progress and log
  settings.json           {"check_on_startup": true}
"""
import os, json, sqlite3, datetime, shutil, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.abspath(os.environ.get("FIASC_DATA", os.path.join(ROOT, "data")))
BUILDS = os.path.join(DATA, "builds")
RAW = os.path.join(DATA, "raw")
STAGING = os.path.join(DATA, "staging")
JOBS = os.path.join(DATA, "jobs")
POINTER = os.path.join(DATA, "current.json")
SETTINGS = os.path.join(DATA, "settings.json")
KEEP_PREVIOUS = 2


def ensure():
    for d in (DATA, BUILDS, RAW, STAGING, JOBS):
        os.makedirs(d, exist_ok=True)


def _write_json_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    replace_retry(tmp, path)     # atomic on NTFS and POSIX


def replace_retry(tmp, path, tries=50):
    """os.replace, retried: on Windows it fails while another process has the target open (e.g. the server reading it)."""
    import time
    for i in range(tries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.05 + 0.01 * i)


def pointer():
    if not os.path.exists(POINTER):
        return {"current": None, "history": []}
    for i in range(20):
        try:
            with open(POINTER, encoding="utf-8") as f:
                return json.load(f)
        except (PermissionError, ValueError):
            import time
            time.sleep(0.05)
    with open(POINTER, encoding="utf-8") as f:
        return json.load(f)


def current_db():
    """Absolute path of the live build, or None. FIASC_DB overrides (used by the test suite)."""
    if os.environ.get("FIASC_DB"):
        return os.environ["FIASC_DB"]
    p = pointer().get("current")
    return os.path.join(BUILDS, p) if p else None


def new_build_name():
    stem = "fia_sc_" + datetime.date.today().strftime("%Y%m%d")
    name, n = stem + ".sqlite", 1
    while os.path.exists(os.path.join(BUILDS, name)) or os.path.exists(os.path.join(BUILDS, name + ".building")):
        n += 1
        name = f"{stem}_{n}.sqlite"
    return name


def switch_to(name):
    """Make build `name` live (atomic pointer replace) and prune builds beyond current + KEEP_PREVIOUS."""
    p = pointer()
    hist = [h for h in p.get("history", []) if h != name and os.path.exists(os.path.join(BUILDS, h))]
    if p.get("current") and p["current"] != name and p["current"] not in hist:
        hist.insert(0, p["current"])
    newp = {"current": name, "history": [name] + hist, "switched_at": datetime.datetime.now().isoformat(timespec="seconds")}
    _write_json_atomic(POINTER, newp)
    prune()
    return newp


def previous_builds():
    p = pointer()
    cur = p.get("current")
    return [h for h in p.get("history", []) if h != cur and os.path.exists(os.path.join(BUILDS, h))]


def rollback():
    """Switch to the most recent previous build; the build switched away from stays in history (retention allows)."""
    prev = previous_builds()
    if not prev:
        raise RuntimeError("no previous build to restore")
    p = pointer()
    target = prev[0]
    hist = [target] + [h for h in p["history"] if h != target]
    newp = {"current": target, "history": hist, "switched_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "rolled_back_from": p.get("current")}
    _write_json_atomic(POINTER, newp)
    return newp


def prune():
    """Keep the live build and the previous KEEP_PREVIOUS builds; delete older builds and raw CSVs no kept build uses."""
    p = pointer()
    keep = p.get("history", [])[: KEEP_PREVIOUS + 1]
    if p.get("current") and p["current"] not in keep:
        keep.append(p["current"])
    for f in glob.glob(os.path.join(BUILDS, "*.sqlite")):
        if os.path.basename(f) not in keep:
            try:
                os.remove(f)
            except OSError:
                pass
    if keep != p.get("history"):
        p["history"] = [h for h in p.get("history", []) if h in keep]
        _write_json_atomic(POINTER, p)
    used = set()
    for b in keep:
        try:
            con = sqlite3.connect(f"file:{os.path.join(BUILDS, b)}?mode=ro", uri=True)
            used |= {r[0] for r in con.execute("SELECT raw_path FROM manifest WHERE raw_path IS NOT NULL")}
            con.close()
        except sqlite3.Error:
            return                       # cannot read a kept build: do not delete any raw files
    for f in glob.glob(os.path.join(RAW, "*", "*.csv")):
        rel = os.path.relpath(f, DATA).replace("\\", "/")
        if rel not in used:
            for x in (f, f[:-4] + ".json"):
                try:
                    os.remove(x)
                except OSError:
                    pass


def settings():
    s = {"check_on_startup": True}
    if os.path.exists(SETTINGS):
        try:
            s.update(json.load(open(SETTINGS, encoding="utf-8")))
        except ValueError:
            pass
    return s


def save_settings(s):
    ensure()
    _write_json_atomic(SETTINGS, s)


def connect_ro(path=None):
    path = path or current_db()
    if not path or not os.path.exists(path):
        raise FileNotFoundError("no live database; run scripts/build_db.py")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    return con

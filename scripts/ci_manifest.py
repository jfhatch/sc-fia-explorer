"""DataMart manifest committed in the repo (ci/datamart_manifest.json), used by the GitHub Actions workflow.

  check [--out FILE]   HEAD every table and compare Last-Modified / Content-Length / ETag with the committed manifest.
                       Prints a reachability report; writes changed=true|false and reachable=true|false to FILE
                       (GITHUB_OUTPUT) and the current headers to ci/datamart_headers_now.json (cache key).
  write [--db FILE]    Write ci/datamart_manifest.json from the live build's manifest table (no local paths).
"""
import os, sys, json, time, socket, sqlite3
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
from fiasc import datamart, store

CI = os.path.join(ROOT, "ci")
MANIFEST = os.path.join(CI, "datamart_manifest.json")
NOW = os.path.join(CI, "datamart_headers_now.json")
FIELDS = ("last_modified", "etag", "content_length")


def arg(n):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else None


def check():
    rec = json.load(open(MANIFEST)).get("tables", {}) if os.path.exists(MANIFEST) else {}
    t0 = time.time()
    now, changed, errors = {}, [], []
    for t, fname in datamart.files():
        try:
            h = datamart.head(datamart.BASE_URL + fname, timeout=60)
        except Exception as e:                      # network-level failure: DataMart unreachable from here
            errors.append(f"{fname}: {type(e).__name__}: {e}")
            continue
        now[t] = {k: h.get(k) for k in FIELDS} | {"status": h["status"]}
        if h["status"] == 404:
            if t in rec:
                changed.append(t)
            continue
        if h["status"] != 200:
            errors.append(f"{fname}: HTTP {h['status']}")
            continue
        if t not in rec or datamart.changed(rec[t], h):
            changed.append(t)
    reachable = not errors or len(errors) < len(datamart.files())
    os.makedirs(CI, exist_ok=True)
    json.dump(now, open(NOW, "w"), indent=1, sort_keys=True)
    try:
        ip = socket.gethostbyname("apps.fs.usda.gov")
    except OSError as e:
        ip = f"DNS error {e}"
    print(f"DataMart reachability: {'REACHABLE' if reachable and not errors else 'PARTIAL' if reachable else 'UNREACHABLE'} "
          f"({len(now)}/{len(datamart.files())} HEAD requests answered in {time.time() - t0:.1f}s; apps.fs.usda.gov -> {ip})")
    for e in errors[:10]:
        print("  error:", e)
    print("changed tables:", ", ".join(changed) if changed else "none")
    out = arg("--out")
    if out:
        with open(out, "a") as f:
            f.write(f"changed={'true' if changed else 'false'}\nreachable={'true' if reachable and not errors else 'false'}\n")
    if errors and not now:
        sys.exit(3)


def write():
    db = arg("--db") or store.current_db()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    tables = {}
    for r in con.execute("SELECT * FROM manifest ORDER BY table_name"):
        tables[r["table_name"]] = {"file": r["file"], "url": r["url"], "last_modified": r["last_modified"], "etag": r["etag"],
                                   "content_length": r["content_length"], "sha256": r["sha256"], "rows": r["rows"],
                                   "max_modified_date": r["max_modified_date"]}
    bi = {k: json.loads(v) for k, v in con.execute("SELECT key, value FROM build_info")}
    os.makedirs(CI, exist_ok=True)
    json.dump({"fiadb_version": bi.get("fiadb_version"), "built_at": bi.get("built_at"), "latest_invyr": bi.get("latest_invyr"),
               "locations": bi.get("locations"), "visits": bi.get("visits"), "tables": tables}, open(MANIFEST, "w"), indent=1, sort_keys=True)
    print(f"wrote {os.path.relpath(MANIFEST, ROOT)}: {len(tables)} tables, built {bi.get('built_at')}")


if __name__ == "__main__":
    {"check": check, "write": write}[sys.argv[1]]()

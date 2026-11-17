"""Build a clean handoff zip of the explorer and audit it.

Usage: python -I scripts/package.py <out.zip | -> [--audit-only] [--compare-dir DIR] [--forbid "s1,..."] [--forbid-loose "f1,..."]

Included: README.md, requirements.txt, run.ps1, app/, fiasc/, scripts/, tests/ (allowlist).
Excluded: .venv, data/ (builds, raw CSVs, staging, job logs, manifests, settings), _downloads/, _e2e/, caches,
          __pycache__, *.pyc, logs and temporary files.
Audit (fails on any finding):
  * no local paths: drive-letter user paths or the current user name;
  * no data/manifest/database/log files;
  * coordinates: every decimal or DMS value inside the South Carolina lat/lon window is listed; only the bundled
    Census county boundaries (sc_counties.geojson) and minified vendor libraries may contain such numbers;
  * --forbid: strings that must not appear anywhere (e.g. fragments of a test location; given on the command line so
    they are never written to a file);
  * --compare-dir: no packaged file may be byte-identical to a file under that directory.
"""
import os, sys, re, zipfile, hashlib, fnmatch, getpass, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INCLUDE_FILES = ["README.md", "requirements.txt", "run.ps1", ".gitignore"]
INCLUDE_DIRS = ["app", "fiasc", "scripts", "tests", "web", "ci", ".github"]
MANIFEST_OK = {"ci/datamart_manifest.json"}                        # DataMart URLs/headers only, no local paths
EXCLUDE = ["*/__pycache__/*", "*.pyc", "*.pyo", "*.log", "*.tmp", "*.part", "*.part.meta", "*/.pytest_cache/*",
           "*.sqlite", "*.sqlite-*", "*.building", "*.csv", "*.zip", "ci/datamart_headers_now.json"]
DATA_LIKE = re.compile(r"(^|/)(data|_downloads|_e2e|\.venv)/|manifest|current\.json|settings\.json|last_check|state\.json", re.I)
COORD_OK = {"app/static/sc_counties.geojson"}                     # public Census county boundary vertices
VENDOR = ("app/static/vendor/", "web/vendor/")


def arg(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


def collect():
    files = [f for f in INCLUDE_FILES if os.path.exists(os.path.join(ROOT, f))]
    for d in INCLUDE_DIRS:
        for dp, dn, fn in os.walk(os.path.join(ROOT, d)):
            dn[:] = [x for x in dn if x not in ("__pycache__", ".pytest_cache")]
            for f in fn:
                rel = os.path.relpath(os.path.join(dp, f), ROOT).replace("\\", "/")
                if not any(fnmatch.fnmatch("/" + rel, p) or fnmatch.fnmatch(rel, p) for p in EXCLUDE):
                    files.append(rel)
    return sorted(files)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    out = os.path.abspath(sys.argv[1])
    forbid = [s for s in (arg("--forbid") or "").split(",") if s.strip()]
    loose = [s for s in (arg("--forbid-loose") or "").split(",") if s.strip()]   # short fragments; not checked in boundary files
    cmp_dir = arg("--compare-dir")
    files = collect()
    problems, report = [], {}
    user = getpass.getuser()
    # pattern pieces are concatenated so that this file's own source does not match them
    path_re = re.compile(r"[A-Za-z]:[\\/]+" + "Us" + r"ers[\\/]+|/" + "ho" + r"me/[a-z0-9_.-]+/|App" + r"Data[\\/]"
                         + (rf"|\b{re.escape(user)}\b" if len(user) > 2 else ""), re.I)
    lat = r"3[1-5]\.\d{2,}"
    lon = r"-?(?:7[89]|8[0-3])\.\d{2,}"
    coord_re = re.compile(rf"(?<![\d.])(?:{lat}|{lon})(?![\d])|\d{{2}}\s*°\s*\d{{1,2}}\s*['’′]")
    blobs = {}
    for rel in files:
        b = open(os.path.join(ROOT, rel), "rb").read()
        blobs[rel] = b
        if DATA_LIKE.search(rel) and rel not in MANIFEST_OK and not rel.endswith((".py", ".js", ".ps1", ".yml", ".md", ".html", ".css")):
            problems.append(f"data/manifest-like file included: {rel}")
        try:
            t = b.decode("utf-8")
        except UnicodeDecodeError:
            continue                                              # binary (PNG icons)
        for m in path_re.finditer(t):
            problems.append(f"local path or user name in {rel}: …{t[max(0, m.start() - 30):m.end() + 30]!r}…")
        for s in forbid + ([] if rel in COORD_OK else loose):
            if s in t:
                problems.append(f"forbidden string found in {rel}")
        hits = coord_re.findall(t)
        if hits:
            if rel in COORD_OK or rel.startswith(VENDOR):
                report.setdefault("coordinate-like numbers allowed", {})[rel] = len(hits)
            else:
                ctx = [t[max(0, m.start() - 40):m.end() + 20].replace("\n", " ") for m in coord_re.finditer(t)][:5]
                report.setdefault("coordinate-like numbers to review", {})[rel] = ctx
    identical = []
    if cmp_dir:
        sizes = {}
        for rel, b in blobs.items():
            sizes.setdefault(len(b), []).append(rel)
        n = 0
        for dp, dn, fn in os.walk(cmp_dir):
            for f in fn:
                p = os.path.join(dp, f)
                try:
                    sz = os.path.getsize(p)
                except OSError:
                    continue
                if sz in sizes:
                    n += 1
                    h = sha(open(p, "rb").read())
                    for rel in sizes[sz]:
                        if sha(blobs[rel]) == h:
                            identical.append((rel, os.path.relpath(p, cmp_dir)))
        for rel, other in identical:
            problems.append(f"{rel} is byte-identical to a file in the compare directory ({other})")
        report["compare-dir files with a matching size (hashed)"] = n
    for rel, ctx in report.get("coordinate-like numbers to review", {}).items():
        problems.append(f"coordinate-like values in {rel}: {ctx}")
    if problems:
        print("PACKAGE AUDIT FAILED:\n  " + "\n  ".join(problems))
        return 1
    if "--audit-only" in sys.argv:
        print(f"audit passed for {len(files)} files (no zip written):", json.dumps(report))
        return 0
    if os.path.exists(out):
        os.remove(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in files:
            z.writestr(zipfile.ZipInfo(f"fia_sc_explorer/{rel}", date_time=(2026, 11, 17, 0, 0, 0)), blobs[rel],
                       compress_type=zipfile.ZIP_DEFLATED)
    print(f"wrote {out}: {len(files)} files, {os.path.getsize(out) / 2**20:.1f} MB")
    print("audit passed:", json.dumps({k: v for k, v in report.items()}, indent=1))
    print("forbidden strings checked:", len(forbid), "exact +", len(loose), "fragments", "| local paths: none | data/manifest/log files: none"
          + (f" | byte-identical to compare dir: none" if cmp_dir else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

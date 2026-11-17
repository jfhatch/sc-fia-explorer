"""Download every SC table (plus REF tables) from the FIA DataMart and build a new SQLite database from scratch.

Usage:  .venv\\Scripts\\python.exe -I scripts\\build_db.py [--skip-tests] [--no-switch]

Steps: HEAD + download into data/staging (resumable, retries; 404 tables skipped and reported) -> raw store ->
load into data/builds/fia_sc_YYYYMMDD.sqlite (chunked) -> indexes -> derived per-visit tables -> validation
(Plot 45-3-91-25 BA 35/82/82/101/92 for 2000-2021, key relationships, row counts vs the previous build) ->
pytest suite against the new file -> atomic switch (data/current.json). Fails without switching otherwise.
"""
import os, sys, time, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
from fiasc import fetch, build, store, testrun


def main():
    args = sys.argv[1:]
    t0 = time.time()
    store.ensure()
    print("== fetch")
    recs, missing = fetch.fetch()
    if missing:
        print("tables not on the DataMart (404, skipped):", ", ".join(missing))
    name = store.new_build_name()
    print(f"== build {name}")
    prev = store.current_db()
    info = build.build(name, recs, missing, prev_db=prev)
    v = info["validation"]
    if v["errors"]:
        print("BUILD FAILED validation:\n  " + "\n  ".join(v["errors"]))
        sys.exit(1)
    if v["confirm"]:
        print("Row-count drops need confirmation (run scripts/update.ps1 -Import -AcceptRowDrops to accept):\n  " + "\n  ".join(v["confirm"]))
        sys.exit(2)
    if "--skip-tests" not in args:
        print("== tests")
        ok, tail = testrun.run_tests(info["path"])
        build.set_build_info(info["path"], "tests", {"passed": ok, "tail": tail})
        if not ok:
            print("BUILD FAILED: test suite failed against the new database\n" + tail)
            sys.exit(1)
    final = build.finish(info)
    if "--no-switch" not in args:
        store.switch_to(os.path.basename(final))
        print("live build ->", os.path.basename(final))
    T = info["timings"]
    print(f"\nDB {final}: {os.path.getsize(final) / 2**20:,.0f} MB; {info['locations']:,} plot locations; {info['visits']:,} visits; "
          f"latest INVYR {info['latest_invyr']}; FIADB {info['fiadb_version']['version'] if info['fiadb_version'] else '?'}")
    print(f"build time: load {T['load_s']:.0f}s, derive {T['derive_s']:.0f}s, validate {T['validate_s']:.0f}s; "
          f"total incl. download and tests {time.time() - t0:.0f}s")
    print("validation:", json.dumps(v["info"], default=str)[:800])


if __name__ == "__main__":
    main()

"""Command-line update (used by scripts/update.ps1); same code path as the app's Data panel.

  check                      HEAD every table, report changes (downloads nothing)
  import [--accept-row-drops] [--base-url URL]
                             download changed tables, build a new DB from scratch, validate, run tests, switch
  rollback                   restore the previous build
  status                     live build, previous builds, last check
"""
import os, sys, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
from fiasc import updater, store


def arg(name):
    a = sys.argv
    return a[a.index(name) + 1] if name in a else None


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    base = arg("--base-url")
    if cmd == "check":
        r = updater.check(base_url=base, log=print)
        fv = r["fiadb_version"]
        print(f"\nlive build {r['live_build']}; FIADB version recorded "
              f"{(fv['recorded'] or {}).get('version')} / now {(fv['now'] or {}).get('version')}")
        print(("CHANGED: " + ", ".join(r["changed"])) if r["any_changed"] else "No changes since the last build.")
        return 0 if not r["any_changed"] else 10
    if cmd == "import":
        try:
            d = updater.acquire("import", pid=os.getpid())
        except RuntimeError as e:
            print("IMPORT REFUSED:", e)
            return 1
        st = updater.run_import(d, accept_row_drops="--accept-row-drops" in sys.argv, base_url=base, echo=True)
        print("\nresult:", st.get("state"), "-", st.get("message"))
        if st.get("state") == "needs_confirmation":
            print("Row-count drops:\n  " + "\n  ".join(st.get("confirm", [])))
            print("Re-run with -AcceptRowDrops to switch anyway; the current build stays live.")
            updater.cancel(d)
            return 3
        if st.get("state") == "done":
            print("what's new:", json.dumps(st.get("whats_new_summary")))
            return 0
        return 1
    if cmd == "rollback":
        try:
            p = updater.rollback()
        except RuntimeError as e:
            print("ROLLBACK FAILED:", e)
            return 1
        print(f"restored {p['current']} (was {p.get('rolled_back_from')})")
        return 0
    if cmd == "status":
        p = store.pointer()
        print(json.dumps({"live": p.get("current"), "history": p.get("history"), "last_check": (updater.last_check() or {}).get("checked_at")}, indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())

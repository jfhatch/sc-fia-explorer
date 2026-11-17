"""Run the pytest suite against a given database file (used before switching to a new build)."""
import os, sys, subprocess
from . import store


def run_tests(db_path, log=print, timeout=1800):
    env = dict(os.environ, FIASC_DB=db_path, PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider", os.path.join(store.ROOT, "tests")]
    r = subprocess.run(cmd, cwd=store.ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    out = (r.stdout + r.stderr).strip()
    tail = "\n".join(out.splitlines()[-15:])
    log("  pytest: " + (out.splitlines()[-1] if out else "(no output)"))
    return r.returncode == 0, tail

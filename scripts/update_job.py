"""Entry point of a background update job started by the app (one process per job).

Usage: python -I scripts/update_job.py import <job_dir> [--accept-row-drops]
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fiasc import updater

if __name__ == "__main__":
    kind, d = sys.argv[1], sys.argv[2]
    if kind == "import":
        st = updater.run_import(d, accept_row_drops="--accept-row-drops" in sys.argv)
        sys.exit(0 if st.get("state") in ("done", "needs_confirmation") else 1)
    sys.exit(2)

"""FIA DataMart access: table list, HEAD checks and resumable downloads (HTTP Range) with retries."""
import os, time, hashlib, urllib.request, urllib.error

BASE_URL = os.environ.get("FIASC_BASE_URL", "https://apps.fs.usda.gov/fia/datamart/CSV/")
STATE = "SC"
STATE_TABLES = [
    "PLOT", "COND", "SUBPLOT", "SUBP_COND", "TREE", "SEEDLING", "SITETREE",
    "TREE_GRM_COMPONENT", "TREE_GRM_BEGIN", "TREE_GRM_MIDPT",
    "P2VEG_SUBPLOT_SPP", "P2VEG_SUBP_STRUCTURE", "INVASIVE_SUBPLOT_SPP",
    "DWM_VISIT", "DWM_COARSE_WOODY_DEBRIS", "DWM_FINE_WOODY_DEBRIS", "DWM_DUFF_LITTER_FUEL", "DWM_MICROPLOT_FUEL",
    "DWM_RESIDUAL_PILE", "DWM_TRANSECT_SEGMENT", "COND_DWM_CALC",
    "SOILS_LAB", "SOILS_SAMPLE_LOC", "SOILS_EROSION", "SOILS_VISIT",
    "POP_PLOT_STRATUM_ASSGN", "SURVEY",
]
REF_TABLES = ["REF_SPECIES", "REF_FOREST_TYPE", "REF_FOREST_TYPE_GROUP", "REF_PLANT_DICTIONARY", "REF_FIADB_VERSION"]
UA = "fia-sc-explorer/1.0 (local FIADB reader)"


def files():
    """(table name in SQLite, file name on DataMart)."""
    return [(t, f"{STATE}_{t}.csv") for t in STATE_TABLES] + [(t, f"{t}.csv") for t in REF_TABLES]


def head(url, timeout=30):
    """HEAD request -> dict(status, last_modified, content_length, etag). status 404 is returned, not raised."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            h = r.headers
            return {"status": r.status, "last_modified": h.get("Last-Modified"), "etag": h.get("ETag"),
                    "content_length": int(h["Content-Length"]) if h.get("Content-Length") else None}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "last_modified": None, "etag": None, "content_length": None}


def changed(rec, now):
    """Compare recorded headers with a new HEAD result; returns a list of the fields that differ."""
    diff = []
    for k in ("last_modified", "content_length", "etag"):
        if (rec.get(k) or None) != (now.get(k) or None):
            diff.append(k)
    return diff


class Cancelled(Exception):
    pass


def download(url, dest, expect=None, retries=5, chunk=1 << 20, progress=None, cancel=None, log=print):
    """Download url to dest with resume: data goes to dest + '.part'; an existing .part is continued with an HTTP
    Range request when its ETag/Last-Modified still match (recorded in dest + '.part.meta').
    expect = HEAD dict (content_length/etag/last_modified). Returns (sha256, bytes, headers)."""
    part, meta = dest + ".part", dest + ".part.meta"
    want = expect or head(url)
    if want.get("status", 200) == 404:
        raise FileNotFoundError(url)
    ident = f"{want.get('etag')}|{want.get('last_modified')}|{want.get('content_length')}"
    if os.path.exists(part) and (not os.path.exists(meta) or open(meta).read() != ident):
        os.remove(part)                                  # remote file changed since the partial download: restart
    open(meta, "w").write(ident)
    total = want.get("content_length")
    attempt = 0
    while True:
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if total is not None and have == total:
            break
        hdrs = {"User-Agent": UA}
        if have:
            hdrs["Range"] = f"bytes={have}-"
            if want.get("etag"):
                hdrs["If-Range"] = want["etag"]
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=60) as r:
                if have and r.status != 206:              # server ignored the range (or If-Range failed): start over
                    log(f"  server did not honour Range for {os.path.basename(dest)}; restarting")
                    have, mode = 0, "wb"
                else:
                    mode = "ab" if have else "wb"
                    if have:
                        log(f"  resuming {os.path.basename(dest)} at {have:,} bytes")
                with open(part, mode) as f:
                    while True:
                        if cancel and cancel():
                            raise Cancelled()
                        b = r.read(chunk)
                        if not b:
                            break
                        f.write(b)
                        have += len(b)
                        if progress:
                            progress(have, total)
            if total is None:
                break
            if have != total:
                raise IOError(f"short read {have} of {total}")
        except Cancelled:
            raise
        except Exception as e:
            attempt += 1
            if attempt > retries:
                raise RuntimeError(f"download failed after {retries} retries: {url}: {e}")
            wait = min(60, 2 ** attempt)
            log(f"  {os.path.basename(dest)}: {e}; retry {attempt}/{retries} in {wait}s")
            time.sleep(wait)
    h = hashlib.sha256()
    with open(part, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    n = os.path.getsize(part)
    os.replace(part, dest)
    if os.path.exists(meta):
        os.remove(meta)
    return h.hexdigest(), n, want


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()

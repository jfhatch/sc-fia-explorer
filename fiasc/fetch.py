"""Stage DataMart CSVs: HEAD every table, download what is needed into data/staging (resumable), then file each
download into the content-addressed raw store data/raw/<TABLE>/<sha16>.csv.

fetch(only=None, reuse=None): `reuse` maps table -> manifest record of the live build; a table whose HEAD headers
match the record (and whose raw file still exists) is reused without downloading.
"""
import os, json, time, shutil
from . import datamart, store


def stage_path(fname):
    return os.path.join(store.STAGING, fname)


def raw_match(t, h, only=None):
    """A raw-store file for table t whose recorded headers equal the current HEAD (skipped for tables in `only`)."""
    if only is not None and t in only:
        return None
    d = os.path.join(store.RAW, t)
    if not os.path.isdir(d):
        return None
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".json"):
            try:
                rec = json.load(open(os.path.join(d, fn)))
            except ValueError:
                continue
            if not datamart.changed(rec, h) and os.path.exists(os.path.join(store.DATA, rec.get("raw_path", ""))):
                return rec
    return None


def fetch(only=None, reuse=None, base_url=None, log=print, progress=None, cancel=None):
    store.ensure()
    base = base_url or datamart.BASE_URL
    out, missing = {}, []
    tables = datamart.files()
    total_steps = len(tables)
    for i, (t, fname) in enumerate(tables):
        if cancel and cancel():
            raise datamart.Cancelled()
        url = base + fname
        h = datamart.head(url)
        if h["status"] == 404:
            log(f"{fname}: not on the DataMart (HTTP 404), skipped")
            missing.append(fname)
            continue
        if h["status"] != 200:
            raise RuntimeError(f"HEAD {url} returned HTTP {h['status']}")
        rec = (reuse or {}).get(t)
        if rec and rec.get("raw_path") and not datamart.changed(rec, h) and (only is None or t not in only) \
                and os.path.exists(os.path.join(store.DATA, rec["raw_path"])):
            out[t] = dict(rec, reused=True)
            log(f"{fname}: unchanged, reusing {rec['raw_path']}")
            if progress:
                progress(i + 1, total_steps, fname, 1, 1)
            continue
        hit = raw_match(t, h, only)
        if hit:
            out[t] = dict(hit, reused=True)
            log(f"{fname}: unchanged, already in the raw store ({hit['raw_path']})")
            if progress:
                progress(i + 1, total_steps, fname, 1, 1)
            continue
        dest = stage_path(fname)
        side = dest + ".json"
        if os.path.exists(dest) and os.path.exists(side):
            s = json.load(open(side))
            if not datamart.changed(s, h):
                log(f"{fname}: already staged")
                out[t] = s
                if progress:
                    progress(i + 1, total_steps, fname, 1, 1)
                continue
        t0 = time.time()
        log(f"{fname}: downloading {h['content_length'] or 0:,} bytes")
        sha, n, hh = datamart.download(url, dest, expect=h, log=log, cancel=cancel,
                                       progress=(lambda a, b, _i=i, _f=fname: progress(_i, total_steps, _f, a, b or a)) if progress else None)
        rec = {"table": t, "file": fname, "url": url, "status": 200, "last_modified": hh.get("last_modified"),
               "etag": hh.get("etag"), "content_length": hh.get("content_length"), "sha256": sha, "bytes": n,
               "download_s": round(time.time() - t0, 1), "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        json.dump(rec, open(side, "w"), indent=1)
        out[t] = rec
        if progress:
            progress(i + 1, total_steps, fname, 1, 1)
    # file staged downloads into the raw store
    for t, rec in out.items():
        if rec.get("reused"):
            continue
        dest = stage_path(rec["file"])
        rel = f"raw/{t}/{rec['sha256'][:16]}.csv"
        absr = os.path.join(store.DATA, rel)
        os.makedirs(os.path.dirname(absr), exist_ok=True)
        if os.path.exists(absr):
            os.remove(dest)
        else:
            shutil.move(dest, absr)
        if os.path.exists(dest + ".json"):
            os.remove(dest + ".json")
        rec["raw_path"] = rel
        json.dump(rec, open(absr[:-4] + ".json", "w"), indent=1)
    return out, missing


if __name__ == "__main__":
    import sys
    recs, miss = fetch()
    json.dump({"tables": recs, "missing": miss}, open(os.path.join(store.STAGING, "_fetched.json"), "w"), indent=1)
    print("fetched", len(recs), "tables; missing:", miss)

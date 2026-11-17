"""Export the live SQLite build as a static website (GitHub Pages).

Usage: python -I scripts/export_static.py [--db FILE] [--out site] [--limit N]

site/
  index.html, plot.html, about.html, app.css, *.js, vendor/   copied from web/ (the static frontend)
  data/meta.json        build info, legend groups, filter lists, metric/event key orders
  data/plots.json       every plot location: public LAT/LON + the fields used for filtering and colouring
  data/ids.json         PLOT CN -> plot index (plot-ID search by CN; county-plot and key search use plots.json)
  data/codes.json       FIADB User Guide v9.4 code texts (pre-rendered by fiasc.core.decode), REF names
  data/counties.geojson simplified Census county boundaries
  p/<key>.json          one file per plot: visits, metrics, conditions, PLOT records, species, trees, events,
                        growth intervals, seedlings, site trees, P2 veg, invasives, DWM, soils, predecessor candidates
Fails if the site exceeds 900 MB or any file exceeds 50 MB, or if the exported Plot 45-3-91-25 totals differ from the
published 35/82/82/101/92 ft²/ac.
"""
import os, sys, json, math, time, shutil, re, hashlib
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import numpy as np
import pandas as pd
from fiasc import core, store, plotdata, build

MAX_SITE, MAX_FILE = 900 * 2 ** 20, 50 * 2 ** 20
WEB = os.path.join(ROOT, "web")
AUDIT = plotdata.AUDIT
SKIP = AUDIT | {"CN", "PLT_CN", "PREV_PLT_CN", "SRV_CN", "CTY_CN", "STATECD", "UNITCD", "COUNTYCD", "PLOT", "INVYR", "CYCLE", "SUBCYCLE"}
METRICS = ["live_n", "live_tpa", "tpa5", "sap_tpa", "ba", "qmd", "vol", "carbon", "dead_n", "dead_tpa", "dead_ba",
           "live_tpa_c1", "live_tpa_c2", "live_tpa_c3", "live_tpa_c4", "dead_tpa_c1", "dead_tpa_c2", "dead_tpa_c3", "dead_tpa_c4"]
EVTYPES = ["mortality", "dead at first tally", "cut", "ingrowth", "added (not ingrowth)", "removed from sample"]
TREE_COLS = ["SUBP", "TREE", "CONDID", "STATUSCD", "SPCD", "DIA", "DIAHTCD", "HT", "ACTUALHT", "HTCD", "CR", "CCLCD", "TREECLCD", "AGENTCD",
             "DAMAGE_AGENT_CD1", "DAMAGE_AGENT_CD2", "DAMAGE_AGENT_CD3", "DECAYCD", "STANDING_DEAD_CD", "MORTYR", "RECONCILECD",
             "P2A_GRM_FLG", "TPA_UNADJ", "VOLCFNET", "DRYBIO_AG", "CARBON_AG"]
GENERIC = {"sd": "SEEDLING", "st": "SITETREE", "p2s": "P2VEG_SUBP_STRUCTURE", "p2v": "P2VEG_SUBPLOT_SPP", "iv": "INVASIVE_SUBPLOT_SPP",
           "dwm": ["COND_DWM_CALC", "DWM_VISIT", "DWM_COARSE_WOODY_DEBRIS", "DWM_FINE_WOODY_DEBRIS", "DWM_DUFF_LITTER_FUEL",
                   "DWM_MICROPLOT_FUEL", "DWM_RESIDUAL_PILE", "DWM_TRANSECT_SEGMENT"],
           "so": ["SOILS_VISIT", "SOILS_SAMPLE_LOC", "SOILS_LAB", "SOILS_EROSION"]}
DEC = {"LAT": 6, "LON": 6, "TPA_UNADJ": 4, "DYEAR": 4}


def arg(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


def num(v, nd=3):
    """compact JSON value: NaN -> None, integral floats -> int, other floats rounded."""
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        if math.isnan(v) or math.isinf(v):
            return None
        r = round(float(v), nd)
        return int(r) if r.is_integer() else r
    if isinstance(v, str):
        return v
    if v is pd.NA:
        return None
    return v


def table_block(df, cols, decimals=None):
    """{"c": [cols], "r": [[...], ...]} with per-column rounding."""
    decimals = decimals or {}
    out = []
    vals = df[cols].astype(object).values.tolist()
    nds = [decimals.get(c, DEC.get(c, 3)) for c in cols]
    for row in vals:
        out.append([num(x, nd) for x, nd in zip(row, nds)])
    return {"c": cols, "r": out}


def dumps(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def simplify(coords, tol):
    """Douglas-Peucker on one ring."""
    if len(coords) < 5:
        return coords
    pts = np.array(coords)
    keep = np.zeros(len(pts), bool); keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        p, q = pts[a], pts[b]
        seg = pts[a + 1:b]
        d = q - p
        n = math.hypot(*d)
        w = seg - p
        dist = np.abs(d[0] * w[:, 1] - d[1] * w[:, 0]) / n if n else np.hypot(w[:, 0], w[:, 1])
        i = int(np.argmax(dist))
        if dist[i] > tol:
            keep[a + 1 + i] = True
            stack += [(a, a + 1 + i), (a + 1 + i, b)]
    out = pts[keep]
    return [[round(x, 4), round(y, 4)] for x, y in out]


def main():
    t0 = time.time()
    db = arg("--db") or store.current_db()
    out = os.path.abspath(arg("--out", os.path.join(ROOT, "site")))
    limit = int(arg("--limit", 0))
    con = store.connect_ro(db)
    ref = core.Ref(con)
    q = lambda s, p=(): pd.read_sql_query(s, con, params=p)
    bi = {k: json.loads(v) for k, v in con.execute("SELECT key, value FROM build_info")}
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(WEB, out)
    # cache busting: GitHub Pages lets browsers cache files for 10 minutes, so after a deploy a browser could mix new
    # code with old data (or the reverse). Every page references its scripts/styles with ?v=<site version>, and fia.js
    # appends the same version to every data fetch.
    hv = hashlib.sha256(json.dumps(bi.get("build_name")).encode())
    for dp, dn, fn in sorted(os.walk(WEB)):
        for f in sorted(fn):
            hv.update(f.encode()); hv.update(open(os.path.join(dp, f), "rb").read())
    site_v = hv.hexdigest()[:12]
    for f in os.listdir(out):
        if f.endswith(".html"):
            fp = os.path.join(out, f); h = open(fp, encoding="utf-8").read()
            h2 = re.sub(r'((?:src|href)="(?!https?:|//|#)[^"?]+\.(?:js|css))"', lambda m: f'{m.group(1)}?v={site_v}"', h)
            open(fp, "w", encoding="utf-8").write(h2)
    os.makedirs(os.path.join(out, "data")); os.makedirs(os.path.join(out, "p"))
    print(f"export {os.path.basename(db)} -> {out}")

    # ------------------------------------------------------------ plots.json + meta.json (same rules as /api/meta, /api/locations)
    loc = q("SELECT * FROM plot_location ORDER BY KEY")
    if limit:
        keep = set(loc.KEY.sample(limit, random_state=1)) | set(core.REGRESSION_BA)
        loc = loc[loc.KEY.isin(keep)].reset_index(drop=True)
    gcount = loc.FORTYP_GRP.dropna().astype(int).value_counts()
    groups = [{"code": int(g), "name": ref.FGN.get(int(g), f"group {g}"), "n": int(n), "color": core.PAL[i] if i < len(core.PAL) else core.OTHER}
              for i, (g, n) in enumerate(gcount.items())]
    groups.append({"code": -1, "name": "Nonforest / no accessible forest", "n": int((loc.FORTYP_GRP.isna() & (loc.PLOT_STATUS_CD != 3)).sum()), "color": "#c9c8c2"})
    groups.append({"code": -2, "name": "Nonsampled", "n": int((loc.FORTYP_GRP.isna() & (loc.PLOT_STATUS_CD == 3)).sum()), "color": "#6b6a66"})
    grp = loc.FORTYP_GRP.fillna(-1).astype(int)
    grp[loc.FORTYP_GRP.isna() & (loc.PLOT_STATUS_CD == 3)] = -2
    des = loc.DESIGNS.map(lambda d: {"annual": "a", "periodic": "p"}.get(d, "ap" if "annual" in d else "o"))
    # m = MEASYEAR of the most recent measurement; the page decides "active" from it and the viewer's current year
    lastmeas = q("SELECT KEY, MAX(MEASYEAR) AS M FROM visit GROUP BY KEY").set_index("KEY").M
    pcols = ["k", "la", "lo", "g", "f", "y", "p", "o", "l", "n", "i", "d", "a", "x", "q", "t", "b", "m"]
    prow = []
    for r, g, d, my in zip(loc.itertuples(), grp, des, lastmeas.reindex(loc.KEY).fillna(loc.LAST_INVYR.set_axis(loc.KEY)).astype(int)):
        prow.append([r.KEY, round(r.LAT, 5), round(r.LON, 5), int(g), num(r.FORTYPCD), int(r.COUNTYCD), int(r.PLOT), num(r.OWNGRPCD),
                     int(r.LAST_INVYR), int(r.N_VISITS), int(r.HAS_INVASIVES), d, num(r.STDAGE), int(r.COORDS_DIFFER), int(r.N_PRED_CAND),
                     r.LAST_DATE, num(r.BA, 1), int(my)])
    kidx = {k: i for i, k in enumerate(loc.KEY)}
    json.dump({"c": pcols, "r": prow}, open(os.path.join(out, "data", "plots.json"), "w", encoding="utf-8"), separators=(",", ":"))
    ft = loc.FORTYPCD.dropna().astype(int).value_counts()
    cty = [{"code": int(c), "name": n} for c, n in con.execute("SELECT COUNTYCD, NAME FROM county ORDER BY NAME")]
    meta = {
        "build": {"build_name": bi.get("build_name"), "built_at": bi.get("built_at"), "fiadb_version": bi.get("fiadb_version"),
                  "locations": len(loc), "visits": bi.get("visits"), "latest_invyr": bi.get("latest_invyr")},
        "groups": groups,
        "types": [{"code": int(c), "name": ref.FTN.get(int(c), "?"), "group": ref.ftgroup(c), "n": int(n)} for c, n in ft.sort_index().items()],
        "owners": [{"code": int(c), "name": core.dec("COND.OWNGRPCD", int(c)).split(" = ", 1)[-1].split(" (")[0], "n": int(n)}
                   for c, n in loc.OWNGRPCD.dropna().astype(int).value_counts().sort_index().items()],
        "counties": cty, "last_invyr": [int(loc.LAST_INVYR.min()), int(loc.LAST_INVYR.max())], "max_visits": int(loc.N_VISITS.max()),
        "metrics": METRICS, "evtypes": EVTYPES,
        "coord_note": "Public coordinates are fuzzed (usually within 0.5 mi, some up to 1 mi) and some private plots are swapped "
                      "within the county, so the true plot may not be the nearest.",
        "unadj_note": plotdata.UNADJ_NOTE, "regression": {k: {str(y): v for y, v in d.items()} for k, d in core.REGRESSION_BA.items()},
    }
    json.dump(meta, open(os.path.join(out, "data", "meta.json"), "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)

    # ------------------------------------------------------------ county boundaries (simplified)
    gj = json.load(open(os.path.join(ROOT, "app", "static", "sc_counties.geojson")))
    for f in gj["features"]:
        g = f["geometry"]
        if g["type"] == "Polygon":
            g["coordinates"] = [simplify(r, 0.0004) for r in g["coordinates"]]
        else:
            g["coordinates"] = [[simplify(r, 0.0004) for r in poly] for poly in g["coordinates"]]
    json.dump(gj, open(os.path.join(out, "data", "counties.geojson"), "w"), separators=(",", ":"))

    # ------------------------------------------------------------ codes.json: decode texts rendered by fiasc.core.decode
    codes = {"t": {}, "nt": {}, "rn": {}, "al": core.ALIAS}
    for key, ent in core.CODES.items():
        if isinstance(ent, dict) and "codes" in ent:
            codes["t"][key] = {c: core.decode(key, int(c) if c.lstrip("-").isdigit() else c)["text"] for c in ent["codes"]}
    for key, why in core.UNRESOLVED.items():
        if key not in core.CODES:
            codes["nt"][key] = why
    for key, d in core.RESEARCH.items():
        if not key.startswith("_"):
            codes["rn"][key] = {c: r.get("label") for c, r in d.items()}
    sp = q("SELECT SPCD, COMMON_NAME, GENUS, SPECIES FROM REF_SPECIES")
    codes["sp"] = {int(r.SPCD): [r.COMMON_NAME, f"{r.GENUS or ''} {r.SPECIES or ''}".strip()] for r in sp.itertuples()}
    codes["ft"] = {int(k): v for k, v in ref.FTN.items()}
    codes["fg"] = {int(k): v for k, v in ref.FGN.items()}
    syms = set()
    for t in ("INVASIVE_SUBPLOT_SPP", "P2VEG_SUBPLOT_SPP"):
        if plotdata.has_table(con, t):
            syms |= {r[0] for r in con.execute(f"SELECT DISTINCT VEG_SPCD FROM {t}") if r[0]}
    codes["pl"] = {s: list(ref.plant(s)) for s in sorted(syms)}
    json.dump(codes, open(os.path.join(out, "data", "codes.json"), "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)

    # ------------------------------------------------------------ per-plot tables (sliced by key)
    visit = q("SELECT v.*, p.MICROPLOT_LOC, p.MANUAL AS P_MANUAL, p.PLOT_NONSAMPLE_REASN_CD FROM visit v JOIN PLOT p ON p.CN = v.PLT_CN")
    visit = visit[visit.KEY.isin(kidx)].sort_values(["KEY", "DYEAR"])
    vkey = dict(zip(visit.PLT_CN, visit.KEY))
    vno = {cn: i for k, g in visit.groupby("KEY", sort=False) for i, cn in enumerate(g.PLT_CN)}
    ids = {cn: kidx[k] for cn, k in vkey.items()}
    json.dump(ids, open(os.path.join(out, "data", "ids.json"), "w"), separators=(",", ":"))

    def by_key(df, cn_col="PLT_CN"):
        df = df[df[cn_col].isin(vkey)].copy()
        df.insert(0, "vi", df[cn_col].map(vno))
        df["_k"] = df[cn_col].map(vkey)
        return {k: g.drop(columns="_k") for k, g in df.groupby("_k", sort=False)}

    def generic(df, table):
        cols = [c for c in df.columns if c not in SKIP and not c.endswith("_CN") and c != "vi" and df[c].notna().any()]
        return table_block(df.sort_values("vi"), ["vi"] + cols)

    t1 = time.time()
    plot_rows = by_key(q("SELECT * FROM PLOT"), "CN")
    cond_rows = by_key(q("SELECT * FROM COND"))
    spv = by_key(q("SELECT * FROM visit_species"))
    tree = q("SELECT t.CN, t.PLT_CN, t.PREV_TRE_CN, " + ", ".join(f"t.{c}" for c in TREE_COLS) + ", l.TID FROM TREE t JOIN tree_link l ON l.TRE_CN = t.CN")
    tree["INVYR"] = tree.PLT_CN.map(dict(zip(visit.PLT_CN, visit.INVYR)))
    tree["DYEAR"] = tree.PLT_CN.map(dict(zip(visit.PLT_CN, visit.DYEAR)))
    tree["KEY"] = tree.PLT_CN.map(vkey)
    tree = tree[tree.KEY.notna()]
    # tree labels as in core.link_trees: S{subp}-T{tree} of the first record, -P2A for bridge records, suffix on collisions
    first = tree.sort_values(["DYEAR", "INVYR", "SUBP", "TREE"]).drop_duplicates("TID")
    lab = ("S" + first.SUBP.astype(int).astype(str) + "-T" + first.TREE.astype(int).astype(str) + np.where(first.SUBP > 4, "-P2A", ""))
    lab = pd.DataFrame({"TID": first.TID, "KEY": first.KEY, "L": lab.values}).sort_values(["KEY", "L", "TID"])
    lab["n"] = lab.groupby(["KEY", "L"]).TID.transform("size")
    lab["s"] = lab.groupby(["KEY", "L"]).cumcount()
    lab["L"] = np.where(lab.n > 1, lab.L + lab.s.map(lambda i: "abcdefghijklmnop"[i]), lab.L)
    tlabel = dict(zip(lab.TID, lab.L))
    # growth intervals (vectorized core.tree_intervals): consecutive records of a tree, both live
    gi = build.growth_intervals(tree)
    grow = {k: g for k, g in gi.groupby("KEY", sort=False)}
    tree["pv"] = tree.PREV_TRE_CN.notna().astype(int)
    tree.insert(0, "vi", tree.PLT_CN.map(vno))
    trees = {k: g for k, g in tree.groupby("KEY", sort=False)}
    ev = q("SELECT * FROM tree_event")
    ev = ev[ev.KEY.isin(kidx)]
    ev["t"] = ev.TYPE.map({t: i for i, t in enumerate(EVTYPES)})
    events = {k: g for k, g in ev.groupby("KEY", sort=False)}
    gen = {}
    for short, tabs in GENERIC.items():
        for t in (tabs if isinstance(tabs, list) else [tabs]):
            if plotdata.has_table(con, t):
                gen[(short, t)] = by_key(q(f'SELECT * FROM "{t}"'))
    pcs = q("SELECT * FROM predecessor_candidate")
    pc_by = {k: g.sort_values("RANK") for k, g in pcs.groupby("KEY")}
    cf_by = {k: g.sort_values("SCORE", ascending=False) for k, g in pcs.groupby("CAND_KEY")}
    print(f"  tables loaded and grouped in {time.time() - t1:.0f}s")

    # ------------------------------------------------------------ write p/<key>.json
    t2 = time.time()
    vcols = ["PLT_CN", "INVYR", "DATE", "DATE_APPROX", "DESIGN", "DYEAR", "KINDCD", "DESIGNCD", "PLOT_STATUS_CD", "PLOT_NONSAMPLE_REASN_CD",
             "REMPER", "PREV_PLT_CN", "CHAIN", "LAT", "LON", "P_MANUAL", "MICROPLOT_LOC", "FORTYPCD", "STDAGE", "OWNGRPCD", "N_INVASIVE_SPP"]
    vshort = ["cn", "y", "d", "da", "ds", "dy", "kc", "dc", "st", "ns", "rp", "pp", "ch", "la", "lo", "mn", "mp", "ft", "ag", "og", "ni"]
    check25 = None
    vgroups = {k: g for k, g in visit.groupby("KEY", sort=False)}
    sizes = []
    for i, r in enumerate(loc.itertuples()):
        k = r.KEY
        vg = vgroups[k]
        vis = []
        for row in vg.itertuples(index=False):
            d = row._asdict()
            o = {s: num(d[c], DEC.get(c, 4)) for s, c in zip(vshort, vcols)}
            o["m"] = [num(d[m], 4) for m in METRICS]
            vis.append(o)
        tr = trees.get(k)
        tids = []
        if tr is not None:
            tids = list(dict.fromkeys(tr.sort_values(["DYEAR", "INVYR", "SUBP", "TREE"]).TID))
            tix = {t: j for j, t in enumerate(tids)}
            tr = tr.assign(ti=tr.TID.map(tix)).sort_values(["vi", "SUBP", "TREE"])
        P = {
            "k": k, "s": int(r.STATECD), "u": int(r.UNITCD), "c": int(r.COUNTYCD), "p": int(r.PLOT), "la": num(r.LAT, 6), "lo": num(r.LON, 6),
            "cd": int(r.COORDS_DIFFER), "nc": int(r.N_CHAINS), "og": num(r.OWNGRPCD), "ft": num(r.FORTYPCD), "fg": num(r.FORTYP_GRP),
            "dsg": r.DESIGNS, "v": vis,
            "pf": table_block(plot_rows[k], ["vi"] + [c for c in plot_rows[k].columns if c not in AUDIT and c not in ("CN", "SRV_CN", "CTY_CN", "vi")
                                                      and plot_rows[k][c].notna().any()]) if k in plot_rows else None,
            "cn": generic(cond_rows[k], "COND") if k in cond_rows else None,
            "sp": table_block(spv[k], ["vi", "SPCD", "live_n", "live_tpa", "tpa5", "ba", "vol", "carbon", "dead_n", "dead_tpa"], {"ba": 4}) if k in spv else None,
            "tl": [tlabel.get(t, "?") for t in tids],
            "tr": table_block(tr, ["vi", "ti", "pv"] + TREE_COLS) if tr is not None else None,
            "ev": table_block(events[k].assign(ti=events[k].TID.map(tix)).sort_values(["Y1", "t"]),
                              ["t", "Y0", "Y1", "ti", "SPCD", "SUBP", "DIA", "AGENTCD", "RECONCILECD", "MORTYR", "TPA", "BA_AC"], {"BA_AC": 4, "TPA": 4})
                  if k in events and tr is not None else None,
            "gr": table_block(grow[k].assign(ti=grow[k].TID.map(tix)), ["ti", "SPCD", "y0", "y1", "yrs", "dia0", "dia1", "gd", "gh"], {"gd": 4, "yrs": 3})
                  if k in grow and tr is not None else None,
        }
        for (short, t), dd in gen.items():
            if k in dd:
                blk = generic(dd[k], t)
                if short in ("dwm", "so"):
                    P.setdefault(short, {})[t] = blk
                else:
                    P[short] = blk
        if k in pc_by:
            P["pc"] = [{"key": x.CAND_KEY, "plot": int(x.CAND_PLOT), "last": x.CAND_LAST_DATE, "invyr": int(x.CAND_INVYR), "ft": num(x.CAND_FORTYPCD),
                        "age": num(x.CAND_STDAGE), "dist": num(x.DIST_MI, 2), "dt": num(x.DT_YR, 2), "rp": num(x.REMPER, 1), "nb": int(x.N_BRIDGE),
                        "nm": int(x.N_MATCHED), "pairs": re.sub(r"SPCD (\d+)", lambda m: ref.spname(int(m.group(1))), x.PAIRS or ""),
                        "score": num(x.SCORE, 1), "rank": int(x.RANK)} for x in pc_by[k].itertuples()]
        if k in cf_by:
            P["cf"] = [{"key": x.KEY, "score": num(x.SCORE, 1), "rank": int(x.RANK), "dist": num(x.DIST_MI, 2)} for x in cf_by[k].itertuples()]
        s = dumps(P)
        open(os.path.join(out, "p", f"{k}.json"), "w", encoding="utf-8").write(s)
        sizes.append(len(s.encode("utf-8")))
        if k in core.REGRESSION_BA:
            check25 = {v["y"]: v["m"][METRICS.index("ba")] for v in vis}
        if i % 2000 == 0:
            print(f"  {i:,}/{len(loc):,} plot files ({time.time() - t2:.0f}s)")
    print(f"  {len(loc):,} plot files written in {time.time() - t2:.0f}s; largest {max(sizes) / 1024:.0f} KB, median {np.median(sizes) / 1024:.1f} KB")

    # ------------------------------------------------------------ validation
    problems = []
    for key, exp in core.REGRESSION_BA.items():
        if check25 is None:
            problems.append(f"{key} not exported")
            continue
        bad = {y: check25.get(y) for y, ba in exp.items() if check25.get(y) is None or int(round(check25[y])) != ba}
        if bad:
            problems.append(f"{key} exported BA differs from published {exp}: {bad}")
    total, nfiles, biggest = 0, 0, (0, "")
    for dp, dn, fn in os.walk(out):
        for f in fn:
            sz = os.path.getsize(os.path.join(dp, f))
            total += sz; nfiles += 1
            if sz > biggest[0]:
                biggest = (sz, os.path.relpath(os.path.join(dp, f), out))
            if sz > MAX_FILE:
                problems.append(f"{os.path.relpath(os.path.join(dp, f), out)} is {sz / 2**20:.1f} MB (> 50 MB)")
    if total > MAX_SITE:
        problems.append(f"site is {total / 2**20:.0f} MB (> 900 MB)")
    print(f"site: {nfiles:,} files, {total / 2**20:.1f} MB; largest file {biggest[1]} {biggest[0] / 2**20:.1f} MB; "
          f"Plot 45-3-91-25 BA {check25}; {time.time() - t0:.0f}s")
    if problems:
        print("EXPORT FAILED:\n  " + "\n  ".join(problems))
        sys.exit(1)
    json.dump({"files": nfiles, "bytes": total, "built_at": bi.get("built_at")}, open(os.path.join(out, "data", "site_stats.json"), "w"))


if __name__ == "__main__":
    main()

"""Build a new SQLite database from the raw DataMart CSVs, from scratch (never modifies a live build).

build(name, recs, log, progress, cancel) loads every table in chunks, indexes it, derives the per-visit tables used
by the app, records the manifest and validates. Writes builds/<name>.building and renames it to builds/<name> only
after validation passes, so a failed or cancelled build never appears as a usable build.
"""
import os, sys, json, time, sqlite3, datetime, math
import numpy as np
import pandas as pd
from . import core, store, datamart

AUDIT = {"CREATED_BY", "CREATED_DATE", "CREATED_IN_INSTANCE", "MODIFIED_BY", "MODIFIED_DATE", "MODIFIED_IN_INSTANCE"}
INDEX_COLS = ["CN", "PLT_CN", "PREV_PLT_CN", "PREV_TRE_CN", "INVYR", "TRE_CN"]
DIGEST_TABLES = {"PLOT", "COND", "SUBPLOT", "SUBP_COND", "TREE", "SEEDLING", "SITETREE", "P2VEG_SUBPLOT_SPP",
                 "P2VEG_SUBP_STRUCTURE", "INVASIVE_SUBPLOT_SPP", "DWM_VISIT", "DWM_COARSE_WOODY_DEBRIS", "DWM_FINE_WOODY_DEBRIS",
                 "DWM_DUFF_LITTER_FUEL", "DWM_MICROPLOT_FUEL", "DWM_RESIDUAL_PILE", "DWM_TRANSECT_SEGMENT", "COND_DWM_CALC",
                 "SOILS_LAB", "SOILS_SAMPLE_LOC", "SOILS_EROSION", "SOILS_VISIT"}
CHILD_CHECK = ["COND", "SUBPLOT", "TREE", "SEEDLING", "SITETREE", "SUBP_COND"]   # PLT_CN must exist in PLOT
MASK = (1 << 64) - 1
SIZE_CLASSES = [("c1", 1.0, 5.0), ("c2", 5.0, 10.0), ("c3", 10.0, 20.0), ("c4", 20.0, 1e9)]


class BuildError(Exception):
    pass


def q(con, sql, params=()):
    return pd.read_sql_query(sql, con, params=params)


# ================================================================ load
def load_table(con, name, path, log, digests, cancel=None):
    t0 = time.time()
    hdr = pd.read_csv(path, nrows=0, encoding_errors="replace").columns.tolist()
    sample = pd.read_csv(path, nrows=20000, low_memory=False, encoding_errors="replace")
    cols = []
    for c in hdr:
        if c in core.CN_COLS or c.endswith("_CN"):
            ty = "TEXT"
        elif pd.api.types.is_numeric_dtype(sample[c]):
            ty = "NUMERIC"
        else:
            ty = "TEXT"
        cols.append((c, ty))
    con.execute(f'DROP TABLE IF EXISTS "{name}"')
    con.execute(f'CREATE TABLE "{name}" (' + ", ".join(f'"{c}" {t}' for c, t in cols) + ")")
    ins = f'INSERT INTO "{name}" VALUES (' + ",".join("?" * len(cols)) + ")"
    keycol = "CN" if name == "PLOT" else ("PLT_CN" if "PLT_CN" in hdr else None)
    hcols = [c for c in hdr if c not in AUDIT]
    dig = {} if (name in DIGEST_TABLES and keycol) else None
    chunk = max(20000, 8_000_000 // max(1, len(hdr)))
    n = 0
    max_mod = None
    for ch in pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False, chunksize=chunk, encoding_errors="replace"):
        if cancel and cancel():
            raise datamart.Cancelled()
        if dig is not None and len(ch):
            h = pd.util.hash_pandas_object(ch[hcols], index=False).values.astype(np.uint64)
            codes, uniq = pd.factorize(ch[keycol].values)
            sums = np.zeros(len(uniq), dtype=np.uint64)
            np.add.at(sums, codes, h)
            cnt = np.bincount(codes, minlength=len(uniq))
            for k, s, c in zip(uniq, sums, cnt):
                a = dig.get(k)
                dig[k] = ((a[0] + int(s)) & MASK, a[1] + int(c)) if a else (int(s), int(c))
        if "MODIFIED_DATE" in ch:
            m = ch.MODIFIED_DATE[ch.MODIFIED_DATE != ""].max() if (ch.MODIFIED_DATE != "").any() else None
            if m and (max_mod is None or m > max_mod):
                max_mod = m
        vals = ch.mask(ch == "").astype(object)
        vals = vals.where(vals.notna(), None)
        con.executemany(ins, vals.itertuples(index=False, name=None))
        n += len(ch)
    if dig is not None:
        digests.extend((k, name, v[1], format(v[0], "016x")) for k, v in dig.items())
    for c in INDEX_COLS:
        if c in hdr:
            con.execute(f'CREATE INDEX "ix_{name}_{c}" ON "{name}" ("{c}")')
    if all(c in hdr for c in ("STATECD", "UNITCD", "COUNTYCD", "PLOT")):
        con.execute(f'CREATE INDEX "ix_{name}_key" ON "{name}" (STATECD, UNITCD, COUNTYCD, PLOT)')
    con.commit()
    dt = time.time() - t0
    log(f"  {name}: {n:,} rows, {len(hdr)} columns, {dt:.0f}s")
    return {"rows": n, "columns": len(hdr), "load_s": round(dt, 1), "max_modified_date": max_mod}


# ================================================================ derived tables
def stand_metrics(B):
    """Per-visit stand metrics from TREE rows B (SUBP <= 4, with BA): same definitions as the Plot 25 PDF's stand()."""
    live = B[(B.STATUSCD == 1) & B.TPA_UNADJ.notna()].copy()
    dead = B[(B.STATUSCD == 2) & B.TPA_UNADJ.notna()].copy()
    for d in (live, dead):
        d["W_BA"] = d.BA * d.TPA_UNADJ
        d["W_D2"] = d.DIA ** 2 * d.TPA_UNADJ
        d["W_VOL"] = d.VOLCFNET.fillna(0) * d.TPA_UNADJ
        d["W_C"] = d.CARBON_AG.fillna(0) * d.TPA_UNADJ / 2000
        d["W_TPA5"] = np.where(d.DIA >= 5, d.TPA_UNADJ, 0.0)
        for c, lo, hi in SIZE_CLASSES:
            d[c] = np.where((d.DIA >= lo) & (d.DIA < hi), d.TPA_UNADJ, 0.0)
    g = live.groupby("PLT_CN")
    m = pd.DataFrame({"live_n": g.size(), "live_tpa": g.TPA_UNADJ.sum(), "ba": g.W_BA.sum(), "d2": g.W_D2.sum(),
                      "vol": g.W_VOL.sum(), "carbon": g.W_C.sum(),
                      **{f"live_tpa_{c}": g[c].sum() for c, _, _ in SIZE_CLASSES}})
    m["qmd"] = np.sqrt(m.d2 / m.live_tpa)
    m = m.drop(columns="d2")
    gd = dead.groupby("PLT_CN")
    dm = pd.DataFrame({"dead_n": gd.size(), "dead_tpa": gd.TPA_UNADJ.sum(), "dead_ba": gd.W_BA.sum(),
                       **{f"dead_tpa_{c}": gd[c].sum() for c, _, _ in SIZE_CLASSES}})
    m = m.join(dm, how="outer")
    m["tpa5"] = m.live_tpa_c2.fillna(0) + m.live_tpa_c3.fillna(0) + m.live_tpa_c4.fillna(0)
    m["sap_tpa"] = m.live_tpa_c1
    sp = pd.concat([
        live.groupby(["PLT_CN", "SPCD"]).agg(live_n=("CN", "size"), live_tpa=("TPA_UNADJ", "sum"), ba=("W_BA", "sum"),
                                             vol=("W_VOL", "sum"), carbon=("W_C", "sum"), tpa5=("W_TPA5", "sum")),
        dead.groupby(["PLT_CN", "SPCD"]).agg(dead_n=("CN", "size"), dead_tpa=("TPA_UNADJ", "sum"), dead_ba=("W_BA", "sum"))],
        axis=1).reset_index()
    return m.reset_index(), sp


def tree_events_vectorized(B, prev_year, key_first):
    """Statewide equivalent of core.tree_events() (validated against it in tests/test_metrics.py).
    B: TREE rows (SUBP <= 4) with TID, KEY, INVYR, BA. prev_year: PLT_CN -> previous INVYR of the same location key.
    key_first: KEY -> first INVYR."""
    cols = ["KEY", "PLT_CN", "Y0", "Y1", "TYPE", "TID", "SPCD", "SUBP", "DIA", "AGENTCD", "RECONCILECD", "MORTYR", "TPA", "BA_AC"]
    B = B.sort_values(["TID", "INVYR"])
    out = []

    def first_with(status):
        x = B[B.STATUSCD == status]
        return x.drop_duplicates("TID", keep="first")

    live = B[B.STATUSCD == 1]

    def last_live_before(qq):
        m = live[["TID", "INVYR", "DIA", "TPA_UNADJ", "BA"]].merge(qq[["TID", "INVYR"]].rename(columns={"INVYR": "QY"}), on="TID")
        m = m[m.INVYR < m.QY]
        return m.drop_duplicates("TID", keep="last").set_index("TID")

    for status, typ_live, typ_none in [(2, "mortality", "dead at first tally"), (3, "cut", None)]:
        qd = first_with(status)
        p = last_live_before(qd)
        has = qd.TID.isin(p.index)
        a = qd[has]
        pp = p.loc[a.TID]
        out.append(pd.DataFrame({"KEY": a.KEY.values, "PLT_CN": a.PLT_CN.values, "Y0": pp.INVYR.values, "Y1": a.INVYR.values,
                                 "TYPE": typ_live, "TID": a.TID.values, "SPCD": a.SPCD.values, "SUBP": a.SUBP.values,
                                 "DIA": pp.DIA.values, "AGENTCD": a.AGENTCD.values, "RECONCILECD": a.RECONCILECD.values,
                                 "MORTYR": a.MORTYR.values, "TPA": pp.TPA_UNADJ.values, "BA_AC": (pp.BA * pp.TPA_UNADJ).values}))
        if typ_none:
            b = qd[~has]
            out.append(pd.DataFrame({"KEY": b.KEY.values, "PLT_CN": b.PLT_CN.values, "Y0": b.PLT_CN.map(prev_year).values,
                                     "Y1": b.INVYR.values, "TYPE": typ_none, "TID": b.TID.values, "SPCD": b.SPCD.values,
                                     "SUBP": b.SUBP.values, "DIA": b.DIA.values, "AGENTCD": b.AGENTCD.values,
                                     "RECONCILECD": b.RECONCILECD.values, "MORTYR": b.MORTYR.values, "TPA": b.TPA_UNADJ.values,
                                     "BA_AC": (b.BA * b.TPA_UNADJ).values}))
    g0 = B.drop_duplicates("TID", keep="first")
    g0 = g0[(g0.INVYR > g0.KEY.map(key_first)) & (g0.STATUSCD == 1)]
    out.append(pd.DataFrame({"KEY": g0.KEY.values, "PLT_CN": g0.PLT_CN.values, "Y0": g0.PLT_CN.map(prev_year).values,
                             "Y1": g0.INVYR.values, "TYPE": np.where(g0.RECONCILECD == 1, "ingrowth", "added (not ingrowth)"),
                             "TID": g0.TID.values, "SPCD": g0.SPCD.values, "SUBP": g0.SUBP.values, "DIA": g0.DIA.values,
                             "AGENTCD": g0.AGENTCD.values, "RECONCILECD": g0.RECONCILECD.values, "MORTYR": np.nan,
                             "TPA": g0.TPA_UNADJ.values, "BA_AC": (g0.BA * g0.TPA_UNADJ).values}))
    r0 = B[B.STATUSCD == 0][["TID", "INVYR", "KEY", "PLT_CN", "SPCD", "SUBP", "AGENTCD", "RECONCILECD"]]
    if len(r0):
        allb = B[["TID", "INVYR", "DIA", "TPA_UNADJ", "BA"]]
        m = r0.merge(allb.rename(columns={"INVYR": "PY"}), on="TID")
        m = m[m.PY < m.INVYR].sort_values(["TID", "INVYR", "PY"]).drop_duplicates(["TID", "INVYR"], keep="last")
        m["Y0"] = m.PLT_CN.map(prev_year)
        m = m[m.Y0.notna()]
        out.append(pd.DataFrame({"KEY": m.KEY.values, "PLT_CN": m.PLT_CN.values, "Y0": m.Y0.values, "Y1": m.INVYR.values,
                                 "TYPE": "removed from sample", "TID": m.TID.values, "SPCD": m.SPCD.values, "SUBP": m.SUBP.values,
                                 "DIA": m.DIA.values, "AGENTCD": m.AGENTCD.values, "RECONCILECD": m.RECONCILECD.values,
                                 "MORTYR": np.nan, "TPA": m.TPA_UNADJ.values, "BA_AC": (m.BA * m.TPA_UNADJ).values}))
    ev = pd.concat(out, ignore_index=True)[cols]
    return ev


def growth_intervals(tree):
    """Statewide equivalent of core.tree_intervals() (validated against it in tests/test_metrics.py): one row per tree
    per consecutive pair of records (SUBP <= 4) that are both live, with rates from the actual survey dates.
    tree: TREE rows with TID, KEY, INVYR, DYEAR, STATUSCD, SPCD, DIA, HT."""
    B = tree[tree.SUBP <= 4].sort_values(["TID", "INVYR"])
    nx = B.groupby("TID")[["STATUSCD", "SPCD", "INVYR", "DYEAR", "DIA", "HT"]].shift(-1)
    yrs = nx.DYEAR - B.DYEAR
    ok = (B.STATUSCD == 1) & (nx.STATUSCD == 1) & (yrs > 0)
    gi = pd.DataFrame({"KEY": B.KEY[ok], "TID": B.TID[ok], "SPCD": nx.SPCD[ok], "y0": B.INVYR[ok], "y1": nx.INVYR[ok],
                       "yrs": yrs[ok], "dia0": B.DIA[ok], "dia1": nx.DIA[ok]})
    gi["gd"] = (gi.dia1 - gi.dia0) / gi.yrs
    gi["gh"] = (nx.HT[ok] - B.HT[ok]) / gi.yrs
    return gi


def bridge_match(bridge, periodic_live, gap):
    """Greedy species/DBH matching of first-national-visit bridge trees (SUBP > 4) to the periodic plot's last live
    trees. A pair matches when the species agrees and DBH change is between -0.5 in and +(0.6 in/yr x gap + 1) in."""
    hi = 0.6 * max(gap, 0) + 1.0
    used, pairs = set(), []
    for b in sorted(bridge, key=lambda x: (x[0], x[1])):
        best = None
        for j, p in enumerate(periodic_live):
            if j in used or p[0] != b[0]:
                continue
            d = b[1] - p[1]
            if -0.5 <= d <= hi and (best is None or abs(d) < abs(best[1])):
                best = (j, d)
        if best:
            used.add(best[0])
            pairs.append((b[0], periodic_live[best[0]][1], b[1]))
    return pairs


def derive(con, log, cancel=None):
    t0 = time.time()
    ref = core.Ref(con)
    gj = os.path.join(store.ROOT, "app", "static", "sc_counties.geojson")
    cty = pd.DataFrame([f["properties"] for f in json.load(open(gj))["features"]]) if os.path.exists(gj) else         pd.DataFrame(columns=["COUNTYCD", "NAME", "GEOID"])
    cty.to_sql("county", con, if_exists="replace", index=False)
    plot = q(con, "SELECT CN, PREV_PLT_CN, INVYR, STATECD, UNITCD, COUNTYCD, PLOT, PLOT_STATUS_CD, MEASYEAR, MEASMON, MEASDAY, "
                  "REMPER, KINDCD, DESIGNCD, LAT, LON, MANUAL, INVASIVE_SAMPLING_STATUS_CD, P2VEG_SAMPLING_STATUS_CD, CYCLE, SUBCYCLE "
                  "FROM PLOT")
    plot["MEASYEAR"] = plot.MEASYEAR.fillna(plot.INVYR)
    plot = core.prep_plot(plot)
    plot["KEY"] = [core.plot_key(*r) for r in plot[["STATECD", "UNITCD", "COUNTYCD", "PLOT"]].itertuples(index=False)]
    plot = plot.sort_values(["DYEAR", "INVYR"])
    plot["CHAIN"] = core.root_cns(plot.CN.tolist(), plot.PREV_PLT_CN.tolist())
    plot["DESIGN"] = np.select([plot.KINDCD.isin([1, 2, 3]), plot.KINDCD.isin([0, 4])], ["annual", "periodic"], "other")
    plot["VISIT_NO"] = plot.groupby("KEY").cumcount() + 1
    plot["PREV_YR"] = plot.groupby("KEY").INVYR.shift()
    prev_year = dict(zip(plot.CN, plot.PREV_YR))
    key_first = plot.groupby("KEY").INVYR.min().to_dict()
    log(f"  visits: {len(plot):,}; location keys: {plot.KEY.nunique():,}")

    # dominant condition per visit: accessible forest first, then largest CONDPROP_UNADJ
    cond = q(con, "SELECT PLT_CN, CONDID, COND_STATUS_CD, CONDPROP_UNADJ, FORTYPCD, FLDTYPCD, STDAGE, OWNGRPCD, OWNCD, STDSZCD, "
                  "SITECLCD, DSTRBCD1, TRTCD1, RESERVCD FROM COND")
    cond["_f"] = (cond.COND_STATUS_CD == 1).astype(int)
    dom = cond.sort_values(["PLT_CN", "_f", "CONDPROP_UNADJ"], ascending=[True, False, False]).drop_duplicates("PLT_CN")
    dom = dom.set_index("PLT_CN")
    nforest = cond[cond._f == 1].groupby("PLT_CN").size()
    dist_any = cond[(cond.DSTRBCD1.fillna(0) > 0) | (cond.TRTCD1.fillna(0) > 0)].groupby("PLT_CN").size()
    v = plot.set_index("CN")
    v["FORTYPCD"] = dom.FORTYPCD.where(dom._f == 1).reindex(v.index)
    v["FORTYP_GRP"] = v.FORTYPCD.map(ref.ftgroup)
    v["STDAGE"] = dom.STDAGE.where(dom._f == 1).reindex(v.index)
    v["OWNGRPCD"] = dom.OWNGRPCD.reindex(v.index)
    v["STDSZCD"] = dom.STDSZCD.where(dom._f == 1).reindex(v.index)
    v["N_FOREST_COND"] = nforest.reindex(v.index).fillna(0).astype(int)
    v["DISTURB_OR_TRT"] = dist_any.reindex(v.index).fillna(0).astype(int) > 0

    # trees
    tree = q(con, "SELECT CN, PLT_CN, PREV_TRE_CN, SUBP, TREE, STATUSCD, SPCD, DIA, HT, TPA_UNADJ, VOLCFNET, CARBON_AG, AGENTCD, "
                  "RECONCILECD, MORTYR FROM TREE")
    if cancel and cancel():
        raise datamart.Cancelled()
    tree["INVYR"] = tree.PLT_CN.map(v.INVYR)
    tree["KEY"] = tree.PLT_CN.map(v.KEY)
    tree["DYEAR"] = tree.PLT_CN.map(v.DYEAR)
    tree["BA"] = core.BA_K * tree.DIA ** 2
    tree = tree.sort_values(["DYEAR", "INVYR", "SUBP", "TREE"])
    tree["TID"] = core.root_cns(tree.CN.tolist(), tree.PREV_TRE_CN.tolist())
    B = tree[tree.SUBP <= 4]
    met, sp = stand_metrics(B)
    log(f"  stand metrics: {len(met):,} visits with trees; species rows {len(sp):,}")
    ev = tree_events_vectorized(B, prev_year, key_first)
    log(f"  tree events: {len(ev):,} ({', '.join(f'{k} {n:,}' for k, n in ev.TYPE.value_counts().items())})")
    ivs = ev.assign(N=1).pivot_table(index="PLT_CN", columns="TYPE", values=["N", "TPA", "BA_AC"], aggfunc="sum", fill_value=0)
    ivs.columns = [f"{t.replace(' ', '_').replace('(', '').replace(')', '')}_{m.lower()}" for m, t in ivs.columns]
    ivs = ivs.reset_index()
    tl = tree[["CN", "PLT_CN", "TID"]].rename(columns={"CN": "TRE_CN"})

    # invasives
    inv = q(con, "SELECT PLT_CN, SUBP, VEG_SPCD, COVER_PCT FROM INVASIVE_SUBPLOT_SPP") if _has(con, "INVASIVE_SUBPLOT_SPP") else \
        pd.DataFrame(columns=["PLT_CN", "SUBP", "VEG_SPCD", "COVER_PCT"])
    invs = inv.groupby(["PLT_CN", "VEG_SPCD"]).agg(n_subp=("SUBP", "nunique"), cover_mean=("COVER_PCT", "mean")).reset_index()
    n_inv = invs.groupby("PLT_CN").size()
    v["N_INVASIVE_SPP"] = n_inv.reindex(v.index).fillna(0).astype(int)

    # visit table
    v = v.join(met.set_index("PLT_CN"), how="left")
    visit = v.reset_index().rename(columns={"CN": "PLT_CN"})
    visit["DATE_APPROX"] = visit.DATE_APPROX.astype(int)
    visit["DISTURB_OR_TRT"] = visit.DISTURB_OR_TRT.astype(int)
    visit = visit.drop(columns=["MDATE"])

    # location table
    vv = visit.sort_values(["KEY", "DYEAR"])
    last = vv.drop_duplicates("KEY", keep="last").set_index("KEY")
    first = vv.drop_duplicates("KEY", keep="first").set_index("KEY")
    grp = vv.groupby("KEY")
    loc = pd.DataFrame({
        "STATECD": last.STATECD, "UNITCD": last.UNITCD, "COUNTYCD": last.COUNTYCD, "PLOT": last.PLOT,
        "LAT": last.LAT, "LON": last.LON,
        "COORDS_DIFFER": grp.apply(lambda g: int(g[["LAT", "LON"]].round(6).drop_duplicates().shape[0] > 1)),
        "N_VISITS": grp.size(), "FIRST_DATE": first.DATE, "LAST_DATE": last.DATE, "FIRST_INVYR": first.INVYR, "LAST_INVYR": last.INVYR,
        "LAST_PLT_CN": last.PLT_CN, "PLOT_STATUS_CD": last.PLOT_STATUS_CD, "FORTYPCD": last.FORTYPCD, "FORTYP_GRP": last.FORTYP_GRP,
        "OWNGRPCD": last.OWNGRPCD, "STDAGE": last.STDAGE, "BA": last.ba, "N_CHAINS": grp.CHAIN.nunique(),
        "DESIGNS": grp.DESIGN.apply(lambda s: "+".join(sorted(set(s)))),
        "DESIGNCDS": grp.DESIGNCD.apply(lambda s: ",".join(str(int(x)) for x in sorted(set(s.dropna())))),
        "HAS_INVASIVES": grp.N_INVASIVE_SPP.max().gt(0).astype(int),
        "INV_SURVEYED": grp.INVASIVE_SAMPLING_STATUS_CD.apply(lambda s: int((s == 1).any())),
    })
    loc.index.name = "KEY"

    # inferred periodic predecessor candidates (never database-linked)
    pc = predecessor_candidates(visit, tree, log)
    npc = pc.groupby("KEY").size() if len(pc) else pd.Series(dtype=int)
    loc["N_PRED_CAND"] = npc.reindex(loc.index).fillna(0).astype(int)
    loc = loc.reset_index()
    sps = sp.copy()

    # write
    for name, df in [("visit", visit), ("plot_location", loc), ("visit_species", sps), ("tree_event", ev), ("interval_summary", ivs),
                     ("invasive_summary", invs), ("tree_link", tl), ("predecessor_candidate", pc)]:
        df.to_sql(name, con, if_exists="replace", index=False, chunksize=20000)
    for sql in ["CREATE INDEX ix_visit_key ON visit (KEY)", "CREATE UNIQUE INDEX ix_visit_cn ON visit (PLT_CN)",
                "CREATE UNIQUE INDEX ix_loc_key ON plot_location (KEY)", "CREATE INDEX ix_loc_cty ON plot_location (COUNTYCD, PLOT)",
                "CREATE INDEX ix_vsp ON visit_species (PLT_CN)", "CREATE INDEX ix_ev_key ON tree_event (KEY)",
                "CREATE INDEX ix_ev_plt ON tree_event (PLT_CN)", "CREATE INDEX ix_ivs ON interval_summary (PLT_CN)",
                "CREATE INDEX ix_invs ON invasive_summary (PLT_CN)", "CREATE INDEX ix_tl_plt ON tree_link (PLT_CN)",
                "CREATE INDEX ix_tl_tid ON tree_link (TID)", "CREATE INDEX ix_pc_key ON predecessor_candidate (KEY)"]:
        con.execute(sql)
    con.commit()
    log(f"  derived tables written in {time.time() - t0:.0f}s")
    return {"locations": len(loc), "visits": len(visit), "events": len(ev), "pred_candidates": len(pc),
            "keys_with_candidates": int((loc.N_PRED_CAND > 0).sum())}


def _has(con, t):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone() is not None


def predecessor_candidates(visit, tree, log, max_mi=1.5, tol_yr=0.5):
    """For each location key with national-design (annual) visits: periodic-only keys in the same county within
    max_mi miles (public, fuzzed coordinates) whose last measurement date + the first national visit's REMPER is
    within tol_yr years of the first national visit date. Scored by bridge-tree matching where bridge records exist.
    These are inferred candidates, not database links."""
    nat = visit[visit.DESIGN == "annual"].sort_values("DYEAR").drop_duplicates("KEY")
    nat = nat[nat.REMPER.notna()]
    designs = visit.groupby("KEY").DESIGN.apply(set)
    per_keys = designs[designs.apply(lambda s: s == {"periodic"})].index
    per = visit[visit.KEY.isin(per_keys)].sort_values("DYEAR").drop_duplicates("KEY", keep="last")
    m = nat[["KEY", "PLT_CN", "STATECD", "COUNTYCD", "LAT", "LON", "DYEAR", "DATE", "REMPER", "INVYR"]].merge(
        per[["KEY", "PLT_CN", "STATECD", "COUNTYCD", "LAT", "LON", "DYEAR", "DATE", "INVYR", "PLOT", "FORTYPCD", "STDAGE"]],
        on=["STATECD", "COUNTYCD"], suffixes=("", "_P"))
    m["DIST_MI"] = core.haversine_mi(m.LAT, m.LON, m.LAT_P, m.LON_P)
    m["DT_YR"] = (m.DYEAR_P + m.REMPER) - m.DYEAR
    m = m[(m.DIST_MI <= max_mi) & (m.DT_YR.abs() <= tol_yr)].copy()
    if not len(m):
        return pd.DataFrame(columns=["KEY", "CAND_KEY", "CAND_PLT_CN", "SCORE", "RANK"])
    need = set(m.PLT_CN) | set(m.PLT_CN_P)
    tt = tree[tree.PLT_CN.isin(need)]
    bridge = {k: list(zip(g.SPCD, g.DIA)) for k, g in tt[(tt.SUBP > 4)].groupby("PLT_CN")}
    plive = {k: list(zip(g.SPCD, g.DIA)) for k, g in tt[(tt.STATUSCD == 1) & tt.TPA_UNADJ.notna()].groupby("PLT_CN")}
    rows = []
    for r in m.itertuples():
        br = [(int(s), float(d)) for s, d in bridge.get(r.PLT_CN, []) if not pd.isna(d)]
        pl = [(int(s), float(d)) for s, d in plive.get(r.PLT_CN_P, []) if not pd.isna(d)]
        gap = r.DYEAR - r.DYEAR_P
        pairs = bridge_match(br, pl, gap) if br else []
        frac = len(pairs) / len(br) if br else 0.0
        score = (60 * frac if br else 0) + 25 * (1 - abs(r.DT_YR) / tol_yr) + 15 * (1 - r.DIST_MI / max_mi)
        rows.append({"KEY": r.KEY, "PLT_CN": r.PLT_CN, "CAND_KEY": r.KEY_P, "CAND_PLT_CN": r.PLT_CN_P, "CAND_PLOT": int(r.PLOT),
                     "CAND_LAST_DATE": r.DATE_P, "CAND_INVYR": int(r.INVYR_P), "CAND_FORTYPCD": r.FORTYPCD, "CAND_STDAGE": r.STDAGE,
                     "FIRST_NAT_DATE": r.DATE, "REMPER": r.REMPER, "DIST_MI": round(r.DIST_MI, 3), "DT_YR": round(r.DT_YR, 3),
                     "GAP_YR": round(gap, 2), "N_BRIDGE": len(br), "N_MATCHED": len(pairs),
                     "PAIRS": "; ".join(f"SPCD {s}: {a:.1f} -> {b:.1f} in" for s, a, b in pairs),
                     "SCORE": round(score, 1)})
    pc = pd.DataFrame(rows).sort_values(["KEY", "SCORE"], ascending=[True, False])
    pc["RANK"] = pc.groupby("KEY").cumcount() + 1
    pc["LABEL"] = "inferred candidate, not database-linked"
    log(f"  predecessor candidates: {len(pc):,} for {pc.KEY.nunique():,} location keys")
    return pc


# ================================================================ validation
def validate(con, prev_db=None, log=print):
    """Returns (errors, warnings_needing_confirmation, info). errors block the switch; warnings need confirmation."""
    errors, confirm, info = [], [], {}
    # 1. regression totals
    for key, exp in core.REGRESSION_BA.items():
        got = dict(con.execute("SELECT INVYR, ba FROM visit WHERE KEY = ? ORDER BY INVYR", (key,)).fetchall())
        miss = [y for y in exp if y not in got]
        bad = {y: round(got[y], 2) for y in exp if y in got and int(round(got[y] or 0)) != exp[y]}
        if miss:
            errors.append(f"regression: {key} visit year(s) {miss} missing")
        if bad:
            errors.append(f"regression: {key} live BA changed for {bad}; published {exp}")
        info[f"regression {key}"] = {str(y): round(got.get(y) or 0, 2) for y in exp}
    # 2. key relationships
    rel = {}
    for t in CHILD_CHECK:
        if _has(con, t):
            n = con.execute(f'SELECT COUNT(*) FROM "{t}" c WHERE NOT EXISTS (SELECT 1 FROM PLOT p WHERE p.CN = c.PLT_CN)').fetchone()[0]
            rel[f"{t}.PLT_CN not in PLOT"] = n
            if n:
                errors.append(f"key relationship: {n:,} {t} rows have a PLT_CN missing from PLOT")
    rel["PLOT.PREV_PLT_CN not in PLOT"] = con.execute(
        "SELECT COUNT(*) FROM PLOT c WHERE PREV_PLT_CN IS NOT NULL AND NOT EXISTS (SELECT 1 FROM PLOT p WHERE p.CN = c.PREV_PLT_CN)").fetchone()[0]
    rel["TREE.PREV_TRE_CN not in TREE"] = con.execute(
        "SELECT COUNT(*) FROM TREE c WHERE PREV_TRE_CN IS NOT NULL AND NOT EXISTS (SELECT 1 FROM TREE p WHERE p.CN = c.PREV_TRE_CN)").fetchone()[0]
    rel["TREE.PREV_TRE_CN in a different location key"] = con.execute(
        "SELECT COUNT(*) FROM TREE c JOIN TREE p ON p.CN = c.PREV_TRE_CN JOIN visit a ON a.PLT_CN = c.PLT_CN "
        "JOIN visit b ON b.PLT_CN = p.PLT_CN WHERE a.KEY <> b.KEY").fetchone()[0]
    info["relationships"] = rel
    # 3. row counts against the previous build
    if prev_db and os.path.exists(prev_db):
        pc = sqlite3.connect(f"file:{prev_db}?mode=ro", uri=True)
        old = dict(pc.execute("SELECT table_name, rows FROM manifest").fetchall())
        try:
            orel = json.loads(pc.execute("SELECT value FROM build_info WHERE key='validation'").fetchone()[0])["info"]["relationships"]
        except Exception:
            orel = {}
        pc.close()
        new = dict(con.execute("SELECT table_name, rows FROM manifest").fetchall())
        drops = {}
        for t, n0 in old.items():
            n1 = new.get(t)
            if n1 is None:
                confirm.append(f"row counts: table {t} ({n0:,} rows) is missing from the new build")
            elif n0 and (n0 - n1) / n0 > 0.01:
                confirm.append(f"row counts: {t} dropped {n0 - n1:,} rows ({(n0 - n1) / n0:.1%}) from {n0:,} to {n1:,}")
            drops[t] = [n0, n1]
        info["row_counts_prev_new"] = drops
        for k in ("PLOT.PREV_PLT_CN not in PLOT", "TREE.PREV_TRE_CN not in TREE"):
            if k in orel and rel[k] > orel[k]:
                errors.append(f"key relationship: {k} rose from {orel[k]:,} to {rel[k]:,}")
    else:
        info["row_counts_prev_new"] = "no previous build"
    for e in errors:
        log("  VALIDATION ERROR: " + e)
    for w in confirm:
        log("  NEEDS CONFIRMATION: " + w)
    return errors, confirm, info


# ================================================================ orchestration
def build(name, recs, missing=(), log=print, progress=None, cancel=None, prev_db=None, base_url=None):
    """Build builds/<name> from fetched records {table: manifest record}. Returns the result dict;
    the file is left as <name>.building (not live) and renamed by finish() after validation/tests."""
    store.ensure()
    path = os.path.join(store.BUILDS, name + ".building")
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=OFF"); con.execute("PRAGMA synchronous=OFF"); con.execute("PRAGMA cache_size=-400000")
    con.execute("PRAGMA temp_store=MEMORY")
    T = {"start": time.time()}
    digests = []
    man = []
    order = sorted(recs, key=lambda t: (not t.startswith("REF_"), t))
    for i, t in enumerate(order):
        rec = recs[t]
        if cancel and cancel():
            con.close(); os.remove(path)
            raise datamart.Cancelled()
        if progress:
            progress("load", i, len(order), t)
        st = load_table(con, t, os.path.join(store.DATA, rec["raw_path"]), log, digests, cancel)
        man.append({**{k: rec.get(k) for k in ("file", "url", "status", "last_modified", "etag", "content_length", "sha256",
                                                 "bytes", "raw_path", "download_s", "downloaded_at")}, "table_name": t, **st})
    T["load_s"] = round(time.time() - T["start"], 1)
    if progress:
        progress("metrics", 0, 1, "derived tables")
    pd.DataFrame(digests, columns=["PLT_CN", "tbl", "n", "digest"]).to_sql("plot_digest", con, index=False, chunksize=50000)
    con.execute("CREATE INDEX ix_dig ON plot_digest (PLT_CN)")
    mf = pd.DataFrame(man)
    mf.to_sql("manifest", con, index=False)
    t1 = time.time()
    dstats = derive(con, log, cancel)
    T["derive_s"] = round(time.time() - t1, 1)
    if progress:
        progress("validate", 0, 1, "validation")
    t2 = time.time()
    errors, confirm, vinfo = validate(con, prev_db, log)
    T["validate_s"] = round(time.time() - t2, 1)
    fv = con.execute("SELECT VERSION, DESCR, CREATED_DATE FROM REF_FIADB_VERSION ORDER BY CREATED_DATE DESC LIMIT 1").fetchone() \
        if _has(con, "REF_FIADB_VERSION") else None
    latest = con.execute("SELECT MAX(INVYR) FROM PLOT").fetchone()[0]
    T["total_s"] = round(time.time() - T["start"], 1)
    binfo = {"build_name": name, "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
             "fiadb_version": {"version": fv[0], "descr": fv[1], "created": fv[2]} if fv else None,
             "source_base_url": base_url or datamart.BASE_URL, "missing_tables": list(missing),
             "locations": dstats["locations"], "visits": dstats["visits"], "latest_invyr": latest, "stats": dstats,
             "timings": T, "validation": {"errors": errors, "confirm": confirm, "info": vinfo},
             "code_dictionary": "FIADB User Guide v9.4 (fiasc/codes/fia_codes.json)",
             "python": sys.version.split()[0]}
    con.execute("CREATE TABLE build_info (key TEXT PRIMARY KEY, value TEXT)")
    con.executemany("INSERT INTO build_info VALUES (?, ?)", [(k, json.dumps(v)) for k, v in binfo.items()])
    con.commit()
    con.execute("ANALYZE")
    con.commit()
    con.close()
    binfo["path"] = path
    binfo["db_mb"] = round(os.path.getsize(path) / 2 ** 20, 1)
    return binfo


def set_build_info(path, key, value):
    con = sqlite3.connect(path)
    con.execute("INSERT OR REPLACE INTO build_info VALUES (?, ?)", (key, json.dumps(value)))
    con.commit()
    con.close()


def finish(binfo):
    """Rename <name>.building -> <name> (the file can then be switched to)."""
    final = binfo["path"][: -len(".building")]
    os.replace(binfo["path"], final)
    binfo["path"] = final
    return final

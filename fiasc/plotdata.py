"""Per-plot data for the app's plot page, CSV export and PDF summary (reads one SQLite build).

Everything coded is decoded with fiasc.core.decode (FIADB User Guide v9.4 + REF tables); values missing from the
guide come back flagged (status 'undecoded' / 'no_table'), never guessed.
"""
import re, math, json
import numpy as np
import pandas as pd
from . import core
from .core import decode, dec, nz

AUDIT = {"CREATED_BY", "CREATED_DATE", "CREATED_IN_INSTANCE", "MODIFIED_BY", "MODIFIED_DATE", "MODIFIED_IN_INSTANCE"}
HIDE = AUDIT | {"CN", "PLT_CN", "PREV_PLT_CN", "SRV_CN", "CTY_CN", "STATECD", "UNITCD", "COUNTYCD", "PLOT", "INVYR", "CYCLE", "SUBCYCLE"}
KEY_RE = re.compile(r"^\s*(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(\d{1,3})\s*-\s*(\d{1,6})\s*$")
UNADJ_NOTE = ("Per-acre values are unadjusted single-plot expansions: Σ(value × TPA_UNADJ), no stratum adjustment "
              "(POP_STRATUM.ADJ_FACTOR_*). A sapling on a 6.8-ft microplot represents ~75 trees/ac and a tree ≥5 in on a 24-ft "
              "subplot ~6 trees/ac, so single trees move per-acre values a lot. Periodic (variable-radius) designs are not "
              "comparable with national-design visits.")


def jsonable(df):
    df = df.astype(object).where(df.notna(), None)
    return df.to_dict(orient="records")


def q(con, sql, params=()):
    return pd.read_sql_query(sql, con, params=params)


def has_table(con, t):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone() is not None


def county_names(con):
    try:
        return dict(con.execute("SELECT COUNTYCD, NAME FROM county").fetchall())
    except Exception:
        return {}


# ================================================================ search by plot ID
def resolve_id(con, text):
    """'91-25', '45-3-91-25', 'York 25', or a PLOT CN (also older visit CNs). Returns list of matching keys."""
    t = (text or "").strip()
    if not t:
        return []
    m = KEY_RE.match(t)
    if m:
        key = "-".join(str(int(x)) for x in m.groups())
        return [key] if con.execute("SELECT 1 FROM plot_location WHERE KEY=?", (key,)).fetchone() else []
    m = re.match(r"^\s*(\d{1,3})\s*[-/ ]\s*(\d{1,6})\s*$", t)
    if m:
        return [r[0] for r in con.execute("SELECT KEY FROM plot_location WHERE COUNTYCD=? AND PLOT=? ORDER BY KEY",
                                          (int(m.group(1)), int(m.group(2))))]
    m = re.match(r"^\s*(?:cn\s*)?(\d{6,20})\s*$", t, re.I)
    if m:
        r = con.execute("SELECT KEY FROM visit WHERE PLT_CN=?", (m.group(1),)).fetchone()
        return [r[0]] if r else []
    m = re.match(r"^\s*([A-Za-z][A-Za-z .']+?)\s*[-/ ]?\s*(\d{1,6})\s*$", t)
    if m:
        names = {v.lower(): k for k, v in county_names(con).items()}
        cty = names.get(m.group(1).strip().lower().replace(" county", ""))
        if cty is not None:
            return [r[0] for r in con.execute("SELECT KEY FROM plot_location WHERE COUNTYCD=? AND PLOT=? ORDER BY KEY",
                                              (cty, int(m.group(2))))]
    return []


# ================================================================ header / timeline
def header(con, ref, key):
    loc = q(con, "SELECT * FROM plot_location WHERE KEY=?", (key,))
    if not len(loc):
        return None
    L = loc.iloc[0]
    vis = q(con, "SELECT v.*, p.MICROPLOT_LOC, p.MANUAL AS P_MANUAL, p.PLOT_NONSAMPLE_REASN_CD FROM visit v JOIN PLOT p ON p.CN = v.PLT_CN "
                 "WHERE v.KEY=? ORDER BY v.DYEAR", (key,))
    visits = []
    for r in vis.itertuples():
        visits.append({
            "plt_cn": r.PLT_CN, "invyr": int(r.INVYR), "date": r.DATE, "date_approx": bool(r.DATE_APPROX), "dyear": nz(r.DYEAR, 4),
            "design": r.DESIGN, "kindcd": decode("PLOT.KINDCD", r.KINDCD), "designcd": decode("PLOT.DESIGNCD", r.DESIGNCD),
            "status": decode("PLOT.PLOT_STATUS_CD", r.PLOT_STATUS_CD), "nonsample": decode("PLOT.PLOT_NONSAMPLE_REASN_CD", r.PLOT_NONSAMPLE_REASN_CD),
            "remper": nz(r.REMPER, 1), "prev_plt_cn": r.PREV_PLT_CN, "chain": r.CHAIN, "lat": nz(r.LAT, 6), "lon": nz(r.LON, 6),
            "manual": nz(r.P_MANUAL, 1), "microplot_loc": decode("PLOT.MICROPLOT_LOC", r.MICROPLOT_LOC),
            "fortyp": ref.ftname(r.FORTYPCD) if not pd.isna(r.FORTYPCD) else "", "stdage": nz(r.STDAGE, 0),
            "ba": nz(r.ba, 2), "live_tpa": nz(r.live_tpa, 1), "n_invasive": int(r.N_INVASIVE_SPP or 0),
        })
    pc = q(con, "SELECT * FROM predecessor_candidate WHERE KEY=? ORDER BY RANK", (key,)) if has_table(con, "predecessor_candidate") else pd.DataFrame()
    preds = []
    for r in pc.itertuples():
        pairs = re.sub(r"SPCD (\d+)", lambda m: ref.spname(int(m.group(1))), r.PAIRS or "")
        preds.append({"key": r.CAND_KEY, "plot": int(r.CAND_PLOT), "plt_cn": r.CAND_PLT_CN, "last_date": r.CAND_LAST_DATE,
                      "invyr": int(r.CAND_INVYR), "fortyp": ref.ftname(r.CAND_FORTYPCD) if not pd.isna(r.CAND_FORTYPCD) else "",
                      "stdage": nz(r.CAND_STDAGE, 0), "dist_mi": nz(r.DIST_MI, 2), "dt_yr": nz(r.DT_YR, 2), "remper": nz(r.REMPER, 1),
                      "n_bridge": int(r.N_BRIDGE), "n_matched": int(r.N_MATCHED), "pairs": pairs, "score": nz(r.SCORE, 1),
                      "rank": int(r.RANK), "label": "inferred candidate, not database-linked"})
    # also: is this key itself a candidate predecessor of an annual plot?
    succ = []
    if has_table(con, "predecessor_candidate"):
        for r in q(con, "SELECT KEY, SCORE, RANK, DIST_MI FROM predecessor_candidate WHERE CAND_KEY=? ORDER BY SCORE DESC", (key,)).itertuples():
            succ.append({"key": r.KEY, "score": nz(r.SCORE, 1), "rank": int(r.RANK), "dist_mi": nz(r.DIST_MI, 2)})
    cn = county_names(con)
    return {
        "key": key, "statecd": int(L.STATECD), "unitcd": int(L.UNITCD), "countycd": int(L.COUNTYCD), "plot": int(L.PLOT),
        "county": cn.get(int(L.COUNTYCD), ""), "lat": nz(L.LAT, 6), "lon": nz(L.LON, 6), "coords_differ": bool(L.COORDS_DIFFER),
        "n_visits": int(L.N_VISITS), "designs": L.DESIGNS, "n_chains": int(L.N_CHAINS), "owngrp": decode("COND.OWNGRPCD", L.OWNGRPCD),
        "fortyp": ref.ftname(L.FORTYPCD) if not pd.isna(L.FORTYPCD) else "",
        "fortyp_grp": (f"{int(L.FORTYP_GRP)} = {ref.FGN.get(int(L.FORTYP_GRP), '?')}" if not pd.isna(L.FORTYP_GRP) else ""),
        "visits": visits, "predecessors": preds, "candidate_for": succ,
        "coord_note": "Public coordinates are fuzzed (usually within 0.5 mi, some up to 1 mi) and some private plots are swapped "
                      "within the county; this is not the plot's true location.",
        "unadj_note": UNADJ_NOTE,
    }


# ================================================================ one visit (tabs)
TREE_COLS = ["CN", "PREV_TRE_CN", "SUBP", "TREE", "CONDID", "STATUSCD", "SPCD", "DIA", "DIAHTCD", "HT", "ACTUALHT", "HTCD", "CR", "CCLCD",
             "TREECLCD", "AGENTCD", "DAMAGE_AGENT_CD1", "DAMAGE_AGENT_CD2", "DAMAGE_AGENT_CD3", "DECAYCD", "STANDING_DEAD_CD", "MORTYR",
             "RECONCILECD", "P2A_GRM_FLG", "TPA_UNADJ", "VOLCFNET", "DRYBIO_AG", "CARBON_AG"]


def generic_rows(con, ref, table, plt_cn, order=None, limit=2000):
    if not has_table(con, table):
        return {"available": False, "rows": [], "columns": []}
    df = q(con, f'SELECT * FROM "{table}" WHERE PLT_CN=?' + (f" ORDER BY {order}" if order else "") + f" LIMIT {limit}", (plt_cn,))
    if not len(df):
        return {"available": True, "rows": [], "columns": []}
    cols = [c for c in df.columns if c not in HIDE and not c.endswith("_CN") and df[c].notna().any()]
    rows = []
    for rec in jsonable(df[cols]):
        d = core.decode_row(table, rec, ref)
        rows.append({c: (d[c] if c in d else rec[c]) for c in cols})
    return {"available": True, "columns": cols, "rows": rows}


def visit_detail(con, ref, key, plt_cn):
    v = q(con, "SELECT * FROM visit WHERE PLT_CN=? AND KEY=?", (plt_cn, key))
    if not len(v):
        return None
    V = jsonable(v)[0]
    prow = jsonable(q(con, "SELECT * FROM PLOT WHERE CN=?", (plt_cn,)))[0]
    pdec = core.decode_row("PLOT", prow, ref)
    plot_fields = [{"col": c, "value": pdec.get(c, prow[c])} for c in prow if c not in AUDIT and prow[c] is not None
                   and c not in ("CN", "SRV_CN", "CTY_CN")]
    cond = q(con, "SELECT * FROM COND WHERE PLT_CN=? ORDER BY CONDID", (plt_cn,))
    conds = []
    for rec in jsonable(cond):
        d = core.decode_row("COND", rec, ref)
        conds.append([{"col": c, "value": d.get(c, rec[c])} for c in rec if c not in AUDIT and rec[c] is not None
                      and c not in ("CN", "PLT_CN", "STATECD", "UNITCD", "COUNTYCD", "PLOT", "INVYR")])
    sp = q(con, "SELECT * FROM visit_species WHERE PLT_CN=? ORDER BY ba DESC", (plt_cn,))
    sp["species"] = sp.SPCD.map(ref.spname)
    tot_ba = sp.ba.sum()
    sp["pct_ba"] = sp.ba / tot_ba * 100 if tot_ba else np.nan
    cols = [c for c in TREE_COLS]
    tr = q(con, "SELECT " + ", ".join(cols) + " FROM TREE WHERE PLT_CN=? ORDER BY SUBP, TREE", (plt_cn,))
    tid = dict(con.execute("SELECT TRE_CN, TID FROM tree_link WHERE PLT_CN=?", (plt_cn,)).fetchall())
    trees = []
    for rec in jsonable(tr):
        d = core.decode_row("TREE", rec, ref)
        row = {c: (d[c] if c in d else rec[c]) for c in cols if c not in ("CN", "PREV_TRE_CN")}
        row["linked"] = bool(rec["PREV_TRE_CN"])
        row["tid"] = tid.get(rec["CN"])
        row["ba_ac"] = nz(core.BA_K * rec["DIA"] ** 2 * rec["TPA_UNADJ"], 3) if rec["DIA"] is not None and rec["TPA_UNADJ"] is not None else None
        row["bridge"] = (rec["SUBP"] or 0) > 4
        trees.append(row)
    inv = q(con, "SELECT SUBP, VEG_SPCD, COVER_PCT FROM INVASIVE_SUBPLOT_SPP WHERE PLT_CN=? ORDER BY VEG_SPCD, SUBP", (plt_cn,)) \
        if has_table(con, "INVASIVE_SUBPLOT_SPP") else pd.DataFrame()
    invs = []
    for sym, g in (inv.groupby("VEG_SPCD") if len(inv) else []):
        cn, sci = ref.plant(sym)
        invs.append({"symbol": sym, "name": cn, "sci": sci, "subplots": sorted(int(s) for s in g.SUBP),
                     "cover_mean": nz(g.COVER_PCT.mean(), 1)})
    out = {
        "visit": V, "plot_fields": plot_fields, "conditions": conds,
        "metrics": {k: nz(V.get(k), 3) for k in ["live_n", "live_tpa", "tpa5", "sap_tpa", "ba", "qmd", "vol", "carbon", "dead_n", "dead_tpa",
                                                  "dead_ba", "live_tpa_c1", "live_tpa_c2", "live_tpa_c3", "live_tpa_c4",
                                                  "dead_tpa_c1", "dead_tpa_c2", "dead_tpa_c3", "dead_tpa_c4"]},
        "species": jsonable(sp[["SPCD", "species", "live_n", "live_tpa", "tpa5", "ba", "pct_ba", "vol", "carbon", "dead_n", "dead_tpa"]]),
        "trees": trees,
        "seedlings": generic_rows(con, ref, "SEEDLING", plt_cn, "SUBP, SPCD"),
        "sitetrees": generic_rows(con, ref, "SITETREE", plt_cn, "SPCD"),
        "p2veg_structure": generic_rows(con, ref, "P2VEG_SUBP_STRUCTURE", plt_cn, "SUBP"),
        "p2veg_species": generic_rows(con, ref, "P2VEG_SUBPLOT_SPP", plt_cn, "SUBP"),
        "invasives": invs,
        "invasive_surveyed": decode("PLOT.INVASIVE_SAMPLING_STATUS_CD", prow.get("INVASIVE_SAMPLING_STATUS_CD")),
        "dwm": {t: generic_rows(con, ref, t, plt_cn) for t in ["COND_DWM_CALC", "DWM_VISIT", "DWM_COARSE_WOODY_DEBRIS", "DWM_FINE_WOODY_DEBRIS",
                                                            "DWM_DUFF_LITTER_FUEL", "DWM_MICROPLOT_FUEL", "DWM_RESIDUAL_PILE",
                                                            "DWM_TRANSECT_SEGMENT"]},
        "soils": {t: generic_rows(con, ref, t, plt_cn) for t in ["SOILS_VISIT", "SOILS_SAMPLE_LOC", "SOILS_LAB", "SOILS_EROSION"]},
        "unadj_note": UNADJ_NOTE,
    }
    return out


# ================================================================ history (linked trees, events, growth)
HIST_TREE_COLS = ["CN", "PLT_CN", "PREV_TRE_CN", "SUBP", "TREE", "STATUSCD", "SPCD", "DIA", "HT", "ACTUALHT", "TPA_UNADJ", "VOLCFNET",
                  "CARBON_AG", "AGENTCD", "RECONCILECD", "MORTYR", "CR", "CCLCD"]


def load_history_frames(con, ref, key):
    plot = q(con, "SELECT p.*, v.DESIGN, v.KEY FROM PLOT p JOIN visit v ON v.PLT_CN = p.CN WHERE v.KEY=?", (key,))
    if not len(plot):
        return None
    plot["MEASYEAR"] = plot.MEASYEAR.fillna(plot.INVYR)
    plot = core.prep_plot(plot)
    cns = tuple(plot.CN)
    tree = q(con, f"SELECT {', '.join(HIST_TREE_COLS)} FROM TREE WHERE PLT_CN IN ({','.join('?' * len(cns))})", cns)
    tree = core.prep_tree(tree, plot, ref)
    cond = q(con, f"SELECT * FROM COND WHERE PLT_CN IN ({','.join('?' * len(cns))})", cns)
    return plot, tree, cond


def history(con, ref, key):
    fr = load_history_frames(con, ref, key)
    if fr is None:
        return None
    plot, tree, cond = fr
    YRS = [int(y) for y in plot.INVYR]
    DATE = dict(zip(plot.INVYR.astype(int), plot.DATE))
    out = {"key": key, "years": YRS, "dates": [DATE[y] for y in YRS], "design": dict(zip(map(str, YRS), plot.DESIGN))}
    if not len(tree):
        out.update(empty=True)
        return out
    sp_rank, top, spcol, order = core.species_colours(tree)
    A = core.link_trees(tree, plot)
    A["DATE"] = A.INVYR.astype(int).map(DATE)
    B = A[A.SUBP <= 4].copy()
    spg = lambda s: s if s in top else "Other species"
    B["SPG"] = B.SPNAME.map(spg)
    L = B[B.INPLOT & (B.STATUSCD == 1)].copy()
    L["W_BA"] = L.BA * L.TPA_UNADJ
    L["W_C"] = L.CARBON_AG.fillna(0) * L.TPA_UNADJ / 2000
    L["W_V"] = L.VOLCFNET.fillna(0) * L.TPA_UNADJ

    def by(col):
        t = L.groupby(["INVYR", "SPG"])[col].sum().unstack().reindex(index=YRS, columns=order).fillna(0)
        return {g: [round(float(x), 3) for x in t[g]] for g in order}
    out["species"] = {"order": order, "colors": spcol, "other_n": int(L.loc[L.SPG == "Other species", "SPNAME"].nunique())}
    out["stack"] = {"ba": by("W_BA"), "tpa": by("TPA_UNADJ"), "carbon": by("W_C"), "vol": by("W_V")}
    tot = L.groupby("INVYR").agg(ba=("W_BA", "sum"), tpa=("TPA_UNADJ", "sum"), carbon=("W_C", "sum"), vol=("W_V", "sum")).reindex(YRS).fillna(0)
    out["totals"] = {c: [round(float(x), 3) for x in tot[c]] for c in tot.columns}
    # individual tree histories
    trees = []
    for tid, g in B.groupby("TREE_ID"):
        g = g.sort_values("INVYR")
        entry, fate = core.entry_fate(g, YRS[0])
        trees.append({"id": tid, "sp": g.SPNAME.iloc[-1], "spg": spg(g.SPNAME.iloc[-1]), "entry": entry, "fate": fate,
                      "pts": [{"y": int(r.INVYR), "dia": nz(r.DIA, 1), "ht": nz(r.HT, 0), "st": int(r.STATUSCD)} for r in g.itertuples()]})
    out["trees"] = trees
    # growth
    IV = pd.DataFrame(core.tree_intervals(B))
    if len(IV):
        gs = IV.groupby("sp").agg(n=("gd", "size"), trees=("id", "nunique"), mean=("gd", "mean"), median=("gd", "median"),
                                  lo=("gd", "min"), hi=("gd", "max"), ht=("gh", "mean")).reset_index()
        gs["order"] = gs.sp.map({s: i for i, s in enumerate(sp_rank)})
        out["growth"] = jsonable(gs.sort_values("order").drop(columns="order"))
        out["growth_all"] = {"n": int(len(IV)), "trees": int(IV.id.nunique()), "mean": nz(IV.gd.mean(), 4), "median": nz(IV.gd.median(), 4),
                             "lo": nz(IV.gd.min(), 4), "hi": nz(IV.gd.max(), 4), "ht": nz(IV.gh.mean(), 3)}
    else:
        out["growth"], out["growth_all"] = [], None
    # events: mortality by cause, ingrowth vs other additions (microplot relocation separated)
    EV = pd.DataFrame(core.tree_events(B, YRS))
    mp = plot.MICROPLOT_LOC.tolist() if "MICROPLOT_LOC" in plot else [None] * len(YRS)
    moved = {YRS[i] for i in range(1, len(YRS)) if mp[i] is not None and mp[i - 1] is not None and mp[i] != mp[i - 1]
             and not (pd.isna(mp[i]) or pd.isna(mp[i - 1]))}
    out["microplot_moved"] = sorted(moved)
    if len(EV):
        EV["ivl"] = EV.y0.map(lambda x: "" if x is None or pd.isna(x) else str(int(x))) + "→" + EV.y1.astype(int).astype(str)

        def add_cls(r):
            if r["type"] == "ingrowth":
                return "ingrowth (RECONCILECD 1)"
            if r["type"] == "added (not ingrowth)":
                if r["y1"] in moved and (r["dia"] or 0) < 5:
                    return "microplot relocation addition"
                return "other addition"
            if r["type"] == "removed from sample" and r["y1"] in moved and (r["dia"] or 0) < 5:
                return "microplot relocation drop"
            return r["type"]
        EV["cls"] = EV.apply(add_cls, axis=1)
        out["events"] = jsonable(EV)
    else:
        out["events"] = []
    out["unadj_note"] = UNADJ_NOTE
    return out


# ================================================================ CSV export
def export_rows(con, ref, key):
    fr = load_history_frames(con, ref, key)
    if fr is None:
        return None
    plot, tree, cond = fr
    YRS = [int(y) for y in plot.INVYR]
    DATE = dict(zip(plot.INVYR.astype(int), plot.DATE))
    A = core.link_trees(tree, plot)
    rows = []
    for tid, g in A.groupby("TREE_ID"):
        g = g.sort_values("INVYR")
        entry, fate = core.entry_fate(g, YRS[0])
        for r in g.itertuples():
            rows.append({"plot_key": key, "tree_id": tid, "entry": entry, "fate": fate, "INVYR": int(r.INVYR), "survey_date": DATE[int(r.INVYR)],
                         "SUBP": int(r.SUBP), "TREE": int(r.TREE), "SPCD": nz(r.SPCD), "species": r.SPNAME,
                         "STATUSCD": dec("TREE.STATUSCD", r.STATUSCD), "DIA_in": nz(r.DIA, 1), "HT_ft": nz(r.HT), "TPA_UNADJ": nz(r.TPA_UNADJ, 6),
                         "BA_ft2_per_ac": nz(r.BA * r.TPA_UNADJ, 4) if not pd.isna(r.TPA_UNADJ) else None,
                         "VOLCFNET_ft3_per_ac": nz(r.VOLCFNET * r.TPA_UNADJ, 3) if not pd.isna(r.TPA_UNADJ) and not pd.isna(r.VOLCFNET) else None,
                         "carbon_tons_per_ac": nz(r.CARBON_AG * r.TPA_UNADJ / 2000, 5) if not pd.isna(r.TPA_UNADJ) and not pd.isna(r.CARBON_AG) else None,
                         "AGENTCD": dec("TREE.AGENTCD", r.AGENTCD), "RECONCILECD": dec("TREE.RECONCILECD", r.RECONCILECD),
                         "MORTYR": nz(r.MORTYR), "bridge_record": bool(r.SUBP > 4), "TRE_CN": r.CN, "PREV_TRE_CN": r.PREV_TRE_CN or ""})
    return pd.DataFrame(rows)


def export_visits(con, ref, key):
    v = q(con, "SELECT KEY, PLT_CN, INVYR, DATE, DATE_APPROX, DESIGN, KINDCD, DESIGNCD, PLOT_STATUS_CD, REMPER, FORTYPCD, STDAGE, OWNGRPCD, "
               "live_n, live_tpa, tpa5, sap_tpa, ba, qmd, vol, carbon, dead_n, dead_tpa, dead_ba, N_INVASIVE_SPP FROM visit WHERE KEY=? ORDER BY DYEAR",
          (key,))
    v["KINDCD"] = [dec("PLOT.KINDCD", x) for x in v.KINDCD]
    v["DESIGNCD"] = [dec("PLOT.DESIGNCD", x) for x in v.DESIGNCD]
    v["PLOT_STATUS_CD"] = [dec("PLOT.PLOT_STATUS_CD", x) for x in v.PLOT_STATUS_CD]
    v["FORTYPCD"] = [ref.ftname(x) for x in v.FORTYPCD]
    v["OWNGRPCD"] = [dec("COND.OWNGRPCD", x) for x in v.OWNGRPCD]
    return v

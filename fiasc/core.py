"""Shared FIA logic for the SC plot explorer.

Generalized from plot25_common.py, the shared module of the earlier Plot 25 report/dashboard/PDF:
  * dec(), research_note(), Ref, prep_plot(), prep_tree(), species_colours(), link_trees(), entry_fate(),
    tree_intervals(), tree_events(), nz(), BA_K, PAL and REGRESSION_BA are carried over, with these changes:
    - the code dictionary (FIADB User Guide v9.4) and research notes live in fiasc/codes/;
    - decode() returns a structured result (decoded / undecoded / no code table) so the app can flag codes
      instead of guessing, and decode_row() decodes every coded column of a row;
    - Ref reads the REF_* tables from the SQLite build instead of CSVs;
    - prep_plot() tolerates the missing MEASDAY of periodic plots (date shown to the month, flagged approximate);
    - REGRESSION_BA is keyed by plot location key so other plots can be added.
  * The Plot-25-specific predecessor() is replaced by the statewide candidate search in fiasc/build.py.
"""
import os, json, math, re
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
BA_K = 0.005454154            # ft^2 per in^2 of DBH squared
PAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
OTHER = "#9a9893"
SNAME = {0: "not in sample", 1: "live", 2: "dead", 3: "cut"}
CN_COLS = {"CN", "PLT_CN", "PREV_PLT_CN", "TRE_CN", "PREV_TRE_CN", "CND_CN", "STRATUM_CN", "SRV_CN", "CTY_CN", "SBP_CN",
           "PREV_SBP_CN", "PREV_CND_CN", "PRJ_CN", "EVAL_CN", "EVAL_GRP_CN", "ESTN_UNIT_CN", "TRE_CN_BEGIN", "TRE_CN_MIDPT",
           "PREV_TRE_CN_BEGIN", "DWM_VISIT_CN", "SOILS_VISIT_CN", "INV_CN"}

# Regression values: live BA ft²/ac per visit (INVYR) as published in the Plot 25 report.
REGRESSION_BA = {"45-3-91-25": {2000: 35, 2006: 82, 2011: 82, 2016: 101, 2021: 92}}

# ---------------------------------------------------------------- code dictionary (FIADB User Guide v9.4)
CODES = json.load(open(os.path.join(HERE, "codes", "fia_codes.json"), encoding="utf-8"))
RESEARCH = json.load(open(os.path.join(HERE, "codes", "code_research.json"), encoding="utf-8"))
# coded columns whose code list is not in the guide (entries the dictionary marks as plain numeric measurements are not codes)
UNRESOLVED = {u["col"].split(" ")[0]: u["reason"] for u in CODES.get("unresolved", [])
              if isinstance(u, dict) and "numeric measurement" not in u["reason"]}
UNDECODED = set()
# columns whose code list is shared with a transcribed sibling column in the guide
ALIAS = {}
for _t in ("TREE", "SEEDLING"):
    for _n in (2, 3):
        ALIAS[f"{_t}.DAMAGE_AGENT_CD{_n}"] = f"TREE.DAMAGE_AGENT_CD1"
for _c in ("DAMLOC", "DAMSEV", "DAMTYP"):
    ALIAS[f"TREE.{_c}2"] = f"TREE.{_c}1"
# coded columns decoded from REF tables rather than the guide text
REF_CODED = {"SPCD": "REF_SPECIES", "FORTYPCD": "REF_FOREST_TYPE", "FLDTYPCD": "REF_FOREST_TYPE", "FORTYPCDCALC": "REF_FOREST_TYPE",
             "VEG_SPCD": "REF_PLANT_DICTIONARY"}


def research_note(key, v):
    return RESEARCH.get(key, {}).get(str(v))


def _blank(v):
    return v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and v.strip() == "") or v is pd.NA


def decode(key, v):
    """Structured decode of value v of TABLE.COLUMN key.
    Returns {"code", "text", "status"} with status 'decoded', 'undecoded' (value missing from the guide's list),
    'no_table' (the guide has no code list for this column) or 'blank'. Never guesses."""
    if _blank(v):
        return {"code": None, "text": "", "status": "blank"}
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    ent = CODES.get(key) or CODES.get(ALIAS.get(key, ""))
    if not ent:
        UNDECODED.add((key, str(v)))
        why = UNRESOLVED.get(key, "no code list transcribed from the User Guide")
        return {"code": v, "text": f"{v} (no code table: {why})", "status": "no_table"}
    codes = ent["codes"]
    s = codes.get(str(v))
    if s is None:  # tolerate zero padding differences (e.g. "01" vs "1")
        for k, val in codes.items():
            if k.lstrip("0") == str(v).lstrip("0") and k.strip():
                s = val; break
    if s is None:
        rn = research_note(key, v)
        if rn and rn.get("status") == "decoded" and rn.get("definition"):
            return {"code": v, "text": f"{v} = {rn['definition']} [source: {rn.get('source', 'code_research.json')}]", "status": "decoded"}
        UNDECODED.add((key, str(v)))
        return {"code": v, "text": f"{v} ({rn['label']})" if rn else f"{v} (not in guide)", "status": "undecoded"}
    m = re.match(r"Retired code - .*?MANUAL\s*<\s*([\d.]+)\.\s*(.*)", s)
    if m:
        s = f"{m.group(2)} [retired code, valid for MANUAL <{m.group(1)}]"
    s = s if len(s) <= 140 else s[:137].rsplit(" ", 1)[0] + "..."
    return {"code": v, "text": f"{v} = {s}", "status": "decoded"}


def dec(key, v, short=True):
    """Text form of decode(), same contract as plot25_common.dec()."""
    return decode(key, v)["text"]


def coded_columns(table):
    pre = table + "."
    return sorted({k[len(pre):] for k in list(CODES) + list(ALIAS) if k.startswith(pre)} |
                  {k[len(pre):] for k in UNRESOLVED if k.startswith(pre)})


def decode_row(table, row, ref=None):
    """Decode every coded column of one row (dict). Returns {col: decode-result} for coded columns only."""
    out = {}
    for c in row:
        key = f"{table}.{c}"
        if key in CODES or key in ALIAS or key in UNRESOLVED:
            out[c] = decode(key, row[c])
        elif ref is not None and c in REF_CODED and not _blank(row[c]):
            out[c] = ref.decode_ref(c, row[c])
    return out


# ---------------------------------------------------------------- reference tables
class Ref:
    """Species, forest type (and group) and plant names from the REF_* tables in the SQLite build."""

    def __init__(self, con):
        q = lambda s: pd.read_sql_query(s, con)
        sp = q("SELECT SPCD, COMMON_NAME, GENUS, SPECIES, SFTWD_HRDWD FROM REF_SPECIES")
        sp["SPCD"] = sp.SPCD.astype(int)
        self.SPN = dict(zip(sp.SPCD, sp.COMMON_NAME))
        self.SCI = dict(zip(sp.SPCD, sp.GENUS.fillna("") + " " + sp.SPECIES.fillna("")))
        self.SFT = dict(zip(sp.SPCD, sp.SFTWD_HRDWD))
        ft = q("SELECT VALUE, MEANING, TYPGRPCD FROM REF_FOREST_TYPE")
        self.FTN = dict(zip(ft.VALUE.astype(int), ft.MEANING))
        self.FTG = dict(zip(ft.VALUE.astype(int), ft.TYPGRPCD))
        try:
            fg = q("SELECT VALUE, MEANING FROM REF_FOREST_TYPE_GROUP")
            self.FGN = dict(zip(fg.VALUE.astype(int), fg.MEANING))
        except Exception:
            self.FGN = {}
        self._con = con
        self._plants = {}

    def spname(self, c):
        return "" if _blank(c) else self.SPN.get(int(c), f"SPCD {int(c)} (not in REF_SPECIES)")

    def ftname(self, c):
        return "" if _blank(c) else f"{int(c)} = {self.FTN.get(int(c), '(not in REF_FOREST_TYPE)')}"

    def ftgroup(self, c):
        if _blank(c):
            return None
        return self.FTG.get(int(c))

    def plant(self, sym):
        """SYMBOL -> (common name, scientific name) from REF_PLANT_DICTIONARY (current symbols preferred)."""
        if sym in self._plants:
            return self._plants[sym]
        r = self._con.execute("SELECT COMMON_NAME, SCIENTIFIC_NAME FROM REF_PLANT_DICTIONARY WHERE SYMBOL = ? "
                              "ORDER BY (SYMBOL_TYPE = 'Old') LIMIT 1", (sym,)).fetchone()
        v = ((r[0] or r[1]), r[1] or "") if r else (sym, "")
        self._plants[sym] = v
        return v

    def decode_ref(self, col, v):
        t = REF_CODED[col]
        try:
            if t == "REF_SPECIES":
                ok = int(v) in self.SPN
                return {"code": int(v), "text": f"{int(v)} = {self.spname(v)}", "status": "decoded" if ok else "undecoded"}
            if t == "REF_FOREST_TYPE":
                ok = int(v) in self.FTN
                return {"code": int(v), "text": self.ftname(v), "status": "decoded" if ok else "undecoded"}
            cn, sci = self.plant(v)
            return {"code": v, "text": f"{v} = {cn}" + (f" ({sci})" if sci and sci != cn else ""), "status": "decoded" if sci else "undecoded"}
        except (TypeError, ValueError):
            return {"code": v, "text": f"{v} (not in {t})", "status": "undecoded"}


# ---------------------------------------------------------------- plot & tree preparation
def prep_plot(plot):
    """Sort by INVYR and add MDATE / DYEAR (decimal year of the survey date). Periodic plots often lack MEASDAY:
    the 15th is assumed and DATE_APPROX is set; DATE is the text date (YYYY-MM-DD, or YYYY-MM when approximate)."""
    plot = plot.sort_values("INVYR").copy()
    day = plot.MEASDAY.fillna(15)
    mon = plot.MEASMON.fillna(7)
    plot["DATE_APPROX"] = plot.MEASDAY.isna() | plot.MEASMON.isna()
    plot["MDATE"] = pd.to_datetime(dict(year=plot.MEASYEAR.astype(int), month=mon.astype(int), day=day.astype(int)), errors="coerce")
    plot["DYEAR"] = plot.MDATE.dt.year + (plot.MDATE.dt.day_of_year - 1) / 365.25
    plot["DATE"] = np.where(plot.MEASDAY.isna(),
                            plot.MEASYEAR.astype(int).astype(str) + np.where(plot.MEASMON.isna(), "",
                                                                             "-" + mon.astype(int).astype(str).str.zfill(2)),
                            plot.MDATE.dt.strftime("%Y-%m-%d"))
    return plot


def prep_tree(tree, plot, ref):
    tree = tree.copy()
    tree["INVYR"] = tree.PLT_CN.map(dict(zip(plot.CN, plot.INVYR)))
    tree["SPNAME"] = tree.SPCD.map(ref.spname)
    tree["BA"] = BA_K * tree.DIA ** 2
    tree["INPLOT"] = tree.STATUSCD.isin([1, 2]) & tree.TPA_UNADJ.notna()   # status-0 and P2A-only rows excluded
    tree["SIZE"] = np.where(tree.DIA >= 5, "tree (>=5.0 in, subplot)", "sapling (1.0-4.9 in, microplot)")
    return tree


def species_colours(tree):
    """Fixed species order by total live BA over all visits; top 7 get PAL colours, the rest share OTHER."""
    live_all = tree[tree.INPLOT & (tree.STATUSCD == 1)]
    sp_rank = (live_all.assign(w=live_all.BA * live_all.TPA_UNADJ).groupby("SPNAME").w.sum()
               .sort_values(ascending=False).index.tolist())
    top = sp_rank[:7]
    spcol = {s: PAL[i] for i, s in enumerate(top)}
    spcol["Other species"] = OTHER
    order = top + ["Other species"]
    return sp_rank, top, spcol, order


def link_trees(tree, plot):
    """One identity per physical tree: TID = root CN reached through PREV_TRE_CN; TREE_ID = S{subp}-T{tree}."""
    A = tree.copy()
    A["DYEAR"] = A.PLT_CN.map(dict(zip(plot.CN, plot.DYEAR)))
    A = A.sort_values(["INVYR", "SUBP", "TREE"])
    root = {}
    for r in A.itertuples():
        root[r.CN] = root.get(r.PREV_TRE_CN, r.CN) if isinstance(r.PREV_TRE_CN, str) and r.PREV_TRE_CN else r.CN
    A["TID"] = A.CN.map(root)
    first = A.groupby("TID").first()
    A["TREE_ID"] = A.TID.map(lambda t: f"S{int(first.loc[t, 'SUBP'])}-T{int(first.loc[t, 'TREE'])}"
                             + ("-P2A" if first.loc[t, "SUBP"] > 4 else ""))
    dup = A.groupby("TREE_ID").TID.nunique()
    for tid_label in dup[dup > 1].index:
        for k, t in enumerate(sorted(A.loc[A.TREE_ID == tid_label, "TID"].unique())):
            A.loc[A.TID == t, "TREE_ID"] = f"{tid_label}{'abcdefghijklmnop'[k]}"
    return A


def root_cns(cn, prev):
    """Vectorizable statewide version of the link_trees() root: for arrays of CN and PREV_TRE_CN (records sorted
    so that a record's predecessor comes first, i.e. by INVYR) return the root CN of each record's chain."""
    root = {}
    out = []
    for c, p in zip(cn, prev):
        r = root.get(p, c) if isinstance(p, str) and p else c
        root[c] = r
        out.append(r)
    return out


def entry_fate(g, first_year):
    """Text for how a tree entered the sample and its final state. g = one tree's records, sorted by INVYR."""
    g0 = g.iloc[0]
    if g0.SUBP > 4:
        entry = "periodic-to-annual GRM record only (P2A_GRM_FLG); not a tallied tree"
    elif g0.INVYR == first_year:
        entry = f"tallied at first visit ({first_year})"
    else:
        entry = f"new in {int(g0.INVYR)}: {dec('TREE.RECONCILECD', g0.RECONCILECD)}"
    last = g.iloc[-1]
    if last.STATUSCD == 1:
        fate = f"live at {int(last.INVYR)}"
    elif last.STATUSCD == 0:
        fate = f"left sample {int(last.INVYR)}: {dec('TREE.RECONCILECD', last.RECONCILECD)}"
    elif last.STATUSCD == 3:
        fate = f"cut by {int(last.INVYR)}"
    else:
        dfirst = g[g.STATUSCD == 2].iloc[0]
        fate = (f"dead by {int(dfirst.INVYR)} (MORTYR {'' if pd.isna(dfirst.MORTYR) else int(dfirst.MORTYR)}; "
                f"AGENTCD {dec('TREE.AGENTCD', dfirst.AGENTCD)})")
    return entry, fate


def nz(v, nd=None):
    """JSON-safe number (None for NaN)."""
    if v is None or (isinstance(v, float) and math.isnan(v)) or pd.isna(v):
        return None
    v = float(v)
    return round(v, nd) if nd is not None else v


def tree_intervals(B):
    """One record per tree per consecutive live->live remeasurement. B = linked TREE rows (SUBP <= 4) with
    TREE_ID, DYEAR and DATE. Rates use the actual survey dates, not INVYR."""
    iv = []
    for tid, g in B.groupby("TREE_ID"):
        g = g.sort_values("INVYR")
        for a, b in zip(g.iloc[:-1].itertuples(), g.iloc[1:].itertuples()):
            if a.STATUSCD == 1 and b.STATUSCD == 1:
                yrs = b.DYEAR - a.DYEAR
                if not yrs or pd.isna(yrs):
                    continue
                iv.append({"id": tid, "sp": b.SPNAME, "subp": int(b.SUBP), "y0": int(a.INVYR), "y1": int(b.INVYR),
                           "d0": a.DATE, "d1": b.DATE, "yrs": round(yrs, 3), "dia0": nz(a.DIA, 1), "dia1": nz(b.DIA, 1),
                           "gd": round((b.DIA - a.DIA) / yrs, 4),
                           "gh": None if pd.isna(a.HT) or pd.isna(b.HT) else round((b.HT - a.HT) / yrs, 3),
                           "gba": round((b.BA - a.BA) / yrs, 5),
                           "gba_ac": nz((b.BA - a.BA) / yrs * a.TPA_UNADJ, 4)})
    return iv


def tree_events(B, YRS):
    """Mortality (live -> first dead; per acre from the last live record), dead at first tally,
    ingrowth (RECONCILECD 1) / other additions, and removals from the sample (STATUSCD 0).
    Cut trees (live -> STATUSCD 3) are reported as type 'cut'."""
    ev = []
    for tid, g in B.groupby("TREE_ID"):
        g = g.sort_values("INVYR")
        d2 = g[g.STATUSCD == 2]
        if len(d2):
            q = d2.iloc[0]
            pl = g[(g.INVYR < q.INVYR) & (g.STATUSCD == 1)]
            cause = dec("TREE.AGENTCD", q.AGENTCD) or "no AGENTCD recorded"
            if len(pl):
                p_ = pl.iloc[-1]
                ev.append({"type": "mortality", "y0": int(p_.INVYR), "y1": int(q.INVYR), "id": tid, "sp": q.SPNAME,
                           "subp": int(q.SUBP), "dia": nz(p_.DIA, 1), "cause": cause, "agentcd": nz(q.AGENTCD),
                           "mortyr": None if pd.isna(q.MORTYR) else int(q.MORTYR),
                           "tpa": nz(p_.TPA_UNADJ, 3), "ba_ac": nz(p_.BA * p_.TPA_UNADJ, 4)})
            else:
                prev = [y for y in YRS if y < q.INVYR]
                ev.append({"type": "dead at first tally", "y0": prev[-1] if prev else None, "y1": int(q.INVYR), "id": tid,
                           "sp": q.SPNAME, "subp": int(q.SUBP), "dia": nz(q.DIA, 1), "cause": cause, "agentcd": nz(q.AGENTCD),
                           "mortyr": None if pd.isna(q.MORTYR) else int(q.MORTYR), "rctxt": dec("TREE.RECONCILECD", q.RECONCILECD),
                           "tpa": nz(q.TPA_UNADJ, 3), "ba_ac": nz(q.BA * q.TPA_UNADJ, 4)})
        d3 = g[g.STATUSCD == 3]
        if len(d3):
            q = d3.iloc[0]
            pl = g[(g.INVYR < q.INVYR) & (g.STATUSCD == 1)]
            if len(pl):
                p_ = pl.iloc[-1]
                ev.append({"type": "cut", "y0": int(p_.INVYR), "y1": int(q.INVYR), "id": tid, "sp": q.SPNAME, "subp": int(q.SUBP),
                           "dia": nz(p_.DIA, 1), "cause": dec("TREE.AGENTCD", q.AGENTCD) or "no AGENTCD recorded",
                           "agentcd": nz(q.AGENTCD), "mortyr": None,
                           "tpa": nz(p_.TPA_UNADJ, 3), "ba_ac": nz(p_.BA * p_.TPA_UNADJ, 4)})
        g0 = g.iloc[0]
        if g0.INVYR > YRS[0] and g0.STATUSCD == 1:
            typ = "ingrowth" if g0.RECONCILECD == 1 else "added (not ingrowth)"
            prev = [y for y in YRS if y < g0.INVYR][-1]
            ev.append({"type": typ, "y0": prev, "y1": int(g0.INVYR), "id": tid, "sp": g0.SPNAME, "subp": int(g0.SUBP),
                       "dia": nz(g0.DIA, 1), "cause": dec("TREE.RECONCILECD", g0.RECONCILECD) or "no RECONCILECD recorded",
                       "rc": nz(g0.RECONCILECD), "mortyr": None,
                       "tpa": nz(g0.TPA_UNADJ, 3), "ba_ac": nz(g0.BA * g0.TPA_UNADJ, 4)})
        for q in g[g.STATUSCD == 0].itertuples():
            prevs = [y for y in YRS if y < q.INVYR]
            before = g[g.INVYR < q.INVYR]
            if not prevs or not len(before):
                continue
            pl = before.iloc[-1]
            ev.append({"type": "removed from sample", "y0": prevs[-1], "y1": int(q.INVYR), "id": tid, "sp": q.SPNAME,
                       "subp": int(q.SUBP), "dia": nz(pl.DIA, 1), "cause": dec("TREE.RECONCILECD", q.RECONCILECD), "mortyr": None,
                       "rc": nz(q.RECONCILECD),
                       "tpa": nz(pl.TPA_UNADJ, 3), "ba_ac": nz(pl.BA * pl.TPA_UNADJ, 4) if not pd.isna(pl.TPA_UNADJ) else None})
    return ev


def haversine_mi(lat0, lon0, lat1, lon1):
    lat0, lon0, lat1, lon1 = map(np.radians, (lat0, lon0, lat1, lon1))
    a = np.sin((lat1 - lat0) / 2) ** 2 + np.cos(lat0) * np.cos(lat1) * np.sin((lon1 - lon0) / 2) ** 2
    return 3958.8 * 2 * np.arcsin(np.sqrt(a))


def plot_key(statecd, unitcd, countycd, plot):
    return f"{int(statecd)}-{int(unitcd)}-{int(countycd)}-{int(plot)}"

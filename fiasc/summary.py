"""Plot summary shared by the static site's plot page (scripts/export_static.py) and the PDF summary (summary_pdf.py).

Ported from the Plot 25 summary PDF (build_pdf.py / plot25_common.py of the earlier Plot 25 work) and generalised to any
plot: the same stand totals (stand()), survey and tree-total rows, species tables, highlight rules and caveats.

Trees counted in totals: STATUSCD 1 (live) or 2 (standing dead) with a TPA_UNADJ. On national-design visits this is
exactly subplots 1-4 (bridge records on SUBP > 4 carry no TPA_UNADJ); on periodic visits it is the tallied points
(SUBP 101-105), and remeasurement-only records (SUBP 9xx, no TPA_UNADJ) are not counted, as in the Plot 25 PDF.

compute(...) -> dict for one plot; finish(S, pred, pc) adds what depends on the inferred predecessor. Everything returned
is plain JSON (numbers rounded for display only where noted; totals keep 4 decimals so the page shows the PDF's values).
"""
import math
import numpy as np
import pandas as pd
from . import core
from .core import dec

BA_K = core.BA_K
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
TOL = 0.011                                        # same tolerance as the PDF's check against the report / database
EVT = {"mort": "mortality", "dft": "dead at first tally", "cut": "cut", "ing": "ingrowth", "add": "added (not ingrowth)", "rem": "removed from sample"}


class SummaryError(Exception):
    pass


def r4(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) or pd.isna(v) else round(float(v), 4)


def short(s):
    return s.split(" = ", 1)[-1] if s else ""


def cause_word(code):
    """'20 = Disease.' -> 'disease' (as in the PDF's mortality bullet)."""
    t = dec("TREE.AGENTCD", code) if code is not None and not pd.isna(code) else ""
    return short(t).split(" (")[0].rstrip(".").lower() if t else "no cause recorded"


def survey_label(row):
    if getattr(row, "DATE_APPROX", 0) and not pd.isna(getattr(row, "MEASMON", np.nan)):
        return f"{MON[int(row.MEASMON) - 1]} {int(row.MEASYEAR)}"
    return str(row.DATE)


def stand(live, dead):
    """build_pdf.stand: per-acre totals of one visit from its live and standing-dead tree records."""
    tpa = live.TPA_UNADJ.sum()
    return {"tpa5": live.loc[live.DIA >= 5, "TPA_UNADJ"].sum(), "sap": live.loc[live.DIA < 5, "TPA_UNADJ"].sum(), "tpa": tpa,
            "ba": (BA_K * live.DIA ** 2 * live.TPA_UNADJ).sum(),
            "qmd": math.sqrt((live.DIA ** 2 * live.TPA_UNADJ).sum() / tpa) if tpa else float("nan"),
            "vol": (live.VOLCFNET.fillna(0) * live.TPA_UNADJ).sum() if len(live) else 0.0,
            "c": (live.CARBON_AG.fillna(0) * live.TPA_UNADJ).sum() / 2000 if len(live) else 0.0,
            "n_live": len(live), "n_dead": len(dead), "dead_tpa": dead.TPA_UNADJ.sum()}


def compute(vis, tree, ev, gi, cond, inv, pfr, ref, validate=True):
    """vis: visit rows of one location key ordered by DYEAR (visit table + MICROPLOT_LOC); tree: its TREE rows with vi, TID;
    ev: its tree_event rows; gi: growth intervals (build.growth_intervals); cond: COND rows with vi; inv: INVASIVE_SUBPLOT_SPP
    rows with vi; pfr: PLOT rows with vi. Any of tree/ev/gi/cond/inv may be None."""
    E = lambda df: df if df is not None else pd.DataFrame()
    tree, ev, gi, cond, inv, pfr = E(tree), E(ev), E(gi), E(cond), E(inv), E(pfr)
    vis = vis.reset_index(drop=True)
    YRS = [int(y) for y in vis.INVYR]
    nv = len(vis)
    if len(tree):
        T = tree.copy()
        T["BA"] = BA_K * T.DIA ** 2
        T["W"] = T.BA * T.TPA_UNADJ
        inplot = T.STATUSCD.isin([1, 2]) & T.TPA_UNADJ.notna()
        L, DD = T[inplot & (T.STATUSCD == 1)], T[inplot & (T.STATUSCD == 2)]
    else:
        T = L = DD = pd.DataFrame(columns=["vi", "DIA", "TPA_UNADJ", "VOLCFNET", "CARBON_AG", "SPCD", "TID", "W", "BA", "STATUSCD", "SUBP"])
    evy = {i: ev[ev.Y1 == y] if len(ev) else ev for i, y in enumerate(YRS)}
    V = []
    for i, r in enumerate(vis.itertuples()):
        lv, dv = L[L.vi == i], DD[DD.vi == i]
        s = stand(lv, dv)
        e = evy[i]
        cnt = lambda typ: int((e.TYPE == typ).sum()) if len(e) else 0
        V.append({
            "y": YRS[i], "d": survey_label(r), "da": int(r.DATE_APPROX or 0), "ds": r.DESIGN,
            "age": r4(r.STDAGE), "ft": r4(r.FORTYPCD),
            "tpa5": r4(s["tpa5"]), "sap": r4(s["sap"]), "tpa": r4(s["tpa"]), "ba": r4(s["ba"]), "qmd": r4(s["qmd"]),
            "vol": r4(s["vol"]), "c": r4(s["c"]), "nl": s["n_live"], "n5": int((lv.DIA >= 5).sum()), "ns": int((lv.DIA < 5).sum()),
            "nd": s["n_dead"], "dtpa": r4(s["dead_tpa"]),
            "newd": cnt(EVT["mort"]) + cnt(EVT["dft"]), "ing": cnt(EVT["ing"]), "add": cnt(EVT["add"]),
            "cut": int(((T.vi == i) & (T.STATUSCD == 3)).sum()) if len(T) else 0,
        })
        # validation: national-design totals must equal the database's per-visit metrics (as summary_pdf / build_pdf check)
        if validate and r.DESIGN == "annual" and len(lv):
            for k, col in (("tpa", "live_tpa"), ("ba", "ba"), ("qmd", "qmd"), ("vol", "vol"), ("c", "carbon")):
                a, b = s[k], getattr(r, col)
                a = 0.0 if a is None or (isinstance(a, float) and math.isnan(a)) else a
                b = 0.0 if b is None or pd.isna(b) else b
                if abs(a - b) > TOL:
                    raise SummaryError(f"{r.KEY} {YRS[i]} {k}: summary {a:.3f} vs database {b:.3f}")
    S = {"v": V}
    # ---------------------------------------------------------------- species tables (PDF: BA_SP, TPA5, PCT, volume/carbon by species)
    if len(L):
        rank = L.groupby("SPCD").W.sum().sort_values(ascending=False, kind="mergesort")
        sp = [int(s) for s in rank.index]
        grid = lambda df, val: df.assign(_v=val).groupby(["SPCD", "vi"])._v.sum().unstack().reindex(index=sp, columns=range(nv)).fillna(0)
        BA = grid(L, L.W); TP5 = grid(L[L.DIA >= 5], L.loc[L.DIA >= 5, "TPA_UNADJ"])
        VO = grid(L, L.VOLCFNET.fillna(0) * L.TPA_UNADJ); CA = grid(L, L.CARBON_AG.fillna(0) * L.TPA_UNADJ / 2000)
        tot = BA.sum()
        PCT = BA / tot.replace(0, np.nan) * 100
        js = lambda df: [[r4(x) for x in row] for row in df.values]
        S["sp"] = {"codes": sp, "ba": js(BA), "tpa5": js(TP5), "vol": js(VO), "c": js(CA), "pct": js(PCT)}
        S["top"] = sp[:7]
    else:
        S["sp"] = None
        BA = PCT = None
        sp = []
    # ---------------------------------------------------------------- facts used by highlights and caveats
    live_i = [i for i, v in enumerate(V) if v["nl"]]
    S["kpi"] = None
    hl = []
    if live_i:
        a, z = live_i[0], live_i[-1]
        pk = max(live_i, key=lambda i: V[i]["ba"])
        S["kpi"] = {"a": a, "z": z, "pk": pk}
        hl.append(["Basal area", f"Live basal area went from {V[a]['ba']:.0f} ft²/ac in {YRS[a]} to {V[z]['ba']:.0f} in {YRS[z]}"
                   + (f" (peak {V[pk]['ba']:.0f} in {YRS[pk]})." if pk not in (a, z) else ".")])
        span = float(vis.DYEAR.iloc[z] - vis.DYEAR.iloc[a])
        rate = f" ({(V[z]['c'] - V[a]['c']) / span:.2f} tons C/ac per year)" if span > 0 and z != a else ""
        hl.append(["Carbon and volume", f"Live aboveground carbon went from {V[a]['c']:.1f} to {V[z]['c']:.1f} tons C/ac{rate}; net cubic volume "
                   f"from {V[a]['vol']:,.0f} to {V[z]['vol']:,.0f} ft³/ac."])
    M = ev[ev.TYPE == EVT["mort"]] if len(ev) else pd.DataFrame()
    if len(M):
        last_y1 = int(M.Y1.max())
        lm = M[M.Y1 == last_y1]
        g = lm.groupby("SPCD").BA_AC.sum().sort_values(ascending=False, kind="mergesort")
        s0 = int(g.index[0]); sub = lm[lm.SPCD == s0]
        y0 = int(sub.Y0.iloc[0])
        nm = ref.spname(s0)
        causes = ", ".join(sorted({cause_word(c) for c in sub.AGENTCD}))
        # Y0 is the tree's last live inventory year, which need not be a survey at this key (e.g. a re-keyed visit)
        i0 = YRS.index(y0) if y0 in YRS else None
        i1 = YRS.index(last_y1) if last_y1 in YRS else None
        big = sub.DIA.max()
        lv0 = L[L.vi == i0] if i0 is not None else L.iloc[0:0]
        largest = len(lv0) and abs(lv0.DIA.max() - big) < 1e-9
        both = BA is not None and s0 in BA.index and i0 is not None and i1 is not None
        hl.append(["Largest recent loss", f"Between {y0} and {last_y1}, {len(sub)} {nm} tree{'s' if len(sub) > 1 else ''} died ({causes}), removing "
                   f"{sub.BA_AC.sum():.1f} ft²/ac of basal area; the largest was {big:.1f} in at its last live measurement"
                   + (f", the largest live tree on the plot in {y0}" if largest else "") + "."
                   + (f" {nm[:1].upper() + nm[1:]} basal area went from {BA.loc[s0, i0]:.1f} to {BA.loc[s0, i1]:.1f} ft²/ac." if both else "")])
    if PCT is not None and len(live_i) >= 2:
        a, z = live_i[0], live_i[-1]
        d = (PCT[z].fillna(0) - PCT[a].fillna(0)).sort_values(ascending=False, kind="mergesort")
        up = [s for s in d.index if d[s] > 0.5][:3]
        dn = d.sort_values(kind="mergesort").index[0] if len(d) and d.min() < -0.5 else None
        parts = []
        if up:
            parts.append("largest increases in share of live basal area: " + ", ".join(
                f"{ref.spname(s)} ({PCT.loc[s, a] if not pd.isna(PCT.loc[s, a]) else 0:.0f}% → {PCT.loc[s, z]:.0f}%)" for s in up))
        if dn is not None:
            parts.append(f"largest decrease: {ref.spname(dn)} ({PCT.loc[dn, a]:.0f}% → {0 if pd.isna(PCT.loc[dn, z]) else PCT.loc[dn, z]:.0f}%)")
        if parts:
            txt = "; ".join(parts)
            hl.append([f"Composition, {YRS[a]}→{YRS[z]}", txt[:1].upper() + txt[1:] + "."])
    if len(M):
        cz = M.groupby(M.AGENTCD.map(cause_word)).size().sort_values(ascending=False, kind="mergesort")
        ncut = int((ev.TYPE == EVT["cut"]).sum())
        dist = []
        if len(cond):
            for c in ("DSTRBCD1", "DSTRBCD2", "DSTRBCD3", "TRTCD1", "TRTCD2", "TRTCD3"):
                if c in cond:
                    for vi_, val in zip(cond.vi, cond[c]):
                        if not pd.isna(val) and int(val) > 0:
                            dist.append(f"{YRS[int(vi_)]} {c} {dec('COND.' + c, val)}")
        tail = (f" No tree was recorded cut and no disturbance or treatment was recorded from {YRS[0]} on." if not ncut and not dist else
                (f" {ncut} tree{'s were' if ncut > 1 else ' was'} recorded cut." if ncut else "") +
                (" Recorded disturbance or treatment: " + "; ".join(dist[:4]) + ("…" if len(dist) > 4 else "") + "." if dist else ""))
        hl.append(["Mortality", f"{len(M)} tree{'s' if len(M) > 1 else ''} died between surveys: " + ", ".join(f"{n} {c}" for c, n in cz.items()) + "." + tail])
    if len(gi):
        gs = gi.groupby("SPCD").gd.agg(["size", "mean"])
        for nmin in (5, 3):
            ok = gs[gs["size"] >= nmin]
            if len(ok):
                s = int(ok["mean"].idxmax())
                hl.append(["Growth", f"The fastest-growing species with ≥{nmin} remeasurement intervals was {ref.spname(s)} ({ok['mean'].max():.2f} in/yr). "
                           f"The plot average was {gi.gd.mean():.2f} in/yr over {len(gi)} intervals."])
                break
    if len(inv):
        surveyed = sorted(int(v) for v, s in zip(pfr.vi, pfr.INVASIVE_SAMPLING_STATUS_CD) if s == 1) if len(pfr) and "INVASIVE_SAMPLING_STATUS_CD" in pfr else []
        first = inv.groupby("VEG_SPCD").vi.min().sort_values(kind="mergesort")
        names = {s: ref.plant(s)[0] for s in first.index}
        txt = "; ".join(f"{names[s]} first detected {YRS[int(v)]}" for s, v in first.items())
        full = [names[s] for s in first.index if surveyed and all(inv[(inv.VEG_SPCD == s) & (inv.vi == v)].SUBP.nunique() >= 4 for v in surveyed)]
        if full:
            lst = " and ".join(full) if len(full) <= 2 else ", ".join(full)
            txt += f". {lst[:1].upper() + lst[1:]} {'was' if len(full) == 1 else 'were'} on all four subplots at every invasive survey"
        hl.append(["Invasives", txt[:1].upper() + txt[1:] + "."])
    S["hl"] = hl
    # ---------------------------------------------------------------- basal-area drops between consecutive surveys (Species section)
    drops = []
    for i in range(1, nv):
        b0, b1 = V[i - 1]["ba"] or 0, V[i]["ba"] or 0
        if not (V[i - 1]["nl"] and V[i]["nl"]) or b1 >= b0 - 0.05 or V[i]["ds"] != V[i - 1]["ds"]:
            continue
        t0 = L[L.vi == i - 1].set_index("TID"); t1 = L[L.vi == i].set_index("TID")
        both = t0.index.intersection(t1.index)
        cross = [t for t in both if t0.loc[t, "DIA"] < 5 <= t1.loc[t, "DIA"]]
        other = [t for t in both if t not in cross]
        gone = t0.index.difference(t1.index); new = t1.index.difference(t0.index)
        e = evy[i]
        died = e[e.TYPE == EVT["mort"]] if len(e) else e
        d_died = -float(t0.loc[t0.index.intersection(died.TID), "W"].sum()) if len(died) else 0.0
        d_gone_other = -float(t0.loc[gone, "W"].sum()) - d_died
        d_cross = float((t1.loc[cross, "W"] - t0.loc[cross, "W"]).sum())
        d_other = float((t1.loc[other, "W"] - t0.loc[other, "W"]).sum())
        d_new = float(t1.loc[new, "W"].sum())
        parts = []
        if len(died):
            by = died.groupby("SPCD").size().sort_values(ascending=False, kind="mergesort")
            parts.append(f"trees that died {d_died:+.1f} ({', '.join(f'{n} {ref.spname(s)}' for s, n in by.items())})")
        if abs(d_gone_other) >= 0.05:
            parts.append(f"trees cut or no longer in the sample {d_gone_other:+.1f}")
        if cross:
            tp0 = sorted({round(float(t0.loc[t, "TPA_UNADJ"]), 0) for t in cross}); tp1 = sorted({round(float(t1.loc[t, "TPA_UNADJ"]), 0) for t in cross})
            parts.append(f"{len(cross)} sapling{'s' if len(cross) > 1 else ''} crossing 5.0 in {d_cross:+.1f} (each tree's per-acre weight fell from "
                         f"{'/'.join(f'{x:.0f}' for x in tp0)} to {'/'.join(f'{x:.0f}' for x in tp1)} trees/ac)")
        parts.append(f"growth of the other surviving trees {d_other:+.1f}")
        if d_new:
            parts.append(f"new trees {d_new:+.1f}")
        drops.append(f"Live basal area fell from {b0:.1f} to {b1:.1f} ft²/ac between {YRS[i - 1]} and {YRS[i]} ({b1 - b0:+.1f}). "
                     f"Contributions in ft²/ac: " + "; ".join(parts) + ".")
    S["drops"] = drops
    # ---------------------------------------------------------------- caveats that apply to this plot
    cav = []
    mp = list(vis.MICROPLOT_LOC) if "MICROPLOT_LOC" in vis else [None] * nv
    for i in range(1, nv):
        if mp[i] is not None and mp[i - 1] is not None and not pd.isna(mp[i]) and not pd.isna(mp[i - 1]) and mp[i] != mp[i - 1]:
            e = evy[i]
            n8 = int(((e.TYPE == EVT["rem"]) & (e.RECONCILECD == 8)).sum()) if len(e) else 0
            n3 = int(((e.TYPE == EVT["add"]) & (e.RECONCILECD == 3)).sum()) if len(e) else 0
            loc = lambda v: (short(dec("PLOT.MICROPLOT_LOC", v)).rstrip(".") or str(v))
            cav.append(["Microplot moved in " + str(YRS[i]),
                        f"MICROPLOT_LOC {mp[i - 1]} in {YRS[i - 1]} ({loc(mp[i - 1]).lower()}) changed to {mp[i]} in {YRS[i]} ({loc(mp[i]).lower()}), "
                        f"so saplings were tallied on different microplots: {n8} sapling{'s were' if n8 != 1 else ' was'} dropped (RECONCILECD 8) and "
                        f"{n3} added (RECONCILECD 3). "
                        f"The {YRS[i - 1]}→{YRS[i]} sapling change is a sampling artefact."])
    ann = L[L.vi.isin([i for i, v in enumerate(V) if v["ds"] == "annual"])] if len(L) else L
    if len(ann):
        sap_t = ann.loc[ann.DIA < 5, "TPA_UNADJ"].round(2).mode(); tre_t = ann.loc[ann.DIA >= 5, "TPA_UNADJ"].round(2).mode()
        if len(sap_t) and len(tre_t):
            st, tt = float(sap_t.iloc[0]), float(tre_t.iloc[0])
            cav.append(["Unadjusted per-acre values", f"All per-acre numbers are Σ(value × TPA_UNADJ) for this single plot, with no stratum adjustment. "
                        f"A sapling represents {st:.2f} trees/ac and a tree ≥5 in {tt:.2f} trees/ac, so a 4.9-in sapling counts "
                        f"{BA_K * 4.9 ** 2 * st:.1f} ft²/ac of basal area and the same tree at 5.0 in counts {BA_K * 25 * tt:.1f} ft²/ac."])
    if any(v["ds"] == "periodic" for v in V):
        cav.append(["Periodic design", "Periodic visits used variable-radius points or other pre-annual designs; each tree's TPA_UNADJ depends on its "
                    "diameter, and per-acre values are not comparable with national-design visits."])
    if len(tree):
        nb = tree[(tree.SUBP > 4) & tree.TPA_UNADJ.isna() & tree.vi.isin([i for i, v in enumerate(V) if v["ds"] == "annual"])]
        if len(nb):
            cav.append(["Bridge records", f"{len(nb)} record{'s' if len(nb) > 1 else ''} on SUBP > 4 at national-design visits "
                        f"(periodic-to-annual bridge records, P2A_GRM_FLG = Y) {'are' if len(nb) > 1 else 'is'} excluded from all totals."])
    S["cav"] = cav
    S["und"] = sorted(undecoded(tree, cond, pfr))
    return S


def undecoded(tree, cond, pfr):
    out = set()
    for tab, df in (("TREE", tree), ("COND", cond), ("PLOT", pfr)):
        if df is None or not len(df):
            continue
        for c in core.coded_columns(tab):
            if c in df:
                for v in df[c].dropna().unique():
                    d = core.decode(f"{tab}.{c}", v)
                    if d["status"] == "undecoded":
                        out.add(f"{tab}.{c} {int(v) if isinstance(v, float) and v.is_integer() else v}")
    return out


def finish(S, P0, pred, pc, vis):
    """Add the inferred predecessor (rank-1 candidate pc, its summary pred) to S: survey rows, highlight and caveat."""
    if pred is None or pc is None:
        S.pop("und_pred", None)
        return S
    S["pred"] = {"key": pc["key"], "plot": pc["plot"], "v": pred["v"]}
    pv = pred["v"]
    if pv:
        f0, fl = pv[0], pv[-1]
        parts = [f"{f0['d']}" + (f" ({f0['age']:.0f}-year-old stand, FORTYPCD {int(f0['ft'])})" if f0["age"] is not None and f0["ft"] is not None else "")]
        if len(pv) > 1:
            parts.append(f"{fl['d']}" + (f" ({fl['age']:.0f}-year-old stand, FORTYPCD {int(fl['ft'])})" if fl["age"] is not None and fl["ft"] is not None else ""))
        cut = sum(v["cut"] for v in pv)
        S["hl"].insert(0, ["Inferred predecessor", f"Periodic plot {pc['plot']} (key {pc['key']}; inferred, not database-linked) was measured in "
                           + " and ".join(parts) + "."
                           + (f" {cut} tree{'s were' if cut > 1 else ' was'} recorded cut (STATUSCD 3) by the {fl['d']} visit." if cut else "")])
        first = vis.iloc[0]
        ev = []
        if pd.isna(first.PREV_PLT_CN):
            ev.append("PREV_PLT_CN and PREV_TRE_CN are blank: the User Guide (§2.4.4) says PREV_PLT_CN does not link to a periodic record.")
        if pc.get("rp") is not None:
            back = float(first.DYEAR) - pc["rp"]
            ev.append(f"The {int(first.INVYR)} visit's REMPER is {pc['rp']:.1f} yr, pointing back to about {MON[min(11, int((back % 1) * 12))]} {int(back)}; "
                      f"plot {pc['plot']} was last measured {fl['d']}.")
        if fl["age"] is not None and not pd.isna(first.STDAGE):
            ev.append(f"Stand age {fl['age']:.0f} ({fl['d']}) → {first.STDAGE:.0f} ({survey_label(first)}).")
        if pc.get("pairs"):
            ev.append(f"Bridge records at the {int(first.INVYR)} visit matched to plot {pc['plot']}'s trees: {pc['pairs']}.")
        if pc.get("dist") is not None:
            ev.append(f"Plot {pc['plot']}'s public (fuzzed) coordinates are {pc['dist']:.2f} mi from this plot's.")
        ev.append("Its periodic design makes its per-acre values not comparable with national-design visits.")
        S["cav"].insert(0, [f"Inferred predecessor, not database-linked", f"The rows for periodic plot {pc['plot']} come from a different plot key. " + " ".join(ev)])
    S["und"] = sorted(set(S.get("und", [])) | set(pred.get("und", [])))
    return S


def undecoded_caveat(und):
    """Caveat text for undecoded codes, with the research note when there is one (as the PDF)."""
    items = []
    for u in und:
        k, v = u.rsplit(" ", 1)
        rn = core.research_note(k, v)
        items.append(f"{k} {v}: " + (f"{rn.get('status', 'undecoded')}. {rn.get('range_context', '')} "
                                     f"{len(rn.get('sources_checked', []))} sources checked." if rn else "not in the FIADB User Guide v9.4 or the REF tables; shown flagged, not guessed."))
    return items


def frames(con, key):
    """Per-key frames for compute() read from SQLite (the PDF summary path; the static export slices statewide tables)."""
    from . import build
    q = lambda sql, p=(): pd.read_sql_query(sql, con, params=p)
    vis = q("SELECT v.*, p.MICROPLOT_LOC FROM visit v JOIN PLOT p ON p.CN = v.PLT_CN WHERE v.KEY=? ORDER BY v.DYEAR", (key,))
    if not len(vis):
        return None
    vno = {cn: i for i, cn in enumerate(vis.PLT_CN)}
    cns = tuple(vis.PLT_CN); ph = ",".join("?" * len(cns))
    tr = q(f"SELECT t.*, l.TID FROM TREE t JOIN tree_link l ON l.TRE_CN = t.CN WHERE t.PLT_CN IN ({ph})", cns)
    tr["vi"] = tr.PLT_CN.map(vno); tr["INVYR"] = tr.PLT_CN.map(dict(zip(vis.PLT_CN, vis.INVYR)))
    tr["DYEAR"] = tr.PLT_CN.map(dict(zip(vis.PLT_CN, vis.DYEAR))); tr["KEY"] = key
    ev = q("SELECT * FROM tree_event WHERE KEY=?", (key,))
    gi = build.growth_intervals(tr) if len(tr) else None
    out = [vis, tr, ev, gi]
    for t, cn_col in (("COND", "PLT_CN"), ("INVASIVE_SUBPLOT_SPP", "PLT_CN"), ("PLOT", "CN")):
        try:
            df = q(f"SELECT * FROM {t} WHERE {cn_col} IN ({ph})", cns)
            df["vi"] = df[cn_col].map(vno)
        except Exception:
            df = None
        out.append(df)
    return out


def for_key(con, ref, key):
    """compute() + finish() for one key, with its rank-1 inferred predecessor (as the static site's plot page)."""
    import re
    F = frames(con, key)
    if F is None:
        return None
    S = compute(*F, ref)
    pc = pd.read_sql_query("SELECT * FROM predecessor_candidate WHERE KEY=? AND RANK=1", con, params=(key,))
    if len(pc):
        r = pc.iloc[0]
        PF = frames(con, r.CAND_KEY)
        if PF is not None:
            pcd = {"key": r.CAND_KEY, "plot": int(r.CAND_PLOT), "rp": None if pd.isna(r.REMPER) else float(r.REMPER),
                   "dist": None if pd.isna(r.DIST_MI) else float(r.DIST_MI),
                   "pairs": re.sub(r"SPCD (\d+): ", lambda m: ref.spname(int(m.group(1))) + " ", r.PAIRS or "").replace(" -> ", " → ")}
            S = finish(S, None, compute(*PF, ref), pcd, F[0])
    S["undc"] = undecoded_caveat(S.pop("und", []))
    return S


def help_text():
    """fiasc/help.json: the explanations shared by the site, the glossary and the PDF summary."""
    import json, os
    return json.load(open(os.path.join(os.path.dirname(__file__), "help.json"), encoding="utf-8"))

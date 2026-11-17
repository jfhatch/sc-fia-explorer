"""Printable PDF summary for any plot location key, reusing the Plot 25 summary layout
(build_pdf.py of the earlier Plot 25 work): print-optimised HTML, 300-dpi matplotlib charts with colour + hatch/marker,
US Letter, 0.6 in margins, page numbers in the footer, no chart or table split, rendered by headless Edge.

build_pdf(con, ref, key, out_pdf) -> dict(pages, charts, engine). Raises PdfError if the totals printed differ from
the database's per-visit metrics or the PDF fails its own checks.
"""
import os, io, re, math, html, base64, datetime, subprocess, tempfile
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from . import core, plotdata, summary
from .core import dec, nz

esc = lambda x: html.escape(str(x))
INK, INK2, GRID = "#0b0b0b", "#52514e", "#dcdbd6"
HATCHES = ["", "///", "...", "xxx", "\\\\\\", "ooo", "+++", "---"]
MARKS = ["o", "s", "^", "D", "v", "P", "X", "*"]
CAUSE_COL = ["#6250d6", "#008300", "#e87ba4", "#eda100", "#e34948", "#2a78d6", "#eb6834", "#1baf7a"]
CAUSE_HAT = ["xxx", "", "///", "...", "ooo", "\\\\\\", "+++", "---"]


class PdfError(Exception):
    pass


def f(v, d=1, dash="—"):
    return dash if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:,.{d}f}"


short = lambda s: s.split(" = ", 1)[-1] if s else ""


def find_edge():
    for p in [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]:
        if os.path.exists(p):
            return p


def render_edge(src, dst):
    exe = find_edge()
    if not exe:
        raise RuntimeError("Edge not found")
    if os.path.exists(dst):
        os.remove(dst)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as ud:
        subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", f"--user-data-dir={ud}",
                        "--no-pdf-header-footer", "--virtual-time-budget=15000", f"--print-to-pdf={dst}", "file:///" + src.replace("\\", "/")],
                       capture_output=True, timeout=300)
    if not os.path.exists(dst) or os.path.getsize(dst) < 1000:
        raise RuntimeError("Edge produced no PDF")


def build_pdf(con, ref, key, out_pdf):
    core.UNDECODED.clear()                    # report only codes met while building this plot's summary
    hdr = plotdata.header(con, ref, key)
    if hdr is None:
        raise PdfError(f"unknown plot key {key}")
    fr = plotdata.load_history_frames(con, ref, key)
    plot, tree, cond = fr
    YRS = [int(y) for y in plot.INVYR]
    DATE = dict(zip(plot.INVYR.astype(int), plot.DATE))
    BUILD = datetime.date.today().isoformat()
    title = f"FIA plot {key} · {hdr['county']} County, SC"
    vrow = plotdata.q(con, "SELECT * FROM visit WHERE KEY=? ORDER BY DYEAR", (key,)).set_index("INVYR")
    FIGS = []

    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 8.5, "axes.edgecolor": "#9a9893", "axes.labelcolor": INK2,
        "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "axes.spines.top": False, "axes.spines.right": False, "axes.titleweight": "bold", "axes.titlesize": 9.5,
        "axes.titlelocation": "left", "legend.frameon": False, "hatch.linewidth": 0.6, "hatch.color": "#2b2b2b",
        "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white"})

    def fig_html(fig, caption):
        b = io.BytesIO()
        fig.savefig(b, format="png", dpi=300, bbox_inches="tight", pad_inches=0.04)
        plt.close(fig)
        FIGS.append(caption)
        from PIL import Image
        w_in = min(Image.open(io.BytesIO(b.getvalue())).size[0] / 300, 7.3)
        return (f'<figure class="fig"><img style="width:{w_in:.2f}in" alt="{esc(caption)}" src="data:image/png;base64,{base64.b64encode(b.getvalue()).decode()}">'
                f'<figcaption><b>Figure {len(FIGS)}.</b> {esc(caption)}</figcaption></figure>')

    def table(headers, rows, cls="", num=None, foot=None, widths=None):
        num = num or set()
        cg = "".join(f'<col style="width:{w}">' for w in widths) if widths else ""
        th = "".join(f'<th class="{"n" if i in num else ""}">{h}</th>' for i, h in enumerate(headers))
        body = "".join("<tr>" + "".join(f'<td class="{"n" if i in num else ""}">{c}</td>' for i, c in enumerate(r)) + "</tr>" for r in rows)
        tf = f'<tfoot><tr><td colspan="{len(headers)}">{foot}</td></tr></tfoot>' if foot else ""
        return f'<div class="tw"><table class="{cls}"><colgroup>{cg}</colgroup><thead><tr>{th}</tr></thead><tbody>{body}</tbody>{tf}</table></div>'

    # ---------------------------------------------------------------- data (shared logic)
    has_trees = len(tree) > 0
    if has_trees:
        sp_rank, TOP, SPCOL, ORDER = core.species_colours(tree)
        A = core.link_trees(tree, plot)
        A["DATE"] = A.INVYR.astype(int).map(DATE)
        B = A[A.SUBP <= 4].copy()
        spg = lambda s: s if s in TOP else "Other species"
        B["SPG"] = B.SPNAME.map(spg)
        B["W_BA"] = B.BA * B.TPA_UNADJ
        L = B[B.INPLOT & (B.STATUSCD == 1)]
        DD = B[B.INPLOT & (B.STATUSCD == 2)]
        EV = pd.DataFrame(core.tree_events(B, YRS))
        IV = pd.DataFrame(core.tree_intervals(B))
        SP_ALL = [s for s in sp_rank if s in set(L.SPNAME)]
        N_OTHER = L.loc[L.SPG == "Other species", "SPNAME"].nunique()
        HATCH = dict(zip(ORDER, HATCHES)); MARK = dict(zip(ORDER, MARKS))
    else:
        L = DD = pd.DataFrame(columns=["INVYR", "DIA", "TPA_UNADJ"])
        EV = IV = pd.DataFrame()
        SP_ALL = []

    def stand(live, dead):
        tpa = live.TPA_UNADJ.sum()
        return {"tpa5": live.loc[live.DIA >= 5, "TPA_UNADJ"].sum(), "sap": live.loc[live.DIA < 5, "TPA_UNADJ"].sum(), "tpa": tpa,
                "ba": (core.BA_K * live.DIA ** 2 * live.TPA_UNADJ).sum(),
                "qmd": math.sqrt((live.DIA ** 2 * live.TPA_UNADJ).sum() / tpa) if tpa else float("nan"),
                "vol": (live.VOLCFNET.fillna(0) * live.TPA_UNADJ).sum() if len(live) else 0.0,
                "c": (live.CARBON_AG.fillna(0) * live.TPA_UNADJ).sum() / 2000 if len(live) else 0.0,
                "n_live": len(live), "n_dead": len(dead), "dead_tpa": dead.TPA_UNADJ.sum()}

    V = {}
    for y in YRS:
        V[y] = stand(L[L.INVYR == y], DD[DD.INVYR == y])
        e = EV[EV.y1 == y] if len(EV) else EV
        V[y]["new_dead"] = int(e.type.isin(["mortality", "dead at first tally"]).sum()) if len(e) else 0
        V[y]["ingrowth"] = int((e.type == "ingrowth").sum()) if len(e) else 0
        V[y]["added"] = int((e.type == "added (not ingrowth)").sum()) if len(e) else 0
        V[y]["cut"] = int((e.type == "cut").sum()) if len(e) else 0
        r = vrow.loc[y]
        V[y].update(age=r.STDAGE, fortyp=ref.ftname(r.FORTYPCD) if not pd.isna(r.FORTYPCD) else "nonforest / no forest condition",
                    design=r.DESIGN)

    # ---------------------------------------------------------------- validation: PDF totals == database per-visit metrics
    bad = []
    for y in YRS:
        r = vrow.loc[y]
        for k, col in (("tpa", "live_tpa"), ("ba", "ba"), ("qmd", "qmd"), ("vol", "vol"), ("c", "carbon")):
            a, b_ = V[y][k], r[col]
            a = 0.0 if a is None or (isinstance(a, float) and math.isnan(a)) else a
            b_ = 0.0 if b_ is None or pd.isna(b_) else b_
            if abs(a - b_) > 0.011:
                bad.append(f"{y} {k}: pdf {a:.2f} vs database {b_:.2f}")
    if key in core.REGRESSION_BA:
        for y, ba in core.REGRESSION_BA[key].items():
            if y not in V or int(round(V[y]["ba"])) != ba:
                bad.append(f"{y} BA != published {ba}")
    if bad:
        raise PdfError("totals differ from the database: " + "; ".join(bad))

    # ---------------------------------------------------------------- charts
    FIG = {}
    if has_trees and len(L):
        def sp_handles(order=ORDER):
            return [Patch(facecolor=SPCOL[g], hatch=HATCH[g], edgecolor="#2b2b2b", linewidth=0.5) for g in order], \
                   [g if g != "Other species" else f"Other species ({N_OTHER})" for g in order]

        def by_sp(df, val):
            return df.assign(_v=val(df)).groupby(["INVYR", "SPG"])._v.sum().unstack().reindex(index=YRS, columns=ORDER).fillna(0)

        X = list(range(len(YRS)))

        def stack(ax, df, ttl, d=0):
            polys = ax.stackplot(X, *[df[g].values for g in ORDER], colors=[SPCOL[g] for g in ORDER], edgecolor="#2b2b2b", linewidth=0.4)
            for p, g in zip(polys, ORDER):
                p.set_hatch(HATCH[g])
            tot = df.sum(axis=1)
            for xi, v in zip(X, tot.values):
                ax.annotate(f"{v:,.{d}f}", (xi, v), textcoords="offset points", xytext=(0, 3), ha="center", fontsize=7.5, color=INK)
            ax.set_title(ttl); ax.set_xticks(X); ax.set_xticklabels([str(y) for y in YRS], fontsize=7.5)
            ax.set_xlim(-0.3, len(X) - 0.7); ax.set_ylim(0, max(tot.max(), 1e-9) * 1.15); ax.grid(axis="x", visible=False)

        fig, ax = plt.subplots(figsize=(7.3, 2.9))
        x = np.arange(len(YRS)); w = 0.26
        c5 = [int((L[(L.INVYR == y)].DIA >= 5).sum()) for y in YRS]
        cs = [int((L[(L.INVYR == y)].DIA < 5).sum()) for y in YRS]
        cd = [V[y]["n_dead"] for y in YRS]
        for k, (vals, lab, col, h) in enumerate([(c5, "live, ≥5.0 in", "#2a78d6", ""), (cs, "live saplings, 1.0–4.9 in", "#1baf7a", "///"),
                                                 (cd, "standing dead", "#9a9893", "xxx")]):
            bars = ax.bar(x + (k - 1) * w, vals, w * 0.92, color=col, hatch=h, edgecolor="#2b2b2b", linewidth=0.5, label=lab)
            for b_, v in zip(bars, vals):
                ax.text(b_.get_x() + b_.get_width() / 2, v + 0.4, str(v), ha="center", fontsize=7, color=INK)
        ax.set_xticks(x); ax.set_xticklabels([f"{y}\n{DATE[y]}" for y in YRS], fontsize=7.5); ax.grid(axis="x", visible=False)
        ax.set_ylabel("trees tallied on the plot"); ax.legend(loc="upper left", ncol=3, fontsize=7.5)
        ax.set_ylim(0, max(c5 + cs + cd + [1]) * 1.22)
        FIG["trees"] = fig_html(fig, "Live and standing-dead trees tallied at each visit (subplots 1–4; bridge records excluded). Saplings are "
                                     "tallied on the microplots, so their counts are much smaller than their per-acre weight.")
        SVOL = by_sp(L, lambda d: d.VOLCFNET.fillna(0) * d.TPA_UNADJ)
        SC = by_sp(L, lambda d: d.CARBON_AG.fillna(0) * d.TPA_UNADJ / 2000)
        fig, axs = plt.subplots(1, 2, figsize=(7.3, 3.3))
        stack(axs[0], SVOL, "Net cubic volume (ft³/ac)")
        stack(axs[1], SC, "Aboveground carbon (tons C/ac)", 1)
        h_, l_ = sp_handles()
        fig.legend(h_, l_, loc="lower center", ncol=4, bbox_to_anchor=(0.5, -0.1), fontsize=7.5)
        FIG["vc"] = fig_html(fig, "Live net cubic volume (VOLCFNET) and aboveground carbon (CARBON_AG ÷ 2000) per acre, stacked by species; "
                                  "labels are totals. Volume exists only for trees ≥5.0 in; carbon includes saplings.")
        SBA = by_sp(L, lambda d: d.W_BA)
        fig, ax = plt.subplots(figsize=(7.3, 3.2))
        stack(ax, SBA, "Live basal area by species (ft²/ac)")
        ax.legend(*sp_handles(), loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=7.5)
        FIG["ba"] = fig_html(fig, "Live basal area per acre stacked by species.")
        BA_SP = L.groupby(["SPNAME", "INVYR"]).W_BA.sum().unstack().reindex(index=SP_ALL, columns=YRS).fillna(0)
        PCT = BA_SP / BA_SP.sum().replace(0, np.nan) * 100
        ann = [y for y in YRS if V[y]["design"] == "annual" and V[y]["ba"] > 0]
        y0, y1 = (ann[0], ann[-1]) if len(ann) >= 2 else (YRS[0], YRS[-1])
        show = [s for s in SP_ALL if PCT.loc[s, [y0, y1]].fillna(0).max() >= 1.0]
        if y0 != y1 and show:
            fig, ax = plt.subplots(figsize=(7.3, max(2.0, 0.28 * len(show) + 1.0)))
            yy = np.arange(len(show))[::-1]
            for yv, s in zip(yy, show):
                a, b = PCT.loc[s, y0] if not pd.isna(PCT.loc[s, y0]) else 0, PCT.loc[s, y1] if not pd.isna(PCT.loc[s, y1]) else 0
                ax.plot([a, b], [yv, yv], color="#9a9893", lw=1.4, zorder=1)
                ax.scatter([a], [yv], s=34, facecolors="white", edgecolors=INK2, linewidths=1.3, zorder=2, marker="o")
                ax.scatter([b], [yv], s=40, color=SPCOL[spg(s)], edgecolors="#2b2b2b", linewidths=0.6, zorder=3, marker=MARK[spg(s)])
                ax.text(max(a, b) + 0.6, yv, f"{a:.0f}% → {b:.0f}%", va="center", fontsize=7, color=INK2)
            ax.set_yticks(yy); ax.set_yticklabels(show, fontsize=7.5); ax.set_xlabel("share of live basal area (%)")
            ax.set_xlim(0, PCT[[y0, y1]].max().max() * 1.25); ax.grid(axis="y", visible=False)
            ax.set_title(f"Composition shift, {y0} → {y1}")
            ax.legend(handles=[plt.Line2D([0], [0], ls="", marker="o", mfc="white", mec=INK2, ms=6, label=str(y0)),
                               plt.Line2D([0], [0], ls="", marker="s", color=INK2, ms=6, label=f"{y1} (marker = species)")],
                      loc="lower right", fontsize=7.5)
            FIG["shift"] = fig_html(fig, f"Share of live basal area by species at {y0} and {y1} (species with ≥1% in either year).")
        if len(IV):
            GS = IV.groupby("sp").agg(n=("gd", "size"), trees=("id", "nunique"), mean=("gd", "mean"), median=("gd", "median"),
                                      lo=("gd", "min"), hi=("gd", "max"), ht=("gh", "mean"))
            GS = GS.loc[[s for s in sp_rank if s in GS.index]]
            fig, ax = plt.subplots(figsize=(7.3, max(2.0, 0.28 * len(GS) + 1.0)))
            yy = np.arange(len(GS))[::-1]
            for yv, (s, r) in zip(yy, GS.iterrows()):
                g = spg(s)
                ax.plot([r.lo, r.hi], [yv, yv], color="#9a9893", lw=1.6, solid_capstyle="butt", zorder=1)
                ax.scatter([r["mean"]], [yv], s=46, color=SPCOL[g], edgecolors="#2b2b2b", linewidths=0.6, marker=MARK[g], zorder=3)
                ax.text(r.hi + 0.012, yv, f"{r['mean']:.2f}  (n={int(r.n)})", va="center", fontsize=7, color=INK2)
            ax.axvline(0, color=INK2, lw=0.7)
            ax.set_yticks(yy); ax.set_yticklabels(GS.index, fontsize=7.5); ax.grid(axis="y", visible=False)
            ax.set_xlabel("annual DBH growth (in/yr): marker = mean, line = range"); ax.set_xlim(min(-0.05, GS.lo.min() - 0.03), GS.hi.max() + 0.25)
            ax.set_title("Mean annual DBH growth by species")
            FIG["grow"] = fig_html(fig, "Mean annual DBH growth by species from trees live at consecutive visits; n = remeasurement intervals. "
                                        "Rates use the actual survey dates.")
        M = EV[EV.type == "mortality"].copy() if len(EV) else pd.DataFrame()
        IVL = [f"{YRS[i - 1]}→{YRS[i]}" for i in range(1, len(YRS))]
        if len(M):
            CAUSES = sorted(M.cause.unique(), key=lambda s: (s.startswith("no"), s))
            CCOL = {c: CAUSE_COL[i % len(CAUSE_COL)] for i, c in enumerate(CAUSES)}
            CHAT = {c: CAUSE_HAT[i % len(CAUSE_HAT)] for i, c in enumerate(CAUSES)}
            M["ivl"] = M.y0.astype(int).astype(str) + "→" + M.y1.astype(int).astype(str)
            fig, axs = plt.subplots(1, 2, figsize=(7.3, 3.0))
            for ax, col, lab in [(axs[0], "tpa", "trees/ac lost"), (axs[1], "ba_ac", "basal area lost (ft²/ac)")]:
                bottom = np.zeros(len(IVL))
                for c in CAUSES:
                    v = M[M.cause == c].groupby("ivl")[col].sum().reindex(IVL).fillna(0).values
                    ax.bar(IVL, v, bottom=bottom, color=CCOL[c], hatch=CHAT[c], edgecolor="#2b2b2b", linewidth=0.5, width=0.6)
                    bottom += v
                for xi, v in enumerate(bottom):
                    ax.text(xi, v, f"{v:,.0f}" if col == "tpa" else f"{v:.1f}", ha="center", va="bottom", fontsize=7, color=INK)
                ax.set_title(lab); ax.grid(axis="x", visible=False); ax.set_ylim(0, bottom.max() * 1.15 + 0.1)
                ax.tick_params(axis="x", labelsize=7 if len(IVL) > 5 else 7.5, rotation=30 if len(IVL) > 5 else 0)
            fig.legend([Patch(facecolor=CCOL[c], hatch=CHAT[c], edgecolor="#2b2b2b", linewidth=0.5) for c in CAUSES],
                       [c.split(" (")[0][:60] for c in CAUSES], loc="upper center", ncol=2, bbox_to_anchor=(0.5, 0.0), fontsize=7.5,
                       title="Cause of death (AGENTCD)", title_fontsize=7.5)
            FIG["mort"] = fig_html(fig, "Trees live at one visit and first recorded dead at the next, by interval and decoded cause. "
                                        "Per-acre values use each tree's last live DBH and TPA_UNADJ.")

    # ---------------------------------------------------------------- tables
    preds = [p for p in hdr["predecessors"] if p["rank"] == 1]
    rows = []
    for p in preds:
        rows.append([f'<b>{esc(p["last_date"])}</b><br><span class="tag">plot {p["plot"]}: inferred candidate, not database-linked</span>',
                     f(p["stdage"], 0), esc(short(p["fortyp"])), "—", "—", "—", "—", "—", "—", "—", "—"])
    for y in YRS:
        v = V[y]
        dagger = "†" if v["design"] == "periodic" else ""
        new = (f"{v['ingrowth']}" + (f" + {v['added']}*" if v["added"] else "")) if y != YRS[0] else "—"
        rows.append([f"<b>{DATE[y]}</b><br><span class='muted'>INVYR {y} · {v['design']}</span>", f(v["age"], 0), esc(short(v["fortyp"])),
                     f(v["tpa5"], 0) + dagger, f(v["sap"], 0) + dagger, f(v["ba"]) + dagger, f(v["qmd"]) + dagger, f(v["vol"], 0) + dagger,
                     f(v["c"]) + dagger, (f"{v['n_dead']} ({v['new_dead']} new)" if y != YRS[0] else f"{v['n_dead']}") + (f"; {v['cut']} cut" if v["cut"] else ""),
                     new])
    T_SURVEY = table(["Survey", "Age yr", "Forest type", "Trees/ac ≥5 in", "Saplings /ac", "BA ft²/ac", "QMD in", "Net vol ft³/ac",
                      "Carbon t C/ac", "Dead trees (new)", "New trees"], rows, "survey", num={1, 3, 4, 5, 6, 7, 8},
                     foot="† Periodic (variable-radius or other pre-annual) design: per-acre values are not comparable with national-design visits. "
                          "Inferred candidate rows are periodic plots matched by location, date and bridge trees, not database links (see the plot page). "
                          "New trees = ingrowth (RECONCILECD 1); * = other additions (e.g. microplot relocation, missed trees).",
                     widths=["17%", "5%", "18%", "7%", "7%", "7%", "5%", "8%", "7%", "10%", "9%"])
    rows = [[str(y), DATE[y], str(V[y]["n_live"]), str(int((L[L.INVYR == y].DIA >= 5).sum())), str(int((L[L.INVYR == y].DIA < 5).sum())),
             str(V[y]["n_dead"]), f(V[y]["dead_tpa"], 0), str(V[y]["new_dead"]) if y != YRS[0] else "—",
             str(V[y]["ingrowth"]) if y != YRS[0] else "—", str(V[y]["added"]) if y != YRS[0] else "—"] for y in YRS]
    T_TREES = table(["INVYR", "Survey date", "Live trees", "of which ≥5 in", "saplings", "Standing dead", "Dead trees/ac", "Newly dead",
                     "Ingrowth", "Other additions"], rows, num=set(range(2, 10)))
    YS = YRS[-6:]                                    # keep the wide species tables printable
    note_ys = "" if YS == YRS else f" Last {len(YS)} of {len(YRS)} visits shown."
    T_VC = T_SP = T_GROW = T_MORT = ""
    if SP_ALL:
        rows = []
        for s in SP_ALL:
            vv = L[L.SPNAME == s]
            rows.append([esc(s)] + [f(float((vv[vv.INVYR == y].VOLCFNET.fillna(0) * vv[vv.INVYR == y].TPA_UNADJ).sum()), 0) for y in YS]
                        + [f(float((vv[vv.INVYR == y].CARBON_AG.fillna(0) * vv[vv.INVYR == y].TPA_UNADJ).sum() / 2000), 2) for y in YS])
        rows.append(["<b>All species</b>"] + [f"<b>{f(V[y]['vol'], 0)}</b>" for y in YS] + [f"<b>{f(V[y]['c'], 2)}</b>" for y in YS])
        T_VC = table(["Species"] + [f"Vol {y}" for y in YS] + [f"C {y}" for y in YS], rows, "small", num=set(range(1, 2 * len(YS) + 1)),
                     foot="Vol = net cubic volume ft³/ac (VOLCFNET × TPA_UNADJ); C = aboveground carbon tons/ac (CARBON_AG × TPA_UNADJ ÷ 2000)." + note_ys)
        TPA5 = L[L.DIA >= 5].groupby(["SPNAME", "INVYR"]).TPA_UNADJ.sum().unstack().reindex(index=SP_ALL, columns=YRS).fillna(0)
        rows = [[esc(s)] + sum([[f(BA_SP.loc[s, y]), f(TPA5.loc[s, y], 0), f(PCT.loc[s, y], 0)] for y in YS], []) for s in SP_ALL]
        rows.append(["<b>All species</b>"] + sum([[f"<b>{f(BA_SP[y].sum())}</b>", f"<b>{f(TPA5[y].sum(), 0)}</b>", "<b>100</b>"] for y in YS], []))
        T_SP = table(["Species"] + sum([[f"{y}<br>BA", "TPA<br>≥5", "%BA"] for y in YS], []), rows, "small sp", num=set(range(1, 3 * len(YS) + 1)),
                     foot="BA = live basal area ft²/ac; TPA ≥5 = live trees/ac ≥5.0 in DBH; %BA = share of live basal area." + note_ys)
        if len(IV):
            rows = [[esc(s), str(int(r.n)), str(int(r.trees)), f(r["mean"], 3), f(r["median"], 3), f"{r.lo:.3f} to {r.hi:.3f}", f(r.ht, 2)]
                    for s, r in GS.iterrows()]
            T_GROW = table(["Species", "n intervals", "trees", "mean in/yr", "median in/yr", "range in/yr", "mean height ft/yr"], rows,
                           num={1, 2, 3, 4, 6}, foot="Each interval = one tree live at two consecutive visits; (DBH₂ − DBH₁) ÷ years between survey dates.")
        if len(M):
            rows = []
            for ivl in IVL:
                m = M[M.ivl == ivl]
                if not len(m):
                    rows.append([ivl, "<span class='muted'>no mortality</span>", "", "", "", ""])
                    continue
                for (s, c), g in m.groupby(["sp", "cause"]):
                    rows.append([ivl, esc(s), esc(short(c).rstrip(".")[:90]), str(len(g)), f(g.tpa.sum(), 1), f(g.ba_ac.sum(), 2)])
                rows.append([f"<b>{ivl}</b>", "<b>interval total</b>", "", f"<b>{len(m)}</b>", f"<b>{f(m.tpa.sum(), 1)}</b>", f"<b>{f(m.ba_ac.sum(), 2)}</b>"])
            dft = EV[EV.type == "dead at first tally"]
            T_MORT = table(["Interval", "Species", "Cause (AGENTCD, decoded)", "Trees", "Trees/ac lost", "BA ft²/ac lost"], rows, num={3, 4, 5},
                           foot=(f"Not included: {len(dft)} tree(s) first recorded already dead." if len(dft) else ""))
    inv = plotdata.q(con, f"SELECT PLT_CN, SUBP, VEG_SPCD, COVER_PCT FROM INVASIVE_SUBPLOT_SPP WHERE PLT_CN IN ({','.join('?' * len(plot))})",
                     tuple(plot.CN)) if plotdata.has_table(con, "INVASIVE_SUBPLOT_SPP") else pd.DataFrame()
    T_INV, INV_FIRST = "<p>No invasive plant records for this plot.</p>", {}
    surveyed = [int(p.INVYR) for p in plot.itertuples() if p.INVASIVE_SAMPLING_STATUS_CD == 1]
    if len(inv):
        inv["yr"] = inv.PLT_CN.map(dict(zip(plot.CN, plot.INVYR))).astype(int)
        rows = []
        for sym, g in inv.groupby("VEG_SPCD"):
            cn, sci = ref.plant(sym)
            first = int(g.yr.min()); INV_FIRST[cn] = first
            cells = []
            for y in YRS:
                if y not in surveyed:
                    cells.append("<span class='muted'>not surveyed</span>")
                    continue
                x = g[g.yr == y]
                cells.append("○ 0/4" if not len(x) else f"<b>{'●' * len(x)}{'○' * max(0, 4 - len(x))} {len(x)}/4</b><br>{x.COVER_PCT.astype(float).mean():.1f}% cover")
            rows.append([f"{esc(cn)}<br><i>{esc(sci)}</i> ({esc(sym)})"] + cells + [f"<b>{first}</b>"])
        T_INV = table(["Species"] + [str(y) for y in YRS] + ["First detected"], rows, "inv",
                      foot="● = subplot where the species was recorded (of 4); cover = mean cover % on those subplots."
                           + (f" Invasive plants were first surveyed on this plot in {min(surveyed)}." if surveyed else ""))
    elif surveyed:
        T_INV = f"<p>Invasive plants were surveyed in {', '.join(map(str, surveyed))}; none recorded.</p>"

    # ---------------------------------------------------------------- highlights (computed)
    live_y = [y for y in YRS if V[y]["n_live"]]
    bul = []
    if live_y:
        pk = max(live_y, key=lambda y: V[y]["ba"])
        a, z = live_y[0], live_y[-1]
        bul.append(f"<b>Basal area</b> went from {V[a]['ba']:.0f} ft²/ac in {a} to {V[z]['ba']:.0f} in {z} (peak {V[pk]['ba']:.0f} in {pk}).")
        bul.append(f"<b>Carbon.</b> Live aboveground carbon {V[a]['c']:.1f} → {V[z]['c']:.1f} tons C/ac; net cubic volume "
                   f"{V[a]['vol']:,.0f} → {V[z]['vol']:,.0f} ft³/ac.")
        if SP_ALL:
            lead = BA_SP[z].sort_values(ascending=False)
            bul.append(f"<b>Leading species in {z}:</b> " + ", ".join(f"{s} ({PCT.loc[s, z]:.0f}% of BA)" for s in lead.index[:3] if lead[s] > 0) + ".")
    if len(EV):
        M_ = EV[EV.type == "mortality"]
        if len(M_):
            cz = M_.groupby("cause").size().sort_values(ascending=False)
            bul.append(f"<b>Mortality.</b> {len(M_)} trees died between visits: " +
                       ", ".join(f"{n} {short(c).split(' (')[0].rstrip('.').lower()[:60]}" for c, n in cz.items()) + ".")
        ncut = int((EV.type == "cut").sum())
        if ncut:
            bul.append(f"<b>Cutting.</b> {ncut} trees were recorded cut (STATUSCD 3).")
        ning = int((EV.type == "ingrowth").sum())
        if ning:
            bul.append(f"<b>Ingrowth.</b> {ning} trees entered the tally as ingrowth (RECONCILECD 1).")
    if len(IV) and (IV.groupby('sp').size() >= 3).any():
        GS3 = GS[GS.n >= 3]
        bul.append(f"<b>Growth.</b> Fastest-growing species with ≥3 intervals: {GS3['mean'].idxmax()} ({GS3['mean'].max():.2f} in/yr); plot mean {IV.gd.mean():.2f} in/yr.")
    if INV_FIRST:
        bul.append("<b>Invasives.</b> " + "; ".join(f"{k[:1].upper() + k[1:]} first detected {v}" for k, v in sorted(INV_FIRST.items(), key=lambda kv: kv[1])) + ".")
    if preds:
        p = preds[0]
        bul.append(f"<b>Before {YRS[0]}:</b> periodic plot {p['plot']} ({p['last_date']}, {short(p['fortyp']).lower()}) is the top inferred "
                   f"predecessor candidate (score {p['score']:.0f}/100; not database-linked).")
    if not bul:
        bul = ["No live trees were tallied at any visit (nonforest or nonsampled plot)."]
    und = sorted(core.UNDECODED)
    caveats = [
        "<b>Unadjusted per-acre values.</b> " + esc(plotdata.UNADJ_NOTE),
        "<b>Public coordinates.</b> " + esc(hdr["coord_note"]),
        f"<b>Bridge records.</b> Records on SUBP > 4 (periodic-to-annual GRM bridge records) are excluded from all totals.",
        "<b>Microplot relocation.</b> Visits where PLOT.MICROPLOT_LOC changed (" + ", ".join(map(str, sorted(
            {YRS[i] for i in range(1, len(YRS)) if plot.MICROPLOT_LOC.iloc[i] != plot.MICROPLOT_LOC.iloc[i - 1]
             and not pd.isna(plot.MICROPLOT_LOC.iloc[i]) and not pd.isna(plot.MICROPLOT_LOC.iloc[i - 1])}))) + ") change the sapling sample; "
            "additions there are not ingrowth." if "MICROPLOT_LOC" in plot else "",
        "<b>Inferred predecessors</b> are candidates matched by county, distance (≤1.5 mi, fuzzed coordinates), date (last periodic date + REMPER "
        "within 0.5 yr of the first national visit) and bridge trees. They are not database links." if hdr["predecessors"] else "",
        ("<b>Undecoded codes</b> (shown flagged, not guessed): " + "; ".join(esc(f"{k} {v}") for k, v in und[:12]) + ".") if und else
        "<b>Codes.</b> Every coded value shown was found in the FIADB User Guide v9.4 or the REF tables.",
    ]
    caveats = [c for c in caveats if c]
    # highlights, caveats and section intros: the same computations (fiasc.summary) and text (fiasc/help.json) as the site's plot page
    SUMM = summary.for_key(con, ref, key)
    if SUMM:
        bul = [f"<b>{esc(b)}.</b> {esc(t)}" for b, t in SUMM["hl"]] or bul
        caveats = [f"<b>{esc(b)}.</b> {esc(t)}" for b, t in SUMM["cav"]] + (
            ["<b>Undecoded codes</b> (shown flagged, not guessed):<ul>" + "".join(f"<li>{esc(u)}</li>" for u in SUMM["undc"]) + "</ul>"] if SUMM["undc"] else []) + [
            "<b>Public coordinates.</b> " + esc(hdr["coord_note"])]
    HT = summary.help_text()["sections"]
    intro_ = lambda k: f'<p class="muted">{esc(HT[k]["intro"])} ({esc(HT[k]["refs"])})</p>' if k in HT else ""
    CSS = f"""
@page {{ size: letter portrait; margin: 0.6in;
  @top-left {{ content: "{esc(title)} · summary"; font: 7.5pt 'Segoe UI', Arial, sans-serif; color: #6b6a66; }}
  @top-right {{ content: "Built {BUILD}"; font: 7.5pt 'Segoe UI', Arial, sans-serif; color: #6b6a66; }}
  @bottom-center {{ content: "Page " counter(page) " of " counter(pages); font: 8pt 'Segoe UI', Arial, sans-serif; color: #3a3936; }} }}
* {{ box-sizing: border-box; }}
html {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
body {{ margin: 0; font: 9.3pt/1.4 'Segoe UI', Arial, sans-serif; color: #111; background: #fff; }}
h1 {{ font-size: 18pt; margin: 0 0 2pt; }} .sub {{ color: #52514e; margin: 0 0 8pt; font-size: 9pt; }}
h2 {{ font-size: 13pt; margin: 0 0 5pt; padding-bottom: 2pt; border-bottom: 1.2pt solid #2a78d6; }}
h3 {{ font-size: 10pt; margin: 9pt 0 3pt; }}
section {{ break-before: page; }} section.flow {{ break-before: auto; margin-top: 12pt; }}
p {{ margin: 0 0 5pt; }} ul {{ margin: 3pt 0 6pt 14pt; padding: 0; }} li {{ margin: 0 0 3pt; }}
.tag {{ display: inline-block; font-size: 6.8pt; line-height: 1.2; color: #52514e; border: 0.6pt dashed #8a8984; border-radius: 4pt; padding: 0 3pt; }}
.muted {{ color: #6b6a66; font-size: 7.5pt; }}
.fig {{ margin: 6pt 0 8pt; break-inside: avoid; page-break-inside: avoid; }}
.fig img {{ max-width: 100%; display: block; margin: 0 auto; }}
figcaption {{ font-size: 7.8pt; color: #3a3936; margin-top: 3pt; }}
.tw {{ break-inside: avoid; page-break-inside: avoid; margin: 4pt 0 8pt; }}
table {{ border-collapse: collapse; width: 100%; font-size: 7.8pt; font-variant-numeric: tabular-nums; table-layout: auto; }}
thead {{ display: table-header-group; }} tr {{ break-inside: avoid; }}
th {{ background: #eeede9; text-align: left; font-weight: 600; padding: 2.5pt 4pt; border-bottom: 0.8pt solid #8a8984; vertical-align: bottom; }}
td {{ padding: 2pt 4pt; border-bottom: 0.5pt solid #dcdbd6; vertical-align: top; }}
td.n, th.n {{ text-align: right; }}
tfoot td {{ font-size: 7pt; color: #52514e; border: 0; padding-top: 3pt; }}
table.small {{ font-size: 7.2pt; }} table.small td, table.small th {{ padding: 1.6pt 3pt; }}
table.sp th:nth-child(3n+2), table.sp td:nth-child(3n+2) {{ border-left: 0.6pt solid #c9c8c2; }}
table.survey {{ table-layout: fixed; }} table.survey td, table.survey th {{ overflow-wrap: anywhere; }}
table.inv td {{ text-align: center; }} table.inv td:first-child {{ text-align: left; }}
.kpis {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 5pt; margin: 6pt 0; }}
.kpi {{ border: 0.8pt solid #c9c8c2; border-radius: 4pt; padding: 4pt 6pt; }}
.kpi .l {{ font-size: 7.3pt; color: #52514e; }} .kpi .v {{ font-size: 13pt; font-weight: 650; }} .kpi .u {{ font-size: 7pt; color: #6b6a66; }}
.keep {{ break-inside: avoid; page-break-inside: avoid; }} h2, h3 {{ break-after: avoid; }}
"""
    kp = []
    if live_y:
        a, z = live_y[0], live_y[-1]
        kp = [("Live basal area", f"{V[a]['ba']:.0f} → {V[z]['ba']:.0f}", f"ft²/ac, {a}–{z}"),
              ("Aboveground carbon", f"{V[a]['c']:.1f} → {V[z]['c']:.1f}", "tons C/ac"),
              ("Net cubic volume", f"{V[a]['vol']:,.0f} → {V[z]['vol']:,.0f}", "ft³/ac"),
              ("Stand age", f"{f(V[a]['age'], 0)} → {f(V[z]['age'], 0)}", "years (COND.STDAGE)")]
    KPI = "".join(f'<div class="kpi"><div class="l">{a}</div><div class="v">{b}</div><div class="u">{c}</div></div>' for a, b, c in kp)
    surveys = " · ".join(DATE[y] for y in YRS)
    SK = {"Survey summary": "survey", "Volume and carbon": "vc", "Species": "species", "Growth": "growth", "Mortality": "mort", "Invasive plants": "invh"}
    sec = lambda n, t, body: f"<section><h2>{n}. {t}</h2>{intro_(SK[t]) if t in SK else ''}{body}</section>"
    H = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{esc(title)} summary</title><style>{CSS}</style></head><body>
<h1>{esc(title)}</h1>
<p class="sub">STATECD {hdr['statecd']} · UNITCD {hdr['unitcd']} · COUNTYCD {hdr['countycd']} · PLOT {hdr['plot']} · surveys: {esc(surveys)} ·
FIADB DataMart CSV, codes from the FIADB User Guide v9.4 · built {BUILD}</p>
<div class="kpis">{KPI}</div>
<h2>Highlights</h2>
<ul>{''.join(f'<li>{b}</li>' for b in bul)}</ul>
{sec(1, "Survey summary", "<p>Every visit at this location key" + (", preceded by the top inferred periodic candidate (not database-linked)" if preds else "") + ". Per-acre values are for live trees unless stated.</p>" + T_SURVEY + "<h3>Tree totals</h3>" + T_TREES + FIG.get("trees", ""))}
{sec(2, "Volume and carbon", FIG.get("vc", "") + T_VC) if T_VC else ""}
{sec(3, "Species", T_SP + FIG.get("ba", "")) if T_SP else ""}
{sec(3, "Species (continued): composition shift", FIG["shift"]) if "shift" in FIG else ""}
{sec(4, "Growth", T_GROW + FIG.get("grow", "")) if T_GROW else ""}
{sec(5, "Mortality", FIG.get("mort", "") + T_MORT) if T_MORT else ""}
{sec(6, "Invasive plants", T_INV)}
<section class="flow"><h2>7. Caveats</h2><ul>{''.join(f'<li>{c}</li>' for c in caveats)}</ul></section>
</body></html>"""
    html_path = out_pdf[:-4] + "_print.html"
    open(html_path, "w", encoding="utf-8").write(H)
    render_edge(html_path, out_pdf)
    from pypdf import PdfReader
    rd = PdfReader(out_pdf)
    texts = [p.extract_text() or "" for p in rd.pages]
    imgs = [len(p.images) for p in rd.pages]
    problems = []
    for i, (t, k) in enumerate(zip(texts, imgs), 1):
        body = re.sub(r"(summary|Built \d{4}-\d{2}-\d{2}|Page \d+ of \d+)", "", t).strip()
        if len(body) < 40 and k == 0:
            problems.append(f"page {i} is empty")
    if sum(imgs) != len(FIGS):
        problems.append(f"{sum(imgs)} images in PDF, expected {len(FIGS)} charts")
    alltext = "\n".join(texts)
    for k in range(1, len(FIGS) + 1):
        if f"Figure {k}." not in alltext:
            problems.append(f"Figure {k} caption not found")
    sp_page = next((t for t in texts if "Survey summary" in t), "")
    for y in YRS:
        if f"{V[y]['ba']:.1f}" not in sp_page:
            problems.append(f"survey table BA for {y} ({V[y]['ba']:.1f}) not found in the PDF text")
    if problems:
        raise PdfError("; ".join(problems))
    try:
        os.remove(html_path)
    except OSError:
        pass
    return {"pages": len(rd.pages), "charts": len(FIGS), "ba": {y: round(V[y]["ba"], 2) for y in YRS}}

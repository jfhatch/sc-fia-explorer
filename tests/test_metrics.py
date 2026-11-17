"""Per-acre metrics, regression totals, and the statewide (vectorized) events against core.tree_events()."""
import math, random
import numpy as np
import pandas as pd
import pytest
from fiasc import core, plotdata
from conftest import PLOT25



def test_plot25_regression_ba(con):
    got = dict(con.execute("SELECT INVYR, ba FROM visit WHERE KEY=?", (PLOT25,)).fetchall())
    for y, ba in core.REGRESSION_BA[PLOT25].items():
        assert int(round(got[y])) == ba, (y, got[y])


def stand(live):
    tpa = live.TPA_UNADJ.sum()
    return {"live_tpa": tpa, "ba": (core.BA_K * live.DIA ** 2 * live.TPA_UNADJ).sum(),
            "qmd": math.sqrt((live.DIA ** 2 * live.TPA_UNADJ).sum() / tpa) if tpa else np.nan,
            "vol": (live.VOLCFNET.fillna(0) * live.TPA_UNADJ).sum(), "carbon": (live.CARBON_AG.fillna(0) * live.TPA_UNADJ).sum() / 2000}


def sample_keys(con, n=25, seed=7):
    keys = [r[0] for r in con.execute("SELECT KEY FROM plot_location WHERE N_VISITS >= 3 AND BA > 0 ORDER BY KEY")]
    random.Random(seed).shuffle(keys)
    return [PLOT25] + keys[:n]


def test_visit_metrics_match_the_per_plot_method(con, ref):
    """visit.* (vectorized at build time) == the Plot 25 PDF's stand() applied to each plot's TREE rows."""
    for key in sample_keys(con, 15):
        plot, tree, cond = plotdata.load_history_frames(con, ref, key)
        B = tree[tree.SUBP <= 4]
        v = pd.read_sql_query("SELECT INVYR, live_tpa, ba, qmd, vol, carbon FROM visit WHERE KEY=?", con, params=(key,)).set_index("INVYR")
        for y in v.index:
            live = B[(B.INVYR == y) & (B.STATUSCD == 1) & B.TPA_UNADJ.notna()]
            s = stand(live)
            for k in s:
                a, b = s[k], v.loc[y, k]
                if pd.isna(b):
                    assert (a == 0 or pd.isna(a)), (key, y, k, a, b)
                else:
                    assert abs(a - b) < 1e-6, (key, y, k, a, b)


def test_species_rows_sum_to_visit_totals(con):
    d = pd.read_sql_query("SELECT v.PLT_CN, v.ba, v.live_tpa, SUM(s.ba) AS sba, SUM(s.live_tpa) AS stpa FROM visit v JOIN visit_species s "
                          "ON s.PLT_CN = v.PLT_CN GROUP BY v.PLT_CN", con)
    d = d[d.ba.notna()]
    assert np.allclose(d.ba, d.sba.fillna(0), atol=1e-6) and np.allclose(d.live_tpa, d.stpa.fillna(0), atol=1e-6)


def test_size_classes_sum_to_live_tpa(con):
    d = pd.read_sql_query("SELECT live_tpa, live_tpa_c1, live_tpa_c2, live_tpa_c3, live_tpa_c4, sap_tpa, tpa5 FROM visit WHERE live_tpa > 0", con).fillna(0)
    assert np.allclose(d.live_tpa, d.live_tpa_c1 + d.live_tpa_c2 + d.live_tpa_c3 + d.live_tpa_c4, atol=1e-6)
    assert np.allclose(d.live_tpa, d.sap_tpa + d.tpa5, atol=1e-6)


def _per_plot_events(con, ref, key):
    plot, tree, cond = plotdata.load_history_frames(con, ref, key)
    A = core.link_trees(tree, plot)
    B = A[A.SUBP <= 4]
    YRS = [int(y) for y in plot.INVYR]
    ev = pd.DataFrame(core.tree_events(B, YRS))
    if not len(ev):
        return ev
    ev["TID"] = ev["id"].map(dict(zip(B.TREE_ID, B.TID)))
    return ev


@pytest.mark.parametrize("n", [25])
def test_statewide_events_equal_core_tree_events(con, ref, n):
    """tree_event (built for every plot at once) must equal core.tree_events() run plot by plot."""
    for key in sample_keys(con, n):
        a = _per_plot_events(con, ref, key)
        b = pd.read_sql_query("SELECT * FROM tree_event WHERE KEY=?", con, params=(key,))
        assert len(a) == len(b), (key, len(a), len(b))
        if not len(a):
            continue
        # core.tree_events rounds TPA to 3 and BA/ac to 4 decimals (nz); the stored values are unrounded
        ka = sorted(zip(a["type"], a.TID, a.y0.fillna(-1).astype(int), a.y1.astype(int), a.tpa.fillna(-1).round(3), a.ba_ac.fillna(-1).round(3)))
        kb = sorted(zip(b.TYPE, b.TID, b.Y0.fillna(-1).astype(int), b.Y1.astype(int), b.TPA.fillna(-1).round(3), b.BA_AC.fillna(-1).round(4).round(3)))
        assert ka == kb, key


def test_plot25_mortality_and_ingrowth(con):
    ev = pd.read_sql_query("SELECT TYPE, Y1, RECONCILECD FROM tree_event WHERE KEY=?", con, params=(PLOT25,))
    assert (ev.TYPE == "mortality").sum() > 0
    ing = ev[ev.TYPE == "ingrowth"]
    assert (ing.RECONCILECD == 1).all()
    # 2006 microplot move: saplings added with RECONCILECD 3 are not ingrowth
    added06 = ev[(ev.TYPE == "added (not ingrowth)") & (ev.Y1 == 2006)]
    assert len(added06) == 17 and (added06.RECONCILECD == 3).all()
    dropped06 = ev[(ev.TYPE == "removed from sample") & (ev.Y1 == 2006)]
    assert (dropped06.RECONCILECD == 8).sum() == 8


def test_history_separates_microplot_relocation(con, ref):
    h = plotdata.history(con, ref, PLOT25)
    assert h["microplot_moved"] == [2006]
    cls = pd.DataFrame(h["events"]).cls.value_counts()
    assert cls.get("microplot relocation addition", 0) == 17
    assert cls.get("microplot relocation drop", 0) == 8
    # stacked species totals add up to the visit totals
    tot = pd.DataFrame(h["stack"]["ba"]).sum(axis=1).values
    assert np.allclose(tot, h["totals"]["ba"], atol=1e-3)


def test_statewide_growth_equals_core_tree_intervals(con, ref):
    """build.growth_intervals (used by the static export) == core.tree_intervals() run plot by plot."""
    from fiasc import build
    for key in sample_keys(con, 20):
        plot, tree, cond = plotdata.load_history_frames(con, ref, key)
        A = core.link_trees(tree, plot)
        A["DATE"] = A.INVYR.astype(int).map(dict(zip(plot.INVYR.astype(int), plot.DATE)))
        a = pd.DataFrame(core.tree_intervals(A[A.SUBP <= 4]))
        t = A.assign(KEY=key)
        b = build.growth_intervals(t)
        assert len(a) == len(b), (key, len(a), len(b))
        if len(a):
            ka = sorted(zip(a.y0, a.y1, a.dia0.round(1), a.dia1.round(1), a.gd.round(3)))
            kb = sorted(zip(b.y0.astype(int), b.y1.astype(int), b.dia0.round(1), b.dia1.round(1), b.gd.round(4).round(3)))
            assert ka == kb, key

"""Visit chains (PREV_PLT_CN), tree linking (PREV_TRE_CN), inferred predecessor candidates and plot-ID search."""
import pandas as pd
from fiasc import core, plotdata, build
from conftest import PLOT25


def test_root_cns_follows_predecessors():
    cn = ["a", "b", "c", "d", "e"]
    prev = [None, "a", "b", None, "zz"]          # 'zz' is outside the set: starts its own chain
    assert core.root_cns(cn, prev) == ["a", "a", "a", "d", "e"]


def test_plot25_visits_form_one_prev_plt_cn_chain(con):
    v = pd.read_sql_query("SELECT PLT_CN, PREV_PLT_CN, INVYR, CHAIN, DESIGN FROM visit WHERE KEY=? ORDER BY INVYR", con, params=(PLOT25,))
    assert [2000, 2006, 2011, 2016, 2021] == [int(y) for y in v.INVYR[:5]]
    assert v.CHAIN.nunique() == 1 and v.CHAIN.iloc[0] == v.PLT_CN.iloc[0]
    assert pd.isna(v.PREV_PLT_CN.iloc[0])
    assert (v.PREV_PLT_CN.iloc[1:].values == v.PLT_CN.iloc[:-1].values).all()
    assert set(v.DESIGN) == {"annual"}


def test_chain_links_are_consistent_statewide(con):
    # every PREV_PLT_CN that resolves points to an earlier visit in the same chain
    bad = con.execute("SELECT COUNT(*) FROM visit a JOIN visit b ON b.PLT_CN = a.PREV_PLT_CN WHERE b.CHAIN <> a.CHAIN OR b.DYEAR >= a.DYEAR").fetchone()[0]
    assert bad == 0


def test_tree_link_roots(con):
    # a tree's root is the root of its predecessor
    bad = con.execute("SELECT COUNT(*) FROM TREE t JOIN tree_link a ON a.TRE_CN = t.CN JOIN tree_link b ON b.TRE_CN = t.PREV_TRE_CN "
                      "WHERE a.TID <> b.TID").fetchone()[0]
    assert bad == 0


def test_plot25_tree_identities_match_link_trees(con, ref):
    plot, tree, cond = plotdata.load_history_frames(con, ref, PLOT25)
    A = core.link_trees(tree, plot)
    tl = dict(con.execute("SELECT t.TRE_CN, t.TID FROM tree_link t JOIN visit v ON v.PLT_CN = t.PLT_CN WHERE v.KEY=?", (PLOT25,)).fetchall())
    assert len(tl) == len(A)
    assert all(tl[c] == t for c, t in zip(A.CN, A.TID))


def test_plot25_top_predecessor_candidate_is_periodic_90119(con, ref):
    h = plotdata.header(con, ref, PLOT25)
    top = h["predecessors"][0]
    assert top["plot"] == 90119 and top["rank"] == 1
    assert top["label"] == "inferred candidate, not database-linked"
    assert top["n_matched"] >= 2 and top["dist_mi"] <= 1.5 and abs(top["dt_yr"]) <= 0.5


def test_candidates_respect_the_rules(con):
    pc = pd.read_sql_query("SELECT * FROM predecessor_candidate", con)
    assert (pc.DIST_MI <= 1.5).all() and (pc.DT_YR.abs() <= 0.5).all()
    loc = pd.read_sql_query("SELECT KEY, COUNTYCD, DESIGNS FROM plot_location", con).set_index("KEY")
    assert (loc.loc[pc.CAND_KEY, "DESIGNS"].values == "periodic").all()
    assert (loc.loc[pc.KEY, "COUNTYCD"].values == loc.loc[pc.CAND_KEY, "COUNTYCD"].values).all()


def test_bridge_match():
    pairs = build.bridge_match([(68, 8.2), (611, 9.5), (611, 10.2)], [(68, 6.8), (611, 9.0), (611, 9.1), (131, 12.0)], 7.6)
    assert len(pairs) == 3
    assert build.bridge_match([(68, 3.0)], [(68, 9.0)], 7.6) == []           # shrinking 6 in is not a match


def test_resolve_plot_ids(con):
    assert plotdata.resolve_id(con, "91-25") == [PLOT25]
    assert plotdata.resolve_id(con, "45-3-91-25") == [PLOT25]
    assert plotdata.resolve_id(con, "York 25") == [PLOT25]
    assert plotdata.resolve_id(con, "809203876290487") == [PLOT25]      # 2021 PLOT CN
    assert plotdata.resolve_id(con, "44555686010478") == [PLOT25]       # 2000 PLOT CN
    assert plotdata.resolve_id(con, "nonsense") == []

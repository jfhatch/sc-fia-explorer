"""Build integrity (key relationships, manifest) and the no-location-storage constraint."""
import os, re, json, ast
from fiasc import store
from conftest import ROOT


def test_no_orphan_child_rows(con):
    for t in ("COND", "SUBPLOT", "TREE", "SEEDLING", "SITETREE"):
        n = con.execute(f"SELECT COUNT(*) FROM {t} c WHERE NOT EXISTS (SELECT 1 FROM PLOT p WHERE p.CN = c.PLT_CN)").fetchone()[0]
        assert n == 0, t


def test_manifest_and_build_info(con):
    man = {r[0]: r for r in con.execute("SELECT table_name, url, last_modified, content_length, sha256, rows FROM manifest")}
    for t in ("PLOT", "COND", "TREE", "REF_SPECIES"):
        assert t in man and man[t][1].startswith("http") and man[t][4] and man[t][5] > 0
    bi = dict(con.execute("SELECT key, value FROM build_info").fetchall())
    for k in ("build_name", "built_at", "fiadb_version", "timings", "validation", "locations", "visits", "latest_invyr"):
        assert k in bi
    assert json.loads(bi["validation"])["errors"] == []


def test_plot_location_has_one_row_per_key(con):
    n_loc, n_key = con.execute("SELECT COUNT(*), COUNT(DISTINCT KEY) FROM plot_location").fetchone()
    n_vkeys = con.execute("SELECT COUNT(DISTINCT KEY) FROM visit").fetchone()[0]
    assert n_loc == n_key == n_vkeys


def test_no_user_location_tables_or_columns(con):
    """The database holds only public FIADB coordinates (PLOT.LAT/LON and copies); no table stores searches or notes."""
    names = [r[0].lower() for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert not [n for n in names if re.search(r"search|note|annot|query|user|history_loc", n)]


def test_server_never_accepts_a_location_parameter():
    src = open(os.path.join(ROOT, "app", "server.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    params = [a.arg for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
              for a in f.args.args]
    assert not [p for p in params if re.fullmatch(r"(lat|lon|lng|latitude|longitude|radius|point|coords?)", p, re.I)]
    assert "access_log=False" in src and 'host="127.0.0.1"' in src


def test_client_location_search_stays_in_the_browser():
    js = open(os.path.join(ROOT, "app", "static", "app.js"), encoding="utf-8").read()
    body = js[js.index("search by location"):js.index("search by attributes")]
    assert "fetch(" not in body and "api(" not in body                     # no network call in the location search
    assert "localStorage" not in js and "sessionStorage" not in js and "indexedDB" not in js
    assert "history.pushState" not in js and "location.hash" not in js
    html = open(os.path.join(ROOT, "app", "static", "index.html"), encoding="utf-8").read()
    assert "<form" not in html                                               # nothing can be submitted as a GET query
    assert all('autocomplete="off"' in m for m in re.findall(r'<input id="l_(?:lat|lon)"[^>]*>', html))

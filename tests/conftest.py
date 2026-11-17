"""Shared fixtures. The database under test is FIASC_DB if set (used when validating a new build before switching),
otherwise the live build from data/current.json."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import pytest
from fiasc import store, core

PLOT25 = "45-3-91-25"


@pytest.fixture(scope="session")
def db_path():
    p = store.current_db()
    if not p or not os.path.exists(p):
        pytest.skip("no database build available")
    return p


@pytest.fixture(scope="session")
def con(db_path):
    c = store.connect_ro(db_path)
    yield c
    c.close()


@pytest.fixture(scope="session")
def ref(con):
    return core.Ref(con)

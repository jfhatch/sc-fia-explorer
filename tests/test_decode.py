"""Decoding: values come from the FIADB User Guide v9.4 dictionary (or REF tables); anything else is flagged, never guessed."""
import math
from fiasc import core


def test_known_codes_decode():
    r = core.decode("TREE.STATUSCD", 1)
    assert r["status"] == "decoded" and r["text"].startswith("1 = ") and "live" in r["text"].lower()
    assert core.decode("PLOT.KINDCD", 0)["text"].startswith("0 = Periodic")
    assert core.decode("COND.OWNGRPCD", 40.0)["text"].startswith("40 = Private")      # float from SQLite -> int code


def test_zero_padding_tolerated():
    # the guide prints PLOT_NONSAMPLE_REASN_CD as '01'; the database stores 1
    assert core.decode("PLOT.PLOT_NONSAMPLE_REASN_CD", 1)["status"] == "decoded"


def test_undecoded_value_is_flagged_not_guessed():
    r = core.decode("TREE.AGENTCD", 81)                  # in the 80s range, but no source defines 81 itself
    assert r["status"] == "undecoded"
    assert "undecoded" in r["text"].lower() and "=" not in r["text"]
    assert ("TREE.AGENTCD", "81") in core.UNDECODED
    r = core.decode("TREE.STATUSCD", 7)
    assert r["status"] == "undecoded" and r["text"] == "7 (not in guide)"


def test_column_without_code_table_is_flagged():
    r = core.decode("TREE.TREEGRCD", 3)
    assert r["status"] == "no_table" and "no code table" in r["text"]


def test_alias_columns_share_the_transcribed_list():
    a = core.decode("TREE.DAMAGE_AGENT_CD2", 0)
    b = core.decode("TREE.DAMAGE_AGENT_CD1", 0)
    assert a["status"] == b["status"] == "decoded" and a["text"] == b["text"]


def test_blank_values():
    for v in (None, float("nan"), ""):
        assert core.decode("TREE.STATUSCD", v)["status"] == "blank"


def test_decode_row_covers_every_coded_column(ref):
    row = {"STATUSCD": 2, "AGENTCD": 30, "SPCD": 131, "DIA": 9.1, "TREEGRCD": 1}
    d = core.decode_row("TREE", row, ref)
    assert set(d) == {"STATUSCD", "AGENTCD", "SPCD", "TREEGRCD"}          # DIA is a measurement, not a code
    assert d["SPCD"]["text"] == "131 = loblolly pine"
    assert d["TREEGRCD"]["status"] == "no_table"


def test_ref_decoding_flags_unknown_codes(ref):
    assert ref.decode_ref("SPCD", 99999)["status"] == "undecoded"
    assert ref.decode_ref("FORTYPCD", 161)["status"] == "decoded"

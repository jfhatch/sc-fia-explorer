"""Refresh the FIADB User Guide part of fiasc/help.json.

Usage: python -I scripts/build_help.py <FIADB User Guide v9.4 as text (pdftotext of the Database Description)> [--db <sqlite>] [--check]

fiasc/help.json is the single source of the site's explanations (plot page, glossary, local PDF summary). It has two
kinds of content:
  * hand-written plain-English text (sections, glossary, derived columns, and "plain" overrides for FIADB columns),
    based on the User Guide wording and citing its section numbers; this script never changes it;
  * "guide" fields for every FIADB column the site can show: the column's User Guide section, its short label (the
    column list at the start of each table section) and the first sentences of its description, and the unit when
    the description states one. These are regenerated from the guide text by this script.
  * "nodef" for columns the site shows that the v9.4 guide does not describe (with --db: every non-empty column of
    TABLES in that build). The legacy SOILS_* tables are not in v9.4; a column with the same name in the v9.4
    SUBP_SOIL_SAMPLE_LOC / SUBP_SOIL_SAMPLE_LAYER tables is cited from there, and the text says so.
The guide text itself is not part of the repository.
"""
import os, re, sys, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELP = os.path.join(ROOT, "fiasc", "help.json")
# tables whose columns the site shows (visit details, tree tables)
TABLES = ["PLOT", "COND", "TREE", "SEEDLING", "SITETREE", "P2VEG_SUBP_STRUCTURE", "P2VEG_SUBPLOT_SPP", "INVASIVE_SUBPLOT_SPP",
          "COND_DWM_CALC", "DWM_VISIT", "DWM_COARSE_WOODY_DEBRIS", "DWM_FINE_WOODY_DEBRIS", "DWM_DUFF_LITTER_FUEL",
          "DWM_MICROPLOT_FUEL", "DWM_RESIDUAL_PILE", "DWM_TRANSECT_SEGMENT", "SOILS_VISIT", "SOILS_SAMPLE_LOC", "SOILS_LAB",
          "SOILS_EROSION", "SUBPLOT", "SUBP_COND", "POP_PLOT_STRATUM_ASSGN", "TREE_GRM_COMPONENT"]
LEGACY = {"SOILS_SAMPLE_LOC": "SUBP_SOIL_SAMPLE_LOC", "SOILS_LAB": "SUBP_SOIL_SAMPLE_LAYER"}
SKIP = {"CN", "PLT_CN", "PREV_PLT_CN", "SRV_CN", "CTY_CN", "STATECD", "UNITCD", "COUNTYCD", "PLOT", "INVYR", "CYCLE", "SUBCYCLE",
        "CREATED_BY", "CREATED_DATE", "CREATED_IN_INSTANCE", "MODIFIED_BY", "MODIFIED_DATE", "MODIFIED_IN_INSTANCE"}
NOISE = re.compile(r"^(=====PAGE \d+=====|Chapter \d.*\(revision.*|FIADB User Guides - Volume.*|\s*)$")
UNITS = [(r"\b(?:in|to the nearest(?: [\d.]+)?) (?:whole )?(?:inch(?:es)?|0\.1 inch)\b", "in"), (r"\bin feet\b|\bto the nearest (?:whole )?f(?:oo|ee)t\b", "ft"),
         (r"\bin percent\b|\bpercent(?:age)? (?:cover|of)\b", "%"), (r"\bin years\b|\(years\)", "years"), (r"\bin acres\b", "acres"),
         (r"\bcubic feet per acre\b", "ft³/ac"), (r"\bcubic feet\b", "ft³"), (r"\bsquare feet per acre\b", "ft²/ac"),
         (r"\btons per acre\b", "tons/ac"), (r"\bpounds\b", "lb"), (r"\bin degrees\b|\bdegrees\b", "degrees"), (r"\bin centimeters\b", "cm"),
         (r"\bin grams\b", "g"), (r"\bin miles\b", "mi")]


def clean(t):
    """Symbol-font characters from the PDF text layer: U+F020-F07E map to ASCII; F0B3/F0A3 are >= / <=."""
    t = t.replace("", "≥").replace("", "≤").replace("", "•").replace("�", "•")
    return re.sub("[-]", lambda m: chr(ord(m.group()) - 0xF000), t)


def parse(path):
    lines = [clean(l.rstrip()) for l in open(path, encoding="utf-8", errors="replace")]
    text = "\n".join(lines)
    sec_table = {}                       # "3.1" -> "TREE"
    for m in re.finditer(r"^(\d+\.\d+) [^\n]*?(?:\. ?){3,}[^\n]*\n\(Oracle table name: (\w+)\)", text, re.M):
        sec_table.setdefault(m.group(1), m.group(2))
    label = {}                           # (table, col) -> short label from the column list
    for m in re.finditer(r"^(\d+\.\d+)\.(\d+) ([A-Z][A-Z0-9_]*) (.+?) (?:NUMBER|VARCHAR2|DATE|CHAR|FLOAT|INTEGER)\b", text, re.M):
        t = sec_table.get(m.group(1))
        if t:
            label.setdefault((t, m.group(3)), (f"{m.group(1)}.{m.group(2)}", m.group(4).strip()))
    desc = {}                            # (table, col) -> description paragraph
    # body headings: "2.5.19 STDSZCD"; the PDF text layer sometimes drops leading digits (".5.19 STDSZCD", "5.37 DSTRBCD1"),
    # so a truncated number is resolved against the column list (same column name, section number ending the same way)
    head = re.compile(r"^(\.?\d+(?:\.\d+)+) ([A-Z][A-Z0-9_]*)\s*$")
    by_col = {}
    for (t, c), (sec, _) in label.items():
        by_col.setdefault(c, []).append((t, sec))

    def resolve(num, col):
        full = re.match(r"^(\d+\.\d+)\.\d+$", num)
        if full and sec_table.get(full.group(1)):
            return sec_table[full.group(1)], num
        num = num.lstrip(".")
        hits = [(t, sec) for t, sec in by_col.get(col, []) if sec == num or sec.endswith("." + num)]
        return hits[0] if len(hits) == 1 else (None, None)
    i = 0
    while i < len(lines):
        m = head.match(lines[i])
        t, sec = resolve(m.group(1), m.group(2)) if m else (None, None)
        if t:
            col = m.group(2)
            buf, j = [], i + 1
            while j < len(lines) and not head.match(lines[j]) and not re.match(r"^\d+\.\d+ [A-Z]", lines[j]):
                if not NOISE.match(lines[j]):
                    buf.append(lines[j].strip())
                j += 1
            para = re.sub(r"\s+", " ", " ".join(buf)).strip()
            if (t, col) not in desc:
                desc[(t, col)] = (sec, para)
            i = j
            continue
        i += 1
    for k, (sec, lab) in label.items():                 # no body entry found: the column list's label is the text
        desc.setdefault(k, (sec, lab + "."))
    return label, desc


def first_sentences(p, n=2, limit=320):
    p = re.split(r"\s(?:Codes?:|Code Description|Note:)\s", p)[0]
    parts = re.split(r"(?<=[a-z0-9)\]]\.)\s+(?=[A-Z(])", p)
    out = ""
    for s in parts[:n]:
        if out and len(out) + len(s) > limit:
            break
        out = (out + " " + s).strip()
    return out[:limit].rsplit(" ", 1)[0] + "…" if len(out) > limit else out


def unit_of(p):
    for rx, u in UNITS:
        if re.search(rx, p, re.I):
            return u
    return ""


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    if not a:
        print(__doc__); return 2
    label, desc = parse(a[0])
    H = json.load(open(HELP, encoding="utf-8"))
    cols = H.setdefault("columns", {})
    n_new = n_upd = 0
    legacy = {v: k for k, v in LEGACY.items()}
    for (t, c), (sec, para) in sorted(desc.items()):
        if t in legacy:
            if (legacy[t], c) in desc:
                continue
            note, t = f"Described in the v9.4 guide for {t}.{c}; the legacy {legacy[t]} table itself is not in v9.4.", legacy[t]
        if t not in TABLES:
            continue
        else:
            note = None
        k = f"{t}.{c}"
        e = cols.setdefault(k, {})
        n_new += not e
        lab = label.get((t, c), (sec, ""))[1]
        txt = first_sentences(para)
        g = {"sec": sec, "label": lab or txt.split(". ")[0].rstrip("."), "text": txt, "unit": unit_of(txt)}
        if note:
            g["note"] = note
        if e.get("guide") != g:
            n_upd += 1
        e["guide"] = g
    if "--db" in sys.argv:
        import sqlite3
        con = sqlite3.connect(f"file:{sys.argv[sys.argv.index('--db') + 1]}?mode=ro", uri=True)
        for t in TABLES:
            if not con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone():
                continue
            for c in [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]:
                k = f"{t}.{c}"
                if c in SKIP or c.endswith("_CN") or "guide" in cols.get(k, {}) or "plain" in cols.get(k, {}):
                    continue
                if not con.execute(f'SELECT 1 FROM "{t}" WHERE "{c}" IS NOT NULL LIMIT 1').fetchone():
                    continue
                cols.setdefault(k, {})["nodef"] = (f"{t}.{c} is not described in the FIADB User Guide v9.4"
                                                  + (" (the legacy " + t + " table is not in v9.4)." if t.startswith("SOILS_") else "."))
    for k in [k for k in cols if "guide" not in cols[k] and "plain" not in cols[k] and "nodef" not in cols[k]]:
        print("no guide entry and no plain text:", k)
    if "--check" not in sys.argv:
        json.dump(H, open(HELP, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=False)
    print(f"{len([k for k in desc if k[0] in TABLES])} guide column entries for {len(TABLES)} tables; {n_new} new, {n_upd} updated; "
          f"{sum(1 for e in cols.values() if 'plain' in e)} with plain-English text")


if __name__ == "__main__":
    sys.exit(main())

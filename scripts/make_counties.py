"""Convert the Census cartographic boundary county shapefile (derived from TIGER/Line) to a South Carolina GeoJSON
bundled with the app.

Usage: python -I scripts/make_counties.py <path to cb_YYYY_us_county_500k.shp> [STATEFP]
Writes app/static/sc_counties.geojson (coordinates rounded to 5 decimals, about 1 m).
"""
import sys, os, json
import shapefile  # pyshp

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "app", "static", "sc_counties.geojson")
shp = sys.argv[1]
state = sys.argv[2] if len(sys.argv) > 2 else "45"

r = shapefile.Reader(shp)
fields = [f[0] for f in r.fields[1:]]
feats = []
for sr in r.iterShapeRecords():
    rec = dict(zip(fields, sr.record))
    if rec["STATEFP"] != state:
        continue
    geom = sr.shape.__geo_interface__

    def rnd(c):
        return [rnd(x) for x in c] if isinstance(c[0], (list, tuple)) else [round(c[0], 5), round(c[1], 5)]
    geom = {"type": geom["type"], "coordinates": rnd(geom["coordinates"])}
    feats.append({"type": "Feature", "properties": {"COUNTYCD": int(rec["COUNTYFP"]), "NAME": rec["NAME"], "GEOID": rec["GEOID"]},
                  "geometry": geom})
feats.sort(key=lambda f: f["properties"]["COUNTYCD"])
src = os.path.basename(shp)
json.dump({"type": "FeatureCollection", "source": f"U.S. Census Bureau cartographic boundary file {src} (derived from TIGER/Line)",
           "features": feats}, open(OUT, "w"), separators=(",", ":"))
print(f"wrote {OUT}: {len(feats)} counties, {os.path.getsize(OUT) // 1024} KB")

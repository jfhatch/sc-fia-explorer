# SC FIA plot explorer

**Live site: https://jfhatch.github.io/sc-fia-explorer/**

A map and plot-by-plot history of South Carolina's Forest Inventory and Analysis (FIA) plots, built only from public FIADB DataMart CSVs.

It provides:
- Every plot location at its public (fuzzed) coordinates, with filters.
- Search by plot ID, location or attributes.
- A plot page for each plot, covering:
  - the visit timeline and inferred periodic predecessors;
  - decoded condition, tree, seedling, vegetation, invasive, down woody material and soils data;
  - species and tree histories, growth, mortality and ingrowth;
  - CSV export and a printable summary.

The project runs two ways:
- **Public static website** on GitHub Pages, rebuilt monthly by GitHub Actions. This is the `web/` frontend plus files from `scripts/export_static.py`.
- **Local app** using FastAPI + SQLite (`app/`). It adds the server-rendered PDF summaries and the in-app Data panel for one-click updates and rollback.

Both share the build, decoding, metrics and validation code in `fiasc/`.

## How the public site is updated
`.github/workflows/build-deploy.yml` runs at 09:17 UTC on the 3rd of every month, and can also be started manually. It:
1. Sets up Python 3.12 and sends HEAD requests to every DataMart table. It compares Last-Modified, Content-Length and ETag with `ci/datamart_manifest.json`, which is committed in this repo. If nothing changed, it stops there.
2. Otherwise it:
   - restores cached downloads;
   - downloads the changed tables;
   - builds the SQLite database from scratch;
   - validates the build: row counts, key relationships, and Plot 45-3-91-25 at 35/82/82/101/92 ft²/ac for 2000–2021;
   - runs the full test suite;
   - exports the static site. The export fails over 900 MB total or 50 MB per file.
3. Deploys with `actions/upload-pages-artifact` and `actions/deploy-pages`, then commits the new manifest.

If any step fails, nothing is deployed and the live site stays as it was.

**Manual rebuild:**
```powershell
gh workflow run build-deploy.yml                 # rebuild only if the DataMart changed
gh workflow run build-deploy.yml -f force=true   # rebuild and redeploy regardless
gh run watch                                     # follow the run
```

**Roll back** by re-running the deploy job of an earlier successful run. It redeploys that run's site artifact; artifacts are kept for 90 days.
```powershell
gh run list --workflow build-deploy.yml --status success
gh run view <run-id> --json jobs --jq '.jobs[] | select(.name=="deploy") | .databaseId'
gh run rerun <run-id> --job <deploy-job-id>
```

Re-run only the **deploy** job. Re-running the whole run would rebuild from the current DataMart data.

**Fallback if the DataMart blocks GitHub's runners:** run `powershell -ExecutionPolicy Bypass -File scripts\publish_local.ps1` on a PC (add `-SkipBuild` to use the current local build). It:
1. builds the database and exports the site;
2. uploads `site.zip` to the rolling `local-site` pre-release;
3. commits the manifest;
4. runs the same workflow with `source=local-release`, which deploys that zip.

Pages stays configured for GitHub Actions, so the monthly runs carry on as normal afterwards.

## Install (local use)
Requirements:
- Windows 10/11 with PowerShell 5.1+ and Microsoft Edge. Edge renders the PDFs and runs the browser tests. The build and the static export also run on Linux, which the workflow uses.
- Python 3.12. It was tested with 3.12.10; 3.11+ should work.
- About 6 GB of free disk space.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -I scripts\build_db.py                 # first run: ~1.2 GB download (10–15 min) + ~2 min build, validation, tests
powershell -ExecutionPolicy Bypass -File run.ps1                 # local app at http://127.0.0.1:8742/ (-Port N, -NoBrowser)
.venv\Scripts\python.exe -I scripts\export_static.py --out site  # static site from the local build
```

**Local updates and rollback.** In the local app, open **Data** for Check for updates, Import updates (with progress, Cancel and a log), What's new, and Restore previous. The same actions are available from the command line:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\update.ps1 -Check
powershell -ExecutionPolicy Bypass -File scripts\update.ps1 -Import      # -AcceptRowDrops to accept >1 % row-count drops
powershell -ExecutionPolicy Bypass -File scripts\update.ps1 -Rollback    # the two previous builds are kept
```

## Basemaps
The public site uses USGS The National Map:
- **Topo** is the default.
- **Imagery + Topo** is imagery with the Topo tiles overlaid at 45 % opacity. USGS has retired its combined ImageryTopo service.
- **Imagery only.**
- **Plain** shows only the bundled county boundaries and requests no tiles.

The map switches to Plain on its own after repeated tile errors, or when the browser is offline. The local app uses OpenStreetMap, with the same Plain offline option.

## Privacy and security
- The site uses public FIADB data only. Plot coordinates are fuzzed and swapped (see the site's About page).
- There are no analytics, cookies or third-party scripts. Leaflet, Leaflet.markercluster and Plotly are vendored in `web/vendor`.
- A Content-Security-Policy meta tag allows only the site itself, plus images from `basemap.nationalmap.gov`. Inline *styles* are allowed because Leaflet and Plotly set element styles; no inline scripts are allowed.
- Location search runs only in the browser. The point is never sent anywhere, stored, or put in the URL.

## Tests
```powershell
.venv\Scripts\python.exe -I -m pytest -q tests                                       # unit + database tests
.venv\Scripts\python.exe -I scripts\test_static_edge.py --latlon "<lat>,<lon>" --site site
.venv\Scripts\python.exe -I scripts\test_static_edge.py --latlon "<lat>,<lon>" --url https://jfhatch.github.io/sc-fia-explorer/
.venv\Scripts\python.exe -I scripts\test_ui_edge.py --latlon "<lat>,<lon>"          # local app
.venv\Scripts\python.exe -I scripts\test_update_e2e.py                              # local update flow, in a sandbox
```

The `--latlon` point is used only for that run. Nothing in the repo stores it.

## Layout
- `fiasc/`: shared logic.
  - `core.py`: decoding with the FIADB User Guide v9.4 dictionary in `fiasc/codes/`, tree linking, per-acre values, events.
  - `build.py`: CSV to SQLite, derived tables and validation.
  - `fetch.py`, `datamart.py`: resumable downloads.
  - `updater.py`, `store.py`: local updates and rollback.
  - `plotdata.py`, `summary_pdf.py`: plot data and the PDF summary.
- `web/`: the static frontend.
  - `index.html` + `map.js`: the map.
  - `plot.html` + `plot.js`: the plot page.
  - `about.html`.
  - `fia.js`: data loading and decoding.
- `scripts/`:
  - building: `build_db.py`, `export_static.py`, `ci_manifest.py`;
  - publishing: `publish_local.ps1`, `update.ps1`, `package.py`;
  - tests: `test_*.py`.
- `app/`: the local FastAPI app.
- `ci/datamart_manifest.json`: the DataMart headers of the deployed build.
- `data/` (builds, downloads) and `site/` (generated) are not committed.

## Caveats
- Per-acre values are unadjusted single-plot expansions: Σ(value × TPA_UNADJ), with no stratum adjustment.
- Periodic (variable-radius) designs are not comparable with national-design plots.
- Values not in the FIADB User Guide v9.4 or the REF tables are flagged, never guessed.
- Periodic predecessors are *inferred candidates* (county, distance, date and bridge-tree matches), not database links.

# NCUB Collaboration Progress Monitor — build kit

Everything needed to regenerate the dashboard from the HESA panel data.

## Contents

```
build_dashboard.py      ← the build script (data pipeline + HTML assembly)
hesa_panel_clean.csv    ← input data (231 providers, 2014/15–2024/25)
regions.json            ← UK region boundaries (ONS, pre-simplified)
templates/
  part1.html            ← head, CSS, nav, Home + Economic context tabs
  part2.html            ← Findings, Skills, Institution explorer tabs
  part3.html            ← all JavaScript (charts, map, exports)
```

## Run it

Anywhere with Python 3.9+ and pandas:

```bash
pip install pandas
python build_dashboard.py
```

This writes `ncub_cpm_dashboard.html`. Open it in any browser — the only
external dependency is Plotly, loaded once from cdnjs.

Custom input/output paths:

```bash
python build_dashboard.py path/to/new_panel.csv my_dashboard.html
```

No local Python? It also runs in **Google Colab** (upload the kit, run the
script, download the HTML) or any Jupyter environment.

## Updating with new data

Drop in a new CSV with the same column names and re-run. The script expects:
`ukprn, he_provider, region_of_he_provider, academic_year, cluster, ay_cpi,
bci_sme, bci_lc, bci_total`, plus the HE-BCI interaction, CPD, contract,
licensing, spinout and HE-funds columns. Extra years are picked up
automatically — all charts, the scorecard baselines, the map year selector
and the CSV exports adapt to whatever years are present.

`ay_cpi` must be indexed so the **latest year = 100**; all real-terms figures
deflate to that base.

## Editing the dashboard

- **Text/layout/colours** → `templates/part1.html` and `part2.html`
  (NCUB palette is defined once in the `:root` CSS variables).
- **Charts, map, scorecard logic, exports** → `templates/part3.html`.
- **Metric definitions** (what counts as an interaction, deflation, etc.)
  → `build_dashboard.py`, section 1.
- The context-tab charts (GDP, OECD comparison, BERD, VC) are hard-coded
  digitisations of the NCUB 2025 figures inside `part3.html`
  (`renderContext()`); replace those arrays when you have the source series.

## Automatic data updates (Economic context tab)

The context charts can refresh themselves from live sources:

```bash
pip install requests
python build_dashboard.py --fetch     # fetch latest data, then build
# or separately:
python fetch_context.py               # writes context_data.json
python build_dashboard.py             # picks it up automatically
```

What updates live:

| Chart | Source | Status |
|---|---|---|
| Monthly GDP + sector contributions | ONS time-series API (MGDP: ECY2, ECY4, ECY9, ECY3) | live |
| UK quarterly GDP growth | ONS time-series API (IHYQ) | live |
| EU / US / Japan quarterly growth | OECD SDMX API | best-effort* |
| Universities in deficit | HESA finance open data (annual) | cached |
| Business R&D (BERD) | ONS BERD release (annual) | cached |
| Venture capital % GDP | OECD (annual) | cached |

*The OECD API query is configured at the top of `fetch_context.py`; if OECD
changes its endpoint, rebuild the URL with https://data-explorer.oecd.org
and paste it in. Every block fails safe: anything unreachable keeps the
cached values and the dashboard still builds.

Sector contributions are approximated as GVA-weight × sector growth, with
services as the residual so the bars always sum to net GDP growth (weights
configurable in `fetch_context.py`). The annual series change once a year —
update them by editing `context_cache.json` when the new releases land.

## Fully hands-free: GitHub Actions

`.github/workflows/update-dashboard.yml` is included. Push the kit to a
GitHub repo, enable Pages (Settings → Pages → Source: GitHub Actions), and
the dashboard rebuilds itself with fresh ONS data on the 16th of every
month (just after the monthly GDP release), on every push, or on demand
via the Actions tab. The published URL serves the latest build —
no manual steps at all.

## Hosting

The output is a single static file, so any static host works:

- **GitHub Pages**: commit the HTML to a repo, enable Pages — done.
- SharePoint / OneDrive / internal intranet: upload the file.
- A web server: drop it in the document root.

No backend, database or build step is needed at serve time.

## Regenerating the boundaries (optional)

`regions.json` ships pre-built. To rebuild it from source (e.g. higher
detail), download `eer.json` (GB) and the NI outline from
github.com/martinjc/UK-GeoJSON, then simplify with shapely
(`simplify(geom, 0.02)`, drop polygons with area < 0.005, round coords to
3 dp) and write features with a `properties.region` field matching the
region names in the CSV ("Eastern" → "East of England",
"Yorkshire and the Humber" → "Yorkshire and The Humber").

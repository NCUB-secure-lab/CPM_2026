#!/usr/bin/env python3
"""
fetch_context.py — refresh the Economic Context tab from live sources
=====================================================================
Pulls the latest series from public APIs and writes context_data.json,
which build_dashboard.py embeds into the dashboard. Every block is
independent: if a source is unreachable or its format changes, the
bundled/cached values for that chart are kept and a warning is printed.

Live sources implemented:
  1. UK monthly GDP + sector contributions  → ONS time-series API (dataset MGDP)
  2. UK quarterly GDP growth                → ONS time-series API (IHYQ)
  3. EU / US / Japan quarterly GDP growth   → OECD SDMX API (best-effort)

Kept as cached values (annual releases, update once a year):
  4. % universities in deficit  → recompute from HESA finance open data
  5. Business R&D (BERD)        → ONS annual BERD release (spreadsheet)
  6. Venture capital % GDP      → OECD Entrepreneurship Finance

Usage:
    python fetch_context.py            # writes context_data.json
    python build_dashboard.py --fetch  # fetch + build in one step

Requires:  pip install requests
"""
import json, os, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "context_cache.json")
OUT = os.path.join(HERE, "context_data.json")

# ── configuration ────────────────────────────────────────────────────────
ONS_API = "https://api.ons.gov.uk/timeseries/{cdid}/dataset/{dataset}/data"

# Monthly GDP (dataset MGDP) — chained-volume indices, seasonally adjusted
MGDP_CDIDS = {"gdp": "ECY2", "production": "ECY4",
              "construction": "ECY9", "agriculture": "ECY3"}
# Approximate GVA weights used to turn sector growth into contributions.
# Services is computed as the residual, so it absorbs weight drift.
WEIGHTS = {"production": 0.135, "construction": 0.062, "agriculture": 0.007}
N_MONTHS = 24            # how many recent months to show

ONS_QUARTERLY_UK = ("IHYQ", "QNA")   # GDP q/q growth, %
N_QUARTERS = 12

# OECD SDMX — quarterly GDP growth for comparators. The OECD data API moved
# in 2024 to sdmx.oecd.org; if this query stops working, rebuild it with the
# query builder at https://data-explorer.oecd.org (dataset: Quarterly GDP
# growth) and paste the new URL here. Best-effort: falls back to cache.
OECD_URL = ("https://sdmx.oecd.org/public/rest/data/"
            "OECD.SDD.NAD,DSD_NAMAIN1@DF_QNA_EXPENDITURE_GROWTH_OECD,1.1/"
            "Q..{area}.S1..B1GQ......G1.?startPeriod={start}"
            "&dimensionAtObservation=AllDimensions&format=jsondata")
OECD_AREAS = {"EU": "EA20", "United States": "USA", "Japan": "JPN"}

# ── helpers ──────────────────────────────────────────────────────────────
def get_json(url, timeout=30):
    import requests
    r = requests.get(url, timeout=timeout,
                     headers={"Accept": "application/json",
                              "User-Agent": "NCUB-CPM-dashboard/1.0"})
    r.raise_for_status()
    return r.json()

def ons_monthly(cdid, dataset="mgdp"):
    """Return [(\"YYYY MMM\", value), ...] for an ONS monthly series."""
    j = get_json(ONS_API.format(cdid=cdid.lower(), dataset=dataset))
    return [(m["date"], float(m["value"])) for m in j["months"] if m["value"] not in ("", None)]

def ons_quarterly(cdid, dataset="qna"):
    j = get_json(ONS_API.format(cdid=cdid.lower(), dataset=dataset))
    return [(q["date"], float(q["value"])) for q in j["quarters"] if q["value"] not in ("", None)]

def mom_growth(series):
    """index series -> {date: m/m % growth}"""
    out = {}
    for (d0, v0), (d1, v1) in zip(series, series[1:]):
        if v0:
            out[d1] = (v1 / v0 - 1) * 100
    return out

def short_month(d):                       # "2025 NOV" -> "Nov 25"
    y, m = d.split()
    return m.title()[:3] + " " + y[2:]

def short_quarter(d):                     # "2024 Q1" -> "24Q1"
    y, q = d.split()
    return y[2:] + q

# ── fetch blocks ─────────────────────────────────────────────────────────
def fetch_gdp_monthly(ctx, live):
    idx = {k: ons_monthly(c) for k, c in MGDP_CDIDS.items()}
    g = {k: mom_growth(v) for k, v in idx.items()}
    months = [d for d, _ in idx["gdp"]][-N_MONTHS:]
    months = [m for m in months if m in g["gdp"]]
    prod, cons, serv = [], [], []
    for m in months:
        cp = WEIGHTS["production"] * g["production"].get(m, 0)
        cc = WEIGHTS["construction"] * g["construction"].get(m, 0)
        ca = WEIGHTS["agriculture"] * g["agriculture"].get(m, 0)
        net = g["gdp"][m]
        prod.append(round(cp, 2)); cons.append(round(cc, 2))
        serv.append(round(net - cp - cc - ca, 2))   # services = residual
    ctx["gdpMonthly"] = {"months": [short_month(m) for m in months],
                         "services": serv, "production": prod, "construction": cons}
    live.append("ONS monthly GDP (MGDP: %s)" % ", ".join(MGDP_CDIDS.values()))

def fetch_uk_quarterly(ctx, live):
    cdid, ds = ONS_QUARTERLY_UK
    q = ons_quarterly(cdid, ds)[-N_QUARTERS:]
    quarters = [short_quarter(d) for d, _ in q]
    uk = [round(v, 2) for _, v in q]
    old = ctx["intl"]
    ctx["intl"] = {"quarters": quarters,
                   "series": {"UK": uk,
                              **{k: align(old, k, quarters) for k in old["series"] if k != "UK"}}}
    live.append("ONS quarterly GDP growth (%s/%s)" % (cdid, ds))

def align(old, key, quarters):
    """Re-align a cached comparator series onto the new quarter axis."""
    lookup = dict(zip(old["quarters"], old["series"][key]))
    return [lookup.get(q) for q in quarters]

def fetch_oecd(ctx, live):
    import re
    start = "20" + ctx["intl"]["quarters"][0][:2] + "-Q1"
    for name, area in OECD_AREAS.items():
        j = get_json(OECD_URL.format(area=area, start=start))
        sets = j["data"]["dataSets"][0]["observations"]
        dims = j["data"]["structures"][0]["dimensions"]["observation"]
        tpos = next(i for i, d in enumerate(dims) if d["id"] == "TIME_PERIOD")
        tvals = [v["id"] for v in dims[tpos]["values"]]
        series = {}
        for key, obs in sets.items():
            t = tvals[int(key.split(":")[tpos])]
            series[re.sub(r"(\d{2})(\d{2})-Q(\d)", r"\2Q\3", t)] = round(obs[0], 2)
        ctx["intl"]["series"][name] = [series.get(q) for q in ctx["intl"]["quarters"]]
    live.append("OECD quarterly GDP growth (EA20, USA, JPN)")

# ── main ─────────────────────────────────────────────────────────────────
def main():
    with open(CACHE, encoding="utf-8") as f:
        ctx = json.load(f)
    live, failed = [], []

    for label, fn in [("UK monthly GDP", fetch_gdp_monthly),
                      ("UK quarterly GDP", fetch_uk_quarterly),
                      ("OECD comparators", fetch_oecd)]:
        try:
            fn(ctx, live)
            print(f"[OK]   {label}")
        except Exception as e:
            failed.append(label)
            print(f"[SKIP] {label}: {type(e).__name__}: {e} — keeping cached values")

    ctx["meta"] = {"updated": datetime.date.today().isoformat(),
                   "live": live, "cached_fallback": failed}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(ctx, f, indent=1)
    print(f"\nWrote {OUT}")
    print("Annual series (deficit %, BERD, VC) use cached values — refresh "
          "those once a year by editing context_cache.json from the latest "
          "HESA / ONS BERD / OECD releases.")
    return 0 if not failed else 0   # never hard-fail: cache covers gaps

if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
NCUB Collaboration Progress Monitor — dashboard builder
=======================================================
Reads the HESA HE-BCI panel CSV, computes all metrics (constant-price BCI,
interactions, licensing, spinouts, medians, regional aggregates), embeds the
data and UK region boundaries into the HTML templates, and writes a single
self-contained dashboard file.

Usage:
    python build_dashboard.py [path/to/hesa_panel_clean.csv] [output.html]

Defaults:
    input  = hesa_panel_clean.csv   (next to this script)
    output = ncub_cpm_dashboard.html

Requirements:  Python 3.9+  and  pandas  (pip install pandas)
"""
import sys, json, os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
args = [a for a in sys.argv[1:] if a != "--fetch"]
FETCH = "--fetch" in sys.argv
CSV_PATH = args[0] if len(args) > 0 else os.path.join(HERE, "hesa_panel_clean.csv")
OUT_PATH = args[1] if len(args) > 1 else os.path.join(HERE, "ncub_cpm_dashboard.html")

if FETCH:
    import fetch_context
    fetch_context.main()

# ──────────────────────────────────────────────────────────────────────────
# 1. Load and derive metrics
# ──────────────────────────────────────────────────────────────────────────
df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
df["cluster"] = df["cluster"].fillna("Unclassified")
num = lambda s: pd.to_numeric(s, errors="coerce").fillna(0)

# interaction counts (consultancy + facilities & equipment + contract research)
df["n_sme"] = num(df.int_n_consult_sme) + num(df.int_n_fe_sme) + num(df.contract_int_n_sme)
df["n_lc"]  = num(df.int_n_consult_lc)  + num(df.int_n_fe_lc)  + num(df.contract_int_n_lc)
df["n_tot"] = (df.n_sme + df.n_lc + num(df.int_n_consult_nc)
               + num(df.int_n_fe_nc) + num(df.contract_int_n_nc))

# licensing — business income only (SME + large business across non-software,
# other IP and software streams; excludes non-commercial *_nc columns)
lic_cols = ["license_inc_nsw_lc_000gbp", "license_inc_nsw_sme_000gbp",
            "license_inc_ip_lc_000gbp",  "license_inc_ip_sme_000gbp",
            "license_inc_sw_lc_000gbp",  "license_inc_sw_sme_000gbp"]
df["lic_inc"] = df[lic_cols].apply(num).sum(axis=1)
# breakdown of business licensing income by stream × business size, real terms
df["lic_nsw_sme"] = num(df.license_inc_nsw_sme_000gbp) / df.ay_cpi * 100
df["lic_nsw_lc"]  = num(df.license_inc_nsw_lc_000gbp)  / df.ay_cpi * 100
df["lic_ip_sme"]  = num(df.license_inc_ip_sme_000gbp)  / df.ay_cpi * 100
df["lic_ip_lc"]   = num(df.license_inc_ip_lc_000gbp)   / df.ay_cpi * 100
df["lic_sw_sme"]  = num(df.license_inc_sw_sme_000gbp)  / df.ay_cpi * 100
df["lic_sw_lc"]   = num(df.license_inc_sw_lc_000gbp)   / df.ay_cpi * 100
# licence count breakdown (business clients)
df["lic_n_nsw_sme"] = num(df.nonsoftware_sme)
df["lic_n_nsw_lc"]  = num(df.nonsoftware_lc)
df["lic_n_sw_sme"]  = num(df.software_sme)
df["lic_n_sw_lc"]   = num(df.software_lc)
# IP pipeline
df["disclosures"]  = num(df.n_disclosures)
df["pat_filed"]    = num(df.n_patents_filed)
df["pat_ext"]      = num(df.n_external_patents)
df["lic_n"] = (num(df.nonsoftware_sme) + num(df.nonsoftware_lc)
               + num(df.software_sme) + num(df.software_lc))

# constant 2024/25 prices (£000): nominal / CPI * 100  (ay_cpi: 2024/25 = 100)
defl = lambda col: num(df[col]) / df.ay_cpi * 100
df["real"]     = defl("bci_total")
df["real_sme"] = defl("bci_sme")
df["real_lc"]  = defl("bci_lc")
# income streams, business clients only (SME + large; excludes non-commercial)
df["contract_v"] = (num(df.contract_int_v_sme_000gbp) + num(df.contract_int_v_lc_000gbp)) / df.ay_cpi * 100
df["consult_v"]  = (num(df.int_v_consult_sme_000gbp) + num(df.int_v_consult_lc_000gbp)) / df.ay_cpi * 100
df["fe_v"]       = (num(df.int_v_fe_sme_000gbp) + num(df.int_v_fe_lc_000gbp)) / df.ay_cpi * 100
df["lic_real"] = df.lic_inc / df.ay_cpi * 100
df["uk_ind"]   = defl("hefunds_uk_industry")
df["hef_tot"]  = defl("hefunds_total")
df["spin"] = num(df.n_spinouts_surv3)
# estimated external investment in active spinouts (£000), real terms.
df["ext_real"] = num(df.external_investment_spin) / df.ay_cpi * 100
# one anomalous return (>£20bn from a single provider-year) excluded from
# national totals but kept in provider-level views and exports
ANOM = 2.0e7
df["ext_capped"] = df.ext_real.where(df.ext_real <= ANOM, 0)
df["pat"]  = num(df.n_patents_granted)
df["disc"] = num(df.n_disclosures)

years = sorted(df.academic_year.unique())
r1 = lambda x: round(float(x), 1)
opt = lambda v, f=r1: None if pd.isna(v) else f(v)

# ── per-institution records ───────────────────────────────────────────────
unis = {}
for (ukprn, name), g in df.groupby(["ukprn", "he_provider"]):
    g = g.set_index("academic_year").reindex(years)
    unis[str(ukprn)] = {
        "name": name,
        "region": g.region_of_he_provider.dropna().iloc[0],
        "cluster": g.cluster.dropna().iloc[0],
        "real":     [opt(v) for v in g.real],
        "real_sme": [opt(v) for v in g.real_sme],
        "real_lc":  [opt(v) for v in g.real_lc],
        "n_sme":    [opt(v, int) for v in g.n_sme],
        "n_lc":     [opt(v, int) for v in g.n_lc],
        "contract": [opt(v) for v in g.contract_v],
        "consult":  [opt(v) for v in g.consult_v],
        "fe":       [opt(v) for v in g.fe_v],
        "lic":      [opt(v) for v in g.lic_real],
        "lic_n":    [opt(v, int) for v in g.lic_n],
        "spin":     [opt(v, int) for v in g.spin],
        "ext":      [opt(v) for v in g.ext_real],
        "pat":      [opt(v, int) for v in g.pat],
        "uk_ind":   [opt(v) for v in g.uk_ind],
        # licensing income breakdown (real £000)
        "lic_nsw_sme": [opt(v) for v in g.lic_nsw_sme],
        "lic_nsw_lc":  [opt(v) for v in g.lic_nsw_lc],
        "lic_ip_sme":  [opt(v) for v in g.lic_ip_sme],
        "lic_ip_lc":   [opt(v) for v in g.lic_ip_lc],
        "lic_sw_sme":  [opt(v) for v in g.lic_sw_sme],
        "lic_sw_lc":   [opt(v) for v in g.lic_sw_lc],
        # licence counts
        "lic_n_nsw_sme": [opt(v, int) for v in g.lic_n_nsw_sme],
        "lic_n_nsw_lc":  [opt(v, int) for v in g.lic_n_nsw_lc],
        "lic_n_sw_sme":  [opt(v, int) for v in g.lic_n_sw_sme],
        "lic_n_sw_lc":   [opt(v, int) for v in g.lic_n_sw_lc],
        # IP pipeline
        "disclosures": [opt(v, int) for v in g.disclosures],
        "pat_filed":   [opt(v, int) for v in g.pat_filed],
        "pat_ext":     [opt(v, int) for v in g.pat_ext],
    }

# ── national aggregates ───────────────────────────────────────────────────
agg = df.groupby("academic_year").agg(
    real=("real", "sum"), real_sme=("real_sme", "sum"), real_lc=("real_lc", "sum"),
    n_sme=("n_sme", "sum"), n_lc=("n_lc", "sum"), n_tot=("n_tot", "sum"),
    contract=("contract_v", "sum"), consult=("consult_v", "sum"), fe=("fe_v", "sum"),
    lic=("lic_real", "sum"), lic_n=("lic_n", "sum"), spin=("spin", "sum"),
    pat=("pat", "sum"), disc=("disc", "sum"), uk_ind=("uk_ind", "sum"),
    hef=("hef_tot", "sum"), n_unis=("he_provider", "count"),
    ext=("ext_capped", "sum"), ext_n_anom=("ext_real", lambda x: int((x > 2.0e7).sum()))
    ).reindex(years)
national = {k: [r1(v) for v in agg[k]] for k in agg.columns}
# median external investment across providers reporting > 0 (real £000)
ext_med = df[df.ext_real > 0].groupby("academic_year").ext_real.median().reindex(years)
national["ext_med"] = [opt(v) or 0 for v in ext_med]

# ── medians (cluster / region / national) ────────────────────────────────
def med_table(group_col):
    out = {}
    for gname, g in df.groupby(group_col):
        s = g.groupby("academic_year").real.median().reindex(years)
        out[gname] = [opt(v) for v in s]
    return out
cluster_med = med_table("cluster")
region_med = med_table("region_of_he_provider")
nat_med = [r1(v) for v in df.groupby("academic_year").real.median().reindex(years)]

# ── latest-year growth per provider (funnel + regional box) ──────────────
growth = {}
for k, rec in unis.items():
    a, b = rec["real"][-2], rec["real"][-1]
    if a and b and a > 200:                       # exclude tiny denominators
        growth[k] = round((b / a - 1) * 100, 1)

# ── regional aggregates (choropleth) ─────────────────────────────────────
regionAgg = {}
for r, g in df.groupby("region_of_he_provider"):
    a = g.groupby("academic_year").agg(
        real=("real", "sum"), n_sme=("n_sme", "sum"), n_lc=("n_lc", "sum"),
        lic=("lic_real", "sum"), spin=("spin", "sum"),
        n=("he_provider", "count")).reindex(years).fillna(0)
    med = g.groupby("academic_year").real.median().reindex(years)
    regionAgg[r] = {
        "real": [r1(v) for v in a.real], "n_sme": [int(v) for v in a.n_sme],
        "n_lc": [int(v) for v in a.n_lc], "lic": [r1(v) for v in a.lic],
        "spin": [int(v) for v in a.spin], "n": [int(v) for v in a.n],
        "med": [opt(v) for v in med]}

# ── geo boundaries (pre-simplified ONS regions, shipped with this kit) ───
with open(os.path.join(HERE, "regions.json"), encoding="utf-8") as f:
    geo = json.load(f)

# ── R&D collaboration (GtR / pillar 4) indicators and trends ────────────
gtr_ind = pd.read_csv(os.path.join(HERE, "ri_indicators.csv"), encoding="utf-8-sig").fillna("")
gtr_tr = pd.read_csv(os.path.join(HERE, "ri_trends_full.csv"), encoding="utf-8-sig")
gtr = {"indicators": gtr_ind.to_dict("records"),
       "trends": {c: [None if pd.isna(v) else (int(v) if c in ("year","V1","V2","V3","I5a","I6a","C4d") else round(float(v),2))
                      for v in gtr_tr[c]] for c in gtr_tr.columns}}

# ── economic context: live-fetched file if present, else bundled cache ──
ctx_file = os.path.join(HERE, "context_data.json")
if not os.path.exists(ctx_file):
    ctx_file = os.path.join(HERE, "context_cache.json")
with open(ctx_file, encoding="utf-8") as f:
    ctx = json.load(f)
print(f"  Context data: {os.path.basename(ctx_file)} "
      f"(updated: {ctx.get('meta',{}).get('updated','n/a')})")

data = {"years": years, "unis": unis, "national": national,
        "clusterMed": cluster_med, "regionMed": region_med, "natMed": nat_med,
        "growth": growth, "regionAgg": regionAgg, "geo": geo, "ctx": ctx,
        "gtr": gtr}

# ──────────────────────────────────────────────────────────────────────────
# 2. Assemble the HTML
# ──────────────────────────────────────────────────────────────────────────
tpl = ""
for part in ("part1.html", "part2.html", "part3.html"):
    with open(os.path.join(HERE, "templates", part), encoding="utf-8") as f:
        tpl += f.read()

html = tpl.replace("__DATA__", json.dumps(data, separators=(",", ":")))
with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write(html)

print(f"[OK] Dashboard written to {OUT_PATH}")
print(f"  Providers: {len(unis)} | Years: {years[0]}–{years[-1]} | "
      f"Size: {os.path.getsize(OUT_PATH)/1e6:.2f} MB")
print("  Open it in any browser (internet needed once, to load Plotly from CDN).")

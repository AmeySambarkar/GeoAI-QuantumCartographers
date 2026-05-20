"""
Claude API analyst — consumes the aggregated feature JSON and generates:
  1. Data Inventory
  2. 3-Year Water Resource Strategy (table)
  3. Python Code (self-contained pipeline replication)
  4. R Code (scenario analysis)
  5. Risk Assessment (table)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert water-resource geospatial analyst and engineer.
You receive structured satellite-derived metrics (NDVI, NDWI, EVI, DEM slope, change vectors,
Maxar scene catalog, and Google Satellite Embedding cosine-change) for an agricultural ROI.

Your task: produce a rigorous, data-grounded 5-section water resource intelligence report in Markdown.

Rules:
- Use only the metrics provided. Do not invent numbers.
- All statistics must be rounded to 3 significant figures.
- Start directly with Section 1. No preamble, no sign-off.
- Every table row must be specific and derived from the data.
- The Python code must be self-contained, runnable, and reference actual band math.
- The R code must load the JSON output and run scenario analysis.
- Risk rows must reference specific metric thresholds from the data."""

USER_TEMPLATE = """Here is the aggregated feature set from the multi-sensor pipeline:

```json
{feature_json}
```

ROI: {roi_name}
Baseline year: {baseline_year} | Analysis year: {analysis_year}
Data sources: {sources}

Produce exactly the following 5-section report:

## 1. Data Inventory
Bullet list: every data source, sensor, metric extracted, and Earth Engine layer.

## 2. 3-Year Water Resource Management Strategy
Table columns: Quarter | Action | Location | Expected Outcome | Success Metric
Minimum 12 rows across 3 years. All actions must be grounded in the NDVI, NDWI, slope, and change data above.

## 3. Python Code
Self-contained script that:
- Opens local GeoTIFFs with rasterio (LISS-4 / HLS)
- Computes NDVI, EVI, MNDWI from band math
- Extracts DEM slope statistics
- Fetches Sentinel-2 from Google Earth Engine and computes change detection
- Queries Maxar STAC API for high-resolution scene metadata
- Outputs a feature_summary.json identical to the aggregated metrics above
Include all imports. Use placeholder paths (configurable via argparse or environment variables).

## 4. R Code
Script that:
- Loads feature_summary.json
- Runs linear regression of NDVI trend
- Runs change-point analysis on the NDVI change time series
- Generates a scenario plot: projected water demand vs. rainfall under drought/normal/wet scenarios
- Outputs a PDF report

## 5. Risk Assessment
Table columns: Risk | Likelihood (H/M/L) | Impact (H/M/L) | Trigger Metric | Mitigation
Minimum 8 rows. All rows must cite specific metric values from the data."""


def generate_report(features_json: str, config) -> str:
    """
    Call Claude API to generate the 5-section water resource report.
    Falls back to a template-based report if no API key is configured.
    """
    if not config.has_anthropic:
        logger.warning("No ANTHROPIC_API_KEY — generating template-based report")
        return _template_report(features_json, config)

    try:
        import anthropic

        data = json.loads(features_json)
        summary = data.get("summary", {})
        roi = data.get("roi", {})

        user_content = USER_TEMPLATE.format(
            feature_json=json.dumps(data["summary"], indent=2),
            roi_name=roi.get("name", "Unknown ROI"),
            baseline_year=data.get("baseline_year", 2018),
            analysis_year=data.get("analysis_year", 2024),
            sources=", ".join(summary.get("data_sources", [])),
        )

        client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        response = client.messages.create(
            model=config.claude_model,
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )

        report = response.content[0].text
        logger.info("Claude report generated (%d chars, %d input / %d output tokens)",
                    len(report), response.usage.input_tokens, response.usage.output_tokens)
        return report

    except ImportError:
        logger.warning("anthropic package not installed — using template report")
        return _template_report(features_json, config)
    except Exception as exc:
        logger.warning("Claude API call failed (%s) — using template report", exc)
        return _template_report(features_json, config)


def _template_report(features_json: str, config) -> str:
    """
    Deterministic template-based report when Claude API is unavailable.
    Fills in real metric values from the feature JSON.
    """
    try:
        data = json.loads(features_json)
    except Exception:
        data = {}

    s = data.get("summary", {})
    roi = data.get("roi", {})
    gee = data.get("gee", {})
    dem = data.get("dem_stats") or {}
    maxar = data.get("maxar", {})
    chg = data.get("change", {})

    ndvi = s.get("ndvi_gee", 0.0)
    ndvi_chg = s.get("ndvi_change_2018_2024", 0.0)
    ndwi = s.get("ndwi_mean", 0.0)
    water_km2 = s.get("water_area_km2", 0.0)
    slope = s.get("dem_slope_mean_deg") or "N/A"
    emb_chg = s.get("embedding_change_intensity") or "N/A"
    sources = ", ".join(s.get("data_sources", []))
    roi_name = roi.get("name", "ROI")
    by, ay = data.get("baseline_year", 2018), data.get("analysis_year", 2024)
    maxar_scenes = s.get("maxar_scenes_available", 0)
    best_scene = maxar.get("best_scene") or {}

    report = f"""## 1. Data Inventory

- **ROI**: {roi_name} ({roi.get('west', ''):.3f}°E – {roi.get('east', ''):.3f}°E, {roi.get('south', ''):.3f}°N – {roi.get('north', ''):.3f}°N)
- **Sentinel-2 SR (GEE)**: cloud-free composite {by} and {ay} growing seasons; NDVI, NDWI, EVI computed at 10 m
  - Baseline ({by}) NDVI mean: **{gee.get('baseline_ndvi', 0):.3f}**
  - Analysis ({ay}) NDVI mean: **{gee.get('analysis_ndvi', 0):.3f}** (Δ = {gee.get('ndvi_change', 0):+.3f})
  - NDWI mean: **{ndwi:.3f}** | EVI mean: **{gee.get('evi_mean', 0):.3f}**
  - Water body area: **{water_km2:.2f} km²**
- **Google Satellite Embedding V1 (GEE)**: 64-dim annual embeddings at 10 m; cosine dissimilarity = **{emb_chg}** (0=stable, 2=maximal change)
- **Maxar MGP STAC**: {maxar_scenes} scenes catalogued ({by}–{ay})
  - Best scene: {best_scene.get('sensor', 'N/A')} @ {best_scene.get('resolution_m', 0.5)} m, {best_scene.get('cloud_cover_pct', 0):.1f}% cloud, {best_scene.get('datetime', 'N/A')[:10]}
- **Local DEM**: Elevation range {dem.get('elev_min', 'N/A')}–{dem.get('elev_max', 'N/A')} m, mean slope {slope}°, flat fraction {s.get('flat_fraction', 'N/A')}
- **Data sources**: {sources}
- **Change detection**: NDVI z-score | loss fraction {chg.get('loss_fraction', 'N/A')}, gain fraction {chg.get('gain_fraction', 'N/A')}

---

## 2. 3-Year Water Resource Management Strategy

| Quarter | Action | Location | Expected Outcome | Success Metric |
|---------|--------|----------|-----------------|----------------|
| Q1 2026 | Baseline water audit + IoT soil-moisture sensors | All sub-commands across ROI | Quantify current water-use efficiency | Sensor deployment >90% of target nodes |
| Q2 2026 | Drip irrigation pilot (NDVI < 0.25 zones) | Low-vegetation patches (NDVI < 0.25) | Reduce runoff by 15% in pilot area | Water-use per ha reduced ≥15% |
| Q3 2026 | Canal lining rehabilitation (high-seepage reaches) | Flat terrain (slope < 2°) — {s.get('flat_fraction', 0.3)*100:.0f}% of ROI | Reduce conveyance loss by 10% | Canal discharge ratio improvement |
| Q4 2026 | NDWI water-body monitoring dashboard | {water_km2:.2f} km² identified water bodies | Early flood/drought early warning | Alert latency < 6 hours |
| Q1 2027 | Expand drip to full command area | All agricultural plots | 20% total water reduction | NDWI trend stabilisation |
| Q2 2027 | Remote-sensing crop-water demand mapping | Vegetation areas (NDVI > 0.3) | Precision irrigation scheduling | ±10% crop-water estimate accuracy |
| Q3 2027 | Deficit irrigation trials (EVI-guided) | High-value crop zones (EVI > 0.25) | 12% yield-per-water improvement | EVI ≥ {gee.get('evi_mean', 0.25):.3f} maintained under 80% water budget |
| Q4 2027 | Reservoir desilting + rainwater harvesting structures | Upstream watershed (slope > 5°) | +15% storage capacity | Storage volume increase confirmed |
| Q1 2028 | Drought contingency activation protocol | ROI-wide | Safeguard minimum crop water needs | <5% yield loss in drought trigger scenario |
| Q2 2028 | Urban encroachment buffer zone enforcement | Peri-urban NDVI loss zones (Δ = {ndvi_chg:+.3f}) | Halt agricultural land conversion | Zero net loss of irrigated area |
| Q3 2028 | Aquifer recharge programme | High-permeability flat zones | Groundwater level +0.5 m/year | NDWI improvement {ndwi:.3f} → 0.25 |
| Q4 2028 | Full-system review + policy recommendations | ROI + watershed | Evidence-based 5-year extension plan | Report published with measurable KPIs |

---

## 3. Python Code

```python
#!/usr/bin/env python3
\"\"\"
Multi-Sensor Geospatial Water Resource Pipeline
Replicates: GEE Sentinel-2 + Satellite Embeddings, Maxar STAC, local NDVI/EVI/MNDWI + DEM slope
\"\"\"
import argparse, json, os, sys, warnings
from pathlib import Path
import numpy as np
warnings.filterwarnings("ignore")

# ── Configuration ──────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--roi",    nargs=4, type=float, default=[73.0, 18.5, 73.5, 19.0], metavar=("W","S","E","N"))
parser.add_argument("--ms",     default="",  help="Multispectral GeoTIFF (LISS-4 or HLS)")
parser.add_argument("--dem",    default="",  help="DEM GeoTIFF")
parser.add_argument("--out",    default="workspace/output", help="Output directory")
parser.add_argument("--year-a", type=int, default=2024)
parser.add_argument("--year-b", type=int, default=2018)
args = parser.parse_args()
out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)

summary = {{"roi": dict(zip(["west","south","east","north"], args.roi)),
            "baseline_year": args.year_b, "analysis_year": args.year_a}}

# ── Local Raster Processing (replaces GDAL MCP raster_info/raster_stats) ──
def safe_ratio(num, den): return np.where(np.abs(den) > 1e-6, num/den, np.nan)

if args.ms:
    import rasterio
    with rasterio.open(args.ms) as src:
        bands = src.read().astype(np.float32) / 10_000
        n = src.count
    if n >= 3:
        g, r, nir = bands[1], bands[2], bands[3] if n >= 4 else bands[2]
        ndvi = safe_ratio(nir - r, nir + r)
        ndwi = safe_ratio(g - nir, g + nir)
        summary["local_ndvi_mean"] = round(float(np.nanmean(ndvi)), 4)
        summary["local_ndwi_mean"] = round(float(np.nanmean(ndwi)), 4)
    if n >= 6:
        b, g, r, nir, s1, s2 = [bands[i] for i in range(6)]
        evi  = np.clip(2.5*(nir-r)/(nir+6*r-7.5*b+1), -1, 1)
        mndwi = safe_ratio(g - s1, g + s1)
        summary["local_evi_mean"]   = round(float(np.nanmean(evi)), 4)
        summary["local_mndwi_mean"] = round(float(np.nanmean(mndwi)), 4)

if args.dem:
    import rasterio
    with rasterio.open(args.dem) as src:
        elev = src.read(1).astype(np.float32)
        rx, ry = abs(src.transform.a), abs(src.transform.e)
        if src.crs and src.crs.is_geographic:
            rx *= 111_320; ry *= 111_320
    dy, dx = np.gradient(np.nan_to_num(elev), ry, rx)
    slope_deg = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
    summary.update(elev_min=round(float(np.nanmin(elev)),2),
                   elev_max=round(float(np.nanmax(elev)),2),
                   slope_mean_deg=round(float(np.nanmean(slope_deg)),3),
                   flat_fraction=round(float(np.nanmean(slope_deg < 2.0)),4))

# ── Google Earth Engine (Sentinel-2 + Satellite Embeddings) ────────
def fetch_gee(roi_bbox, year_b, year_a, project=None):
    import ee
    try:
        ee.Initialize(project=project)
    except Exception:
        ee.Authenticate(); ee.Initialize(project=project)
    roi = ee.Geometry.Rectangle(roi_bbox)
    def s2_composite(year):
        return (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                .filterBounds(roi).filterDate(f"{{year}}-05-01", f"{{year}}-10-31")
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
                .select(["B2","B3","B4","B8","B11","B12"]).median().divide(10_000))
    def indices(img):
        ndvi = img.normalizedDifference(["B8","B4"]).rename("NDVI")
        ndwi = img.normalizedDifference(["B3","B8"]).rename("NDWI")
        evi  = img.expression("2.5*(NIR-RED)/(NIR+6*RED-7.5*BLUE+1)",
                              {{"NIR":img.select("B8"),"RED":img.select("B4"),"BLUE":img.select("B2")}}).rename("EVI")
        return ee.Image.cat([ndvi, ndwi, evi])
    def mean_stat(img, band):
        return float(img.select(band).reduceRegion(ee.Reducer.mean(), roi, 10, maxPixels=1e9).get(band).getInfo() or 0)
    base = indices(s2_composite(year_b)); anal = indices(s2_composite(year_a))
    # Satellite Embedding cosine change
    emb_col = ee.ImageCollection("GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL")
    def emb_vec(yr):
        img = emb_col.filter(ee.Filter.calendarRange(yr,yr,"year")).first()
        bands = img.bandNames().getInfo()
        v = img.reduceRegion(ee.Reducer.mean(), roi, 10, maxPixels=1e9)
        return np.array([v.get(b).getInfo() for b in bands], dtype=np.float32)
    base_v, anal_v = emb_vec(year_b), emb_vec(year_a)
    cos = np.dot(base_v, anal_v) / (np.linalg.norm(base_v)*np.linalg.norm(anal_v)+1e-8)
    water_mask = indices(s2_composite(year_a)).select("NDWI").gt(0)
    water_area = water_mask.multiply(ee.Image.pixelArea()).reduceRegion(ee.Reducer.sum(), roi, 10, maxPixels=1e9).get("NDWI")
    return {{
        "gee_ndvi_baseline": round(mean_stat(base,"NDVI"),4),
        "gee_ndvi_analysis": round(mean_stat(anal,"NDVI"),4),
        "gee_ndwi": round(mean_stat(anal,"NDWI"),4),
        "gee_evi": round(mean_stat(anal,"EVI"),4),
        "gee_embedding_cosine_change": round(1.0-float(cos),4),
        "water_area_km2": round(float(water_area.getInfo() or 0)/1e6, 3),
    }}

try:
    gee_data = fetch_gee(args.roi, args.year_b, args.year_a, os.getenv("GEE_PROJECT"))
    summary.update(gee_data)
except Exception as e:
    print(f"GEE skipped: {{e}}", file=sys.stderr)

# ── Maxar STAC Discovery ────────────────────────────────────────────
def search_maxar(roi_bbox, year_b, year_a, api_key):
    import requests
    payload = {{
        "bbox": roi_bbox,
        "datetime": f"{{year_b}}-01-01T00:00:00Z/{{year_a}}-12-31T23:59:59Z",
        "collections": ["wv04-natgeo","wv03-natgeo","wv02-natgeo"],
        "limit": 5,
        "filter": {{"op":"and","args":[
            {{"op":"<=","args":[{{"property":"eo:cloud_cover"}},20]}},
            {{"op":"<=","args":[{{"property":"view:off_nadir"}},30]}}]}},
        "filter-lang": "cql2-json",
        "sortby": [{{"field":"datetime","direction":"desc"}}],
    }}
    r = requests.post("https://api.maxar.com/discovery/v1/stac/search",
                      json=payload, headers={{"Authorization":f"Bearer {{api_key}}"}}, timeout=30)
    r.raise_for_status()
    features = r.json().get("features",[])
    return {{"maxar_scenes": len(features),
             "best_cloud_cover": min((f["properties"].get("eo:cloud_cover",100) for f in features), default=None)}}

try:
    mx_key = os.getenv("MAXAR_API_KEY","")
    if mx_key:
        summary.update(search_maxar(args.roi, args.year_b, args.year_a, mx_key))
except Exception as e:
    print(f"Maxar skipped: {{e}}", file=sys.stderr)

# ── Output ─────────────────────────────────────────────────────────
out_path = out_dir / "feature_summary.json"
out_path.write_text(json.dumps(summary, indent=2))
print(f"Feature summary written to {{out_path}}")
print(json.dumps(summary, indent=2))
```

---

## 4. R Code

```r
# Water Resource Scenario Analysis
# Loads feature_summary.json, runs NDVI trend regression,
# change-point detection, and produces irrigation demand plots.

library(jsonlite)
library(ggplot2)
library(changepoint)   # install.packages("changepoint")
library(dplyr)

# ── Load data ──────────────────────────────────────────────────────
feat <- fromJSON("workspace/output/feature_summary.json")
ndvi_a <- feat$gee_ndvi_analysis %||% feat$ndvi_primary
ndvi_b <- feat$gee_ndvi_baseline %||% ndvi_a
ndvi_chg <- ndvi_a - ndvi_b
water_km2 <- feat$water_area_km2 %||% 0
baseline_y <- feat$baseline_year %||% 2018
analysis_y <- feat$analysis_year %||% 2024

cat("NDVI:", ndvi_b, "→", ndvi_a, " Δ =", ndvi_chg, "\\n")
cat("Water area:", water_km2, "km²\\n")

# ── Synthetic NDVI time series (replace with real if available) ────
years <- seq(baseline_y, analysis_y)
set.seed(42)
ndvi_ts <- ndvi_b + cumsum(rnorm(length(years), mean=ndvi_chg/length(years), sd=0.01))

# ── Change-point detection ─────────────────────────────────────────
cp_result <- cpt.mean(ndvi_ts, method="PELT", penalty="BIC")
cp_years  <- years[cpts(cp_result)]
cat("Change points detected at:", cp_years, "\\n")

# ── Linear regression NDVI ~ Year ─────────────────────────────────
df_ts <- data.frame(year=years, ndvi=ndvi_ts)
model <- lm(ndvi ~ year, data=df_ts)
cat("NDVI trend: ", coef(model)[["year"]], "per year\\n")

# ── Irrigation demand scenarios ────────────────────────────────────
# Water demand proxy: inverse of NDVI (stressed vegetation needs more water)
base_demand <- (1 - ndvi_a) * 1200  # mm/year (field capacity proxy)
scenarios <- data.frame(
  scenario = c("Drought (-20% rain)", "Normal", "Wet (+20% rain)"),
  demand_mm = c(base_demand * 1.35, base_demand, base_demand * 0.72),
  supply_mm = c(base_demand * 0.60, base_demand * 0.85, base_demand * 1.05)
)
scenarios$deficit_mm <- scenarios$demand_mm - scenarios$supply_mm

# ── Plot ───────────────────────────────────────────────────────────
p1 <- ggplot(df_ts, aes(year, ndvi)) +
  geom_line(colour="#2c7bb6", size=1.2) +
  geom_smooth(method="lm", se=TRUE, colour="#d7191c", linetype="dashed") +
  geom_vline(xintercept=cp_years, colour="#fdae61", linetype="dotted", size=1) +
  labs(title="NDVI Trend with Change Points",
       x="Year", y="NDVI Mean",
       caption=paste0("ROI: ", feat$roi$name %||% "Area")) +
  theme_minimal()

p2 <- ggplot(scenarios, aes(scenario, deficit_mm, fill=scenario)) +
  geom_col(show.legend=FALSE) +
  geom_hline(yintercept=0, linetype="dashed") +
  scale_fill_manual(values=c("#d73027","#4575b4","#1a9850")) +
  labs(title="Irrigation Demand vs Supply Gap by Climate Scenario",
       x=NULL, y="Deficit (mm/year)") +
  theme_minimal()

pdf("workspace/output/scenario_analysis.pdf", width=12, height=8)
gridExtra::grid.arrange(p1, p2, ncol=2)
dev.off()
cat("PDF written to workspace/output/scenario_analysis.pdf\\n")
```

---

## 5. Risk Assessment

| Risk | Likelihood | Impact | Trigger Metric | Mitigation |
|------|-----------|--------|---------------|-----------|
| Vegetation degradation continuation | **H** | **H** | NDVI Δ = {ndvi_chg:+.3f} (trend negative) | Deficit irrigation + EVI monitoring; trigger intervention if NDVI < {ndvi:.3f} - 0.05 |
| Prolonged drought | **H** | **H** | NDWI < -0.1 (current: {ndwi:.3f}) | Rainwater harvesting structures; groundwater recharge |
| Water body shrinkage | **M** | **H** | Water area < 1.0 km² (current: {water_km2:.2f} km²) | NDWI sentinel alerts; seasonal canal recharge |
| Urban encroachment on farmland | **M** | **M** | Embedding change > 0.15 (current: {emb_chg}) | Land-use zoning; GIS boundary enforcement |
| High-slope erosion and runoff | **M** | **M** | Slope > 5° zones | Contour bunding; vegetative barriers; drip irrigation on steep areas |
| Satellite data gaps (cloud cover) | **L** | **M** | Cloud cover >20% for >30 days | Maxar high-res fallback ({maxar_scenes} scenes available); SAR alternative |
| Irrigation infrastructure failure | **L** | **H** | EVI drop >0.05 in 2 weeks | Quarterly pump inspections; sensor-triggered maintenance alerts |
| API/data pipeline downtime | **L** | **M** | Feature JSON not updated >7 days | Local GDAL fallback; cached baseline rasters |
"""
    return report

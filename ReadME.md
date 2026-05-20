# GeoAI Water Resource Intelligence Pipeline

**Multi-sensor satellite analysis for water resource planning — powered by Google Earth Engine, Maxar MGP, IBM NASA Prithvi-EO-2.0, and Claude Opus.**

> Project Code: `AUTOCLAW-WS-001` | Branch: `claude/satellite-geospatial-integration-sbpit`

---

## What This Is

A complete geospatial intelligence pipeline that:

1. **Ingests** satellite imagery from Google Earth Engine (Sentinel-2 + Satellite Embeddings V1), Maxar Geospatial Platform (0.5 m VHR), and local GeoTIFFs (LISS-4, HLS, DEM)
2. **Processes** spectral indices (NDVI, EVI, MNDWI, NDWI, SAVI, NBR), DEM slope analysis, and temporal change detection
3. **Fuses** all sources into a structured feature JSON
4. **Analyses** with Claude Opus to generate a 5-section water resource management report
5. **Visualises** everything inside QGIS via a native dock panel plugin

The pipeline runs end-to-end with **zero API keys** in demo mode using synthetic data.

---

## Repository Structure

```
GeoAI-QuantumCartographers/
├── run_pipeline.py                    # Main CLI orchestrator
├── requirements.txt                   # Python dependencies
├── .env.example                       # API key template
│
├── satellite_pipeline/                # Core pipeline package
│   ├── config.py                      # Configuration + ROI definition
│   ├── ingest/
│   │   ├── gee_client.py              # Google Earth Engine (S2 + Embeddings V1)
│   │   ├── maxar_client.py            # Maxar MGP STAC discovery
│   │   └── local_raster.py            # rasterio GeoTIFF inspection + band-math
│   ├── process/
│   │   ├── spectral_indices.py        # NDVI, EVI, MNDWI, NDWI, SAVI, NBR
│   │   └── change_detection.py        # z-score diff + cosine embedding change
│   ├── fusion/
│   │   └── feature_aggregator.py      # Merge all sources → feature_summary.json
│   ├── intelligence/
│   │   └── claude_analyst.py          # Claude Opus report generation
│   ├── output/
│   │   └── report_writer.py           # Write .md / .py / .R / .csv artifacts
│   └── demo/
│       └── generate_sample_data.py    # Synthetic GeoTIFF generator
│
├── qgis_geoai_plugin/                 # QGIS3 plugin
│   ├── metadata.txt
│   ├── plugin.py                      # Plugin lifecycle + toolbar
│   ├── install_plugin.py              # Cross-platform installer
│   ├── ui/dock_panel.py               # 5-tab dock panel (full Qt UI)
│   ├── core/
│   │   ├── symbology.py               # 8 spectral colormaps
│   │   ├── layer_manager.py           # QGIS layer operations
│   │   ├── index_engine.py            # Spectral index computation
│   │   ├── change_engine.py           # Temporal change maps
│   │   └── monitor_engine.py          # QTimer threshold monitoring + alerts
│   ├── providers/
│   │   ├── maxar_provider.py          # Maxar WMS/XYZ/STAC in QGIS
│   │   └── gee_provider.py            # GEE → QGIS layer bridge
│   └── workers/
│       └── pipeline_worker.py         # QThread background pipeline runner
│
└── QC-Lit/
    └── main.py                        # Streamlit web UI
```

---

## Quick Start — No API Keys Needed

```bash
# Clone
git clone https://github.com/AmeySambarkar/GeoAI-QuantumCartographers.git
cd GeoAI-QuantumCartographers

# Install dependencies
pip install numpy rasterio scipy requests python-dotenv anthropic

# Run in demo mode (synthetic data, template report)
python run_pipeline.py --demo --no-gee --no-maxar --no-claude
```

Outputs land in `workspace/output/`:

| File | Contents |
|------|---------|
| `water_plan.md` | 5-section water resource intelligence report |
| `feature_summary.json` | All aggregated metrics (machine-readable) |
| `pipeline_code.py` | Self-contained Python script to replicate the run |
| `scenario_analysis.R` | R script — NDVI trend regression + irrigation demand plot |
| `risk_assessment.csv` | Risk table with trigger metrics and mitigations |

---

## Installation Guide — macOS

### Prerequisites

| Tool | Minimum version | Install command |
|------|----------------|----------------|
| Python | 3.10 | `brew install python` |
| QGIS | 3.22 LTR | [qgis.org → Download](https://qgis.org) |
| Git | any | `brew install git` |
| Homebrew | any | See [brew.sh](https://brew.sh) |

### Step 1 — Clone and create a virtual environment

```bash
git clone https://github.com/AmeySambarkar/GeoAI-QuantumCartographers.git
cd GeoAI-QuantumCartographers

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

### Step 2 — Install dependencies

```bash
# Core (required for pipeline to run)
pip install numpy rasterio scipy requests python-dotenv anthropic

# Google Earth Engine support (optional but recommended)
pip install earthengine-api geemap

# Vector data support (optional)
pip install geopandas
```

### Step 3 — Configure API keys

```bash
cp .env.example .env
open -e .env        # opens in TextEdit; use any editor
```

```ini
# .env — fill in the keys you have; leave the rest blank
ANTHROPIC_API_KEY=sk-ant-...
GEE_PROJECT=your-gee-project-id
MAXAR_API_KEY=your-maxar-bearer-token
```

### Step 4 — Authenticate Google Earth Engine (one-time)

```bash
earthengine authenticate          # opens browser → sign in with Google account
earthengine set_project your-gee-project-id
```

### Step 5 — Run the pipeline

```bash
# Demo mode — synthetic data, no credentials needed
python run_pipeline.py --demo

# Your own GeoTIFFs + Claude report
python run_pipeline.py \
  --ms /path/to/LISS4.tif \
  --dem /path/to/dem.tif \
  --roi 73.0 18.5 73.5 19.0 \
  --baseline-year 2018 \
  --analysis-year 2024

# Demo + Claude (needs ANTHROPIC_API_KEY in .env)
python run_pipeline.py --demo
```

### Step 6 — Streamlit web UI (optional)

```bash
pip install streamlit
streamlit run QC-Lit/main.py
# Opens http://localhost:8501
```

### Step 7 — Install the QGIS plugin

```bash
python qgis_geoai_plugin/install_plugin.py
# → Installs to ~/Library/Application Support/QGIS/QGIS3/.../python/plugins/

# Verify
python qgis_geoai_plugin/install_plugin.py --check
```

Also install `rasterio` and `anthropic` into **QGIS's own Python** so the plugin can import them:

```bash
# Find the QGIS Python binary
/Applications/QGIS.app/Contents/MacOS/bin/python3 -m pip install rasterio anthropic requests
```

Then in QGIS: **Plugins → Manage and Install Plugins → Installed → tick GeoAI Water Resource Intelligence → OK**

The `🛰️` toolbar appears. Click it to open the dock panel.

---

## Installation Guide — Windows

### Prerequisites

| Tool | Minimum version | Where to get it |
|------|----------------|----------------|
| Python | 3.10 | [python.org/downloads](https://www.python.org/downloads/) — tick **Add Python to PATH** |
| QGIS | 3.22 LTR | [qgis.org](https://qgis.org) — use the **OSGeo4W Network Installer** |
| Git | any | [git-scm.com/download/win](https://git-scm.com/download/win) |

> QGIS on Windows ships its own isolated Python environment (OSGeo4W). The pipeline CLI uses your system Python. Both need `rasterio` installed — see Step 8 below.

### Step 1 — Clone the repository

Open **PowerShell** or **Git Bash**:

```powershell
git clone https://github.com/AmeySambarkar/GeoAI-QuantumCartographers.git
cd GeoAI-QuantumCartographers
```

### Step 2 — Create a virtual environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If you see an execution-policy error:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.venv\Scripts\Activate.ps1
```

### Step 3 — Install dependencies

```powershell
pip install --upgrade pip

# rasterio on Windows requires a pre-compiled wheel
pip install rasterio --find-links https://github.com/cgohlke/rasterio-build/releases/latest/download

# Core pipeline
pip install numpy scipy requests python-dotenv anthropic

# GEE support (optional)
pip install earthengine-api geemap
```

> **Alternative for rasterio:** Download the `.whl` file for your Python version from [Christoph Gohlke's wheels](https://www.lfd.uci.edu/~gohlke/pythonlibs/#rasterio) and install with `pip install <file>.whl`.

### Step 4 — Configure API keys

```powershell
Copy-Item .env.example .env
notepad .env
```

```ini
ANTHROPIC_API_KEY=sk-ant-...
GEE_PROJECT=your-gee-project-id
MAXAR_API_KEY=your-maxar-bearer-token
```

### Step 5 — Authenticate Google Earth Engine

```powershell
earthengine authenticate
earthengine set_project your-gee-project-id
```

### Step 6 — Run the pipeline

```powershell
# Demo mode
python run_pipeline.py --demo

# Custom ROI + real files (use backtick ` for line continuation in PowerShell)
python run_pipeline.py `
  --ms C:\data\LISS4.tif `
  --dem C:\data\dem.tif `
  --roi 73.0 18.5 73.5 19.0
```

### Step 7 — Streamlit UI

```powershell
pip install streamlit
streamlit run QC-Lit\main.py
```

### Step 8 — Install the QGIS plugin

```powershell
# Auto-detects %APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\
python qgis_geoai_plugin\install_plugin.py
```

Install `rasterio` and `anthropic` into **QGIS's own Python** (required for the plugin):

```bat
REM Open "OSGeo4W Shell" from the Windows Start menu, then:
py3_env
pip install rasterio anthropic requests numpy scipy
```

If using the standalone QGIS installer (not OSGeo4W):

```powershell
# Adjust path to match your QGIS version
& "C:\Program Files\QGIS 3.34\bin\python3.exe" -m pip install rasterio anthropic requests
```

Then in QGIS: **Plugins → Manage and Install Plugins → Installed → tick GeoAI Water Resource Intelligence → OK**

---

## Pipeline CLI Reference

```
python run_pipeline.py [OPTIONS]

  --demo                  Generate synthetic GeoTIFFs and run end-to-end
  --ms PATH               Multispectral GeoTIFF (3-band LISS-4 or 6-band HLS)
  --dem PATH              DEM GeoTIFF (single band, float32, metres)
  --roi W S E N           Bounding box WGS-84 (default: 73.0 18.5 73.5 19.0)
  --baseline-year INT     Baseline year for change detection (default: 2018)
  --analysis-year INT     Analysis year (default: 2024)
  --out DIR               Output directory (default: workspace/output)
  --no-gee                Skip GEE — use physics-informed simulation
  --no-maxar              Skip Maxar STAC — use simulated scene catalog
  --no-claude             Skip Claude API — use template report
```

---

## QGIS Plugin — Feature Guide

### Layers tab

Load local GeoTIFFs, generate synthetic demo data, add Maxar Vivid/Precision as a WMS streaming basemap or XYZ tile layer, search the Maxar STAC catalog (scene footprints appear as a styled polygon layer), and pull GEE Sentinel-2 composites or Satellite Embedding V1 PCA false-colour directly into the map canvas.

### Indices tab

Auto-detects sensor type from band count (3-band → LISS-4, 6-band → HLS). Compute any combination of NDVI, EVI, MNDWI, NDWI, SAVI, NBR — each added as a styled layer with a science-tuned colormap and a statistics table (mean, std, min, max, p25, p75).

| Index | Colormap | Diagnostic use |
|-------|---------|---------------|
| NDVI | Brown → yellow → dark green | Vegetation vigour, crop health monitoring |
| NDWI | Sand → white → deep blue | Open water bodies, reservoir levels |
| EVI | Grey → lime → forest green | Dense canopy; less soil/atmosphere noise than NDVI |
| MNDWI | Tan → ice blue → navy | Urban water features, canal mapping |
| SAVI | Sand → pale green → green | Sparse vegetation on bare soil (arid zones) |
| NBR | Red → grey → dark green | Burn severity mapping |

### Change tab

Select a baseline and analysis layer. Outputs added to the project:

- **NDVI z-score map** — red (significant loss) ↔ white (stable) ↔ green (gain); 95% CI threshold at ±1.96
- **4-class water change** — encodes new water, lost water, persistent water, dry land
- **Embedding cosine dissimilarity** — when 64-band Google Satellite Embedding V1 input is provided; blue = stable, red = maximum landscape change

### Monitor tab

A `QTimer`-based engine checks configured thresholds on any loaded raster layer at a user-defined interval (default 5 minutes) without blocking the QGIS UI.

**Default rules:**

| Rule | Index | Threshold | Severity |
|------|-------|-----------|---------|
| NDVI drought stress | NDVI | < 0.20 | Critical |
| NDWI water body loss | NDWI | < 0.05 | Warning |
| EVI vegetation health | EVI | < 0.15 | Warning |
| MNDWI water gain | MNDWI | > 0.40 | Info |

Alerts fire in the QGIS message bar and are logged to `workspace/output/monitor_log.jsonl` as newline-delimited JSON for downstream analysis.

### Report tab

Runs the full pipeline in a background `QThread` — QGIS stays responsive. With `ANTHROPIC_API_KEY` set, Claude Opus generates the complete 5-section report. Export as `.md` or `.json`, or click "Load Results into QGIS" to pull computed rasters back onto the map canvas.

---

## Troubleshooting

### Pipeline

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError: rasterio` | `pip install rasterio` (Windows: use pre-built wheel — see Step 3) |
| `ModuleNotFoundError: anthropic` | `pip install anthropic` |
| GEE `EEException: not signed in` | Run `earthengine authenticate` |
| GEE `project not set` | `earthengine set_project your-project-id` |
| NDVI values outside [−1, 1] | Check band order — LISS-4 expects [Green, Red, NIR]; HLS expects [Blue, Green, Red, NIR, SWIR1, SWIR2] |
| `workspace/output` missing | Created automatically — check write permissions on the working directory |
| Slow first run | GEE first call initialises credentials; subsequent calls are faster |

### QGIS Plugin

| Symptom | Fix |
|---------|-----|
| Plugin not in Installed list after install | Re-run `install_plugin.py`; check the destination path with `--check` |
| Plugin ticked but toolbar missing | Restart QGIS |
| `ImportError: rasterio` when opening panel | Install into QGIS Python (see Step 7/8 above) |
| Maxar WMS layer shows blank tiles | API key invalid or expired; re-paste from developers.maxar.com |
| Layer combos empty after loading files | Click the `↻` refresh button on the Indices tab |
| Monitor "Check Now" shows no results | Ensure layer name in the rule matches the layer's exact display name in QGIS |
| GEE pixel pull times out | ROI is too large for direct download; reduce to ≤ 0.5° × 0.5°, or use GEE Export to Drive |

---

## Future Scope for Development

### Near-term (3–6 months)

**1. Real-time Maxar Monitoring Events**
Connect to the [MGP Monitoring Events API](https://github.com/Maxar-Public/mgp-monitoring-events) to subscribe to Maxar's own change detection alerts over a registered AOI. When Maxar identifies a change event, automatically trigger the pipeline and push results to the QGIS monitor tab — closing the full cybernetic sense/act loop without polling.

**2. Prithvi-EO-2.0 deep inference**
Replace the current band-math approximation with actual inference from [ibm-nasa-geospatial/Prithvi-EO-2.0](https://huggingface.co/ibm-nasa-geospatial) — a temporal Vision Transformer trained on 6-band HLS data. Enables multi-temporal masked reconstruction, flood mapping, and crop type classification from the same model checkpoint via `transformers.AutoModel.from_pretrained()`.

**3. Sentinel-1 SAR ingestion**
Add `sar_client.py` to ingest Sentinel-1 GRD VV/VH backscatter from GEE. SAR is cloud-penetrating — combining NDWI (optical) with SAR backscatter gives all-weather water mapping, critical during monsoon season when Sentinel-2 is routinely obscured.

**4. STAC-native data browser**
Replace ad-hoc file paths with a `pystac-client` browser covering Microsoft Planetary Computer, Earth Search (AWS), and Maxar catalogs from a unified panel. STAC Items directly feed into the pipeline — no manual path entry.

**5. QML style export library**
Export computed layer colormaps as `.qml` files so styles can be re-applied to new layers without re-running the plugin. A Style Library tab would let users save, name, and share custom colormaps.

---

### Medium-term (6–12 months)

**6. ArcGIS Pro Add-in**
Port the dock panel to ArcGIS Pro using the ArcGIS API for Python and ArcPy. The core `satellite_pipeline` package is framework-agnostic — only the UI and layer management modules need reimplementing. Maxar provides [official ArcGIS Pro integration docs](https://developers.maxar.com/docs/integrations/arcgispro) as a starting point.

**7. Claude tool-use anomaly explanation**
When the monitor engine fires a threshold alert, automatically construct a Claude API call with `tool_use` — tools that fetch GEE pixel history and Maxar recent imagery for the triggering location. Claude returns a natural-language explanation ("water body has contracted by 23% relative to the 5-year seasonal norm — elevated likelihood of failed monsoon inflow") surfaced as a rich QGIS notification with supporting evidence.

**8. QGIS Temporal Controller integration**
For each year in a GEE ImageCollection, compute NDVI/NDWI and register as a time-stamped raster layer with `QgsRasterLayer.temporalProperties()`. QGIS's built-in Temporal Controller then animates the change sequence directly on the map canvas — 20 years of vegetation dynamics in a 10-second scrubable animation.

**9. Multi-ROI portfolio monitoring**
Accept a GeoJSON or CSV of named AOIs (farm parcels, dam catchments, wetland zones). The pipeline processes all AOIs in parallel via `QgsTaskManager` and produces a portfolio-level risk dashboard: a summary table in the dock panel sortable by NDVI decline, water area, change intensity, and Maxar scene availability.

**10. Confidence-weighted sensor fusion**
Implement a Kalman-filter-style update step that fuses local raster NDVI and GEE NDVI, weighted by quality flags (cloud cover fraction, Maxar off-nadir angle, acquisition date recency). The fused index comes with explicit uncertainty bounds — more scientifically rigorous than simple mean averaging, and enables probabilistic risk assessment.

---

### Long-term (12–24 months)

**11. Regional Prithvi fine-tuning**
Fine-tune Prithvi-EO-2.0 on labelled HLS data from the Maharashtra agricultural zone using the HuggingFace `Trainer` API with a LoRA adapter. Domain-specific weights would substantially improve crop-water stress classification and kharif/rabi crop type mapping compared to the global pretrained checkpoint.

**12. Edge inference on drone hardware**
Export quantised spectral index models (ONNX / TensorRT) for deployment on drone-mounted NVIDIA Jetson Orin modules. Real-time NDVI computation at sub-centimetre scale in the field, fused via 4G with Maxar high-resolution basemap context — enabling precision irrigation actuation at the individual plant row level.

**13. Physics-based hydrological digital twin**
Pipe remote-sensing outputs (NDVI-derived LAI, DEM slope, NDWI water extents) as boundary conditions into a physics-based hydrological model such as [SWAT+](https://swatplus.gitbook.io/). Claude generates scenario narratives for water planners from model outputs: projected reservoir levels under drought, optimal release schedules, and flood risk windows — grounded in both satellite evidence and hydrological physics.

**14. Federated learning across farm cooperatives**
Design a privacy-preserving federated learning architecture where multiple farm cooperatives contribute gradient updates from locally-labelled imagery without sharing raw pixel data. The global Prithvi adapter improves with each cooperative's contribution while keeping commercially sensitive ground truth on-premises — a critical requirement for agricultural data sovereignty.

**15. OGC API Features via QGIS Server**
Deploy the pipeline as a [QGIS Server](https://docs.qgis.org/latest/en/docs/server_manual/) instance exposing OGC API Features and WPS process endpoints. Any standards-compliant GIS client — ArcGIS, MapInfo, browser-based — can then trigger pipeline runs and consume styled analysis layers without installing the desktop plugin, scaling the reach of the system across an organisation.

**16. Conversational GIS via Claude tool-use in the dock panel**
Add a natural language input field to the Report tab. User types: *"Show me where NDVI has declined the most since 2020 and flag any overlap with water body loss."* The input is sent to Claude with tool definitions for every plugin action. Claude calls `run_change_detection()`, `run_indices()`, and `zoom_to_layer()` in sequence and returns a plain-English summary with map canvas focused on the highest-risk area. Full conversational GIS — no menu navigation required.

---

## Architecture Reference

```
                              SENSE
┌─────────────────────────────────────────────────────────────┐
│  Google Earth Engine        Maxar MGP           Local       │
│  Sentinel-2 S2_SR           STAC Discovery      GeoTIFF     │
│  Satellite Embedding V1     WMS 0.5 m VHR       LISS-4      │
│  (64-dim, 10 m annual)      Monitoring Events   HLS / DEM   │
└──────────────┬──────────────────────┬───────────────┬───────┘
               │                      │               │
                              PROCESS
┌─────────────────────────────────────────────────────────────┐
│  Spectral Indices         Change Detection    DEM Analysis  │
│  NDVI EVI MNDWI NDWI      z-score temporal   Slope Aspect  │
│  SAVI NBR                 cosine embedding   Elev stats     │
│                           Prithvi anomaly                   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                              MODEL
                  ┌────────────────────────┐
                  │   Feature Aggregator   │
                  │   feature_summary.json │
                  └────────────┬───────────┘
                               │
                              PLAN
                  ┌────────────────────────┐
                  │   Claude Opus          │
                  │   5-section water      │
                  │   resource report      │
                  └────────────┬───────────┘
                               │
                    ACT + FEEDBACK LOOP
┌─────────────────────────────────────────────────────────────┐
│  QGIS Plugin (dock panel)        Streamlit Web UI           │
│  Styled spectral layers          Interactive dashboard      │
│  QTimer monitoring + alerts      File export                │
│  QThread background pipeline     API key configuration      │
│  Temporal Controller animation   Portfolio monitoring       │
└─────────────────────────────────────────────────────────────┘
```

---

## Licence

MIT — see `LICENSE` file.

## Contributors

- System Architect — pipeline design and implementation
- Reference dossier: AUTOCLAW-WS-001, 15 May 2026
- Tools: Google Earth Engine, Maxar Geospatial Platform, IBM NASA Geospatial, Anthropic Claude

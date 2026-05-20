"""
GeoAI Water Resource Intelligence — Streamlit UI
Wraps the multi-sensor pipeline with an interactive front-end.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import streamlit as st

# Add repo root to path so we can import the pipeline
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

st.set_page_config(
    page_title="GeoAI Water Resource Intelligence",
    page_icon="🛰️",
    layout="wide",
)

st.title("🛰️ Multi-Sensor Geospatial Water Resource Intelligence")
st.caption("Pipeline: GEE Satellite Embeddings V1 · Maxar MGP · IBM NASA Prithvi · Claude Opus")

# ── Sidebar ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Configuration")
    roi_west  = st.number_input("ROI West",  value=73.0, format="%.4f")
    roi_south = st.number_input("ROI South", value=18.5, format="%.4f")
    roi_east  = st.number_input("ROI East",  value=73.5, format="%.4f")
    roi_north = st.number_input("ROI North", value=19.0, format="%.4f")
    baseline_year = st.number_input("Baseline Year", value=2018, min_value=2000, max_value=2030)
    analysis_year = st.number_input("Analysis Year",  value=2024, min_value=2000, max_value=2030)

    st.divider()
    st.subheader("API Keys")
    anthropic_key = st.text_input("Anthropic API Key", type="password",
                                   value=os.getenv("ANTHROPIC_API_KEY", ""),
                                   help="Enables full Claude report generation")
    gee_project   = st.text_input("GEE Project ID",
                                   value=os.getenv("GEE_PROJECT", ""),
                                   help="Google Earth Engine project")
    maxar_key     = st.text_input("Maxar API Key", type="password",
                                   value=os.getenv("MAXAR_API_KEY", ""),
                                   help="Maxar Geospatial Platform key")

    st.divider()
    st.subheader("Local Files (optional)")
    ms_file  = st.file_uploader("Multispectral GeoTIFF (LISS-4 or HLS 6-band)", type=["tif","tiff"])
    dem_file = st.file_uploader("DEM GeoTIFF", type=["tif","tiff"])

    demo_mode = st.checkbox("Use synthetic demo data", value=True,
                             help="Generate realistic synthetic GeoTIFFs — no real files needed")

# ── Main panel ────────────────────────────────────────────────────────
tab_run, tab_results, tab_code, tab_json = st.tabs(["Run Pipeline", "Results", "Code", "Feature JSON"])

with tab_run:
    st.markdown("""
    ### How it works
    1. **Ingest** — GEE Sentinel-2 cloud-free composites + Google Satellite Embedding V1 (64-dim, 10m)
    2. **Discover** — Maxar MGP STAC catalog for high-res (0.5m) scene availability
    3. **Process** — NDVI, EVI, MNDWI, DEM slope, temporal change detection
    4. **Fuse** — all metrics aggregated into `feature_summary.json`
    5. **Analyse** — Claude generates 5-section water resource intelligence report
    """)

    if st.button("▶ Run Pipeline", type="primary", use_container_width=True):
        with st.spinner("Running multi-sensor pipeline…"):
            # Write uploaded files to temp dir
            tmpdir = Path(tempfile.mkdtemp())
            env = os.environ.copy()
            if anthropic_key:
                env["ANTHROPIC_API_KEY"] = anthropic_key
            if gee_project:
                env["GEE_PROJECT"] = gee_project
            if maxar_key:
                env["MAXAR_API_KEY"] = maxar_key

            ms_path = ""
            dem_path = ""

            if ms_file and not demo_mode:
                ms_tmp = tmpdir / ms_file.name
                ms_tmp.write_bytes(ms_file.read())
                ms_path = str(ms_tmp)

            if dem_file and not demo_mode:
                dem_tmp = tmpdir / dem_file.name
                dem_tmp.write_bytes(dem_file.read())
                dem_path = str(dem_tmp)

            out_dir = ROOT / "workspace" / "output"
            cmd = [
                sys.executable, str(ROOT / "run_pipeline.py"),
                "--roi", str(roi_west), str(roi_south), str(roi_east), str(roi_north),
                "--baseline-year", str(int(baseline_year)),
                "--analysis-year", str(int(analysis_year)),
                "--out", str(out_dir),
            ]
            if demo_mode:
                cmd.append("--demo")
            if ms_path:
                cmd += ["--ms", ms_path]
            if dem_path:
                cmd += ["--dem", dem_path]
            if not anthropic_key:
                cmd.append("--no-claude")
            if not gee_project:
                cmd.append("--no-gee")
            if not maxar_key:
                cmd.append("--no-maxar")

            start = time.time()
            result = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(ROOT))
            elapsed = time.time() - start

        if result.returncode == 0:
            st.success(f"Pipeline completed in {elapsed:.1f}s")
            st.session_state["pipeline_ran"] = True
            st.session_state["out_dir"] = str(out_dir)
            st.session_state["logs"] = result.stderr
        else:
            st.error("Pipeline failed")
            st.code(result.stderr, language="text")

        with st.expander("Pipeline logs"):
            st.code(result.stderr or result.stdout, language="text")

with tab_results:
    out_dir_path = Path(st.session_state.get("out_dir", ROOT / "workspace" / "output"))
    plan_file = out_dir_path / "water_plan.md"
    if plan_file.exists():
        st.markdown(plan_file.read_text())
        col1, col2 = st.columns(2)
        with col1:
            st.download_button("Download water_plan.md", plan_file.read_text(),
                               file_name="water_plan.md", mime="text/markdown")
        risk_file = out_dir_path / "risk_assessment.csv"
        with col2:
            if risk_file.exists():
                st.download_button("Download risk_assessment.csv", risk_file.read_bytes(),
                                   file_name="risk_assessment.csv", mime="text/csv")
    else:
        st.info("Run the pipeline first.")

with tab_code:
    out_dir_path = Path(st.session_state.get("out_dir", ROOT / "workspace" / "output"))
    py_file = out_dir_path / "pipeline_code.py"
    r_file  = out_dir_path / "scenario_analysis.R"
    if py_file.exists():
        st.subheader("Python Pipeline Code")
        st.code(py_file.read_text(), language="python")
        st.download_button("Download pipeline_code.py", py_file.read_text(), file_name="pipeline_code.py")
    if r_file.exists():
        st.subheader("R Scenario Analysis")
        st.code(r_file.read_text(), language="r")
        st.download_button("Download scenario_analysis.R", r_file.read_text(), file_name="scenario_analysis.R")
    if not py_file.exists():
        st.info("Run the pipeline first.")

with tab_json:
    out_dir_path = Path(st.session_state.get("out_dir", ROOT / "workspace" / "output"))
    json_file = out_dir_path / "feature_summary.json"
    if json_file.exists():
        data = json.loads(json_file.read_text())
        st.subheader("Feature Summary")
        col_m, col_r = st.columns(2)
        s = data.get("summary", {})
        with col_m:
            st.metric("NDVI (GEE)", f"{s.get('ndvi_gee', 0):.4f}",
                      delta=f"{s.get('ndvi_change_2018_2024', 0):+.4f}")
            st.metric("NDWI", f"{s.get('ndwi_mean', 0):.4f}")
            st.metric("Water Area", f"{s.get('water_area_km2', 0):.2f} km²")
        with col_r:
            st.metric("EVI", f"{s.get('evi_mean', 0):.4f}")
            st.metric("Embedding Change", f"{s.get('embedding_change_intensity', 0):.4f}")
            if s.get("dem_slope_mean_deg"):
                st.metric("DEM Slope Mean", f"{s['dem_slope_mean_deg']:.2f}°")
        st.json(data)
    else:
        st.info("Run the pipeline first.")

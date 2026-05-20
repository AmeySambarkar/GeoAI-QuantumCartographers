"""
Write all pipeline output artifacts to the workspace output directory.
"""
from __future__ import annotations

import csv
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def write_all(report_md: str, features_json: str, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {}

    # ── 1. Full markdown report ──────────────────────────────────────
    plan_path = output_dir / "water_plan.md"
    plan_path.write_text(report_md)
    paths["water_plan"] = plan_path
    logger.info("Written: %s", plan_path)

    # ── 2. Feature JSON ──────────────────────────────────────────────
    json_path = output_dir / "feature_summary.json"
    json_path.write_text(features_json)
    paths["feature_summary"] = json_path
    logger.info("Written: %s", json_path)

    # ── 3. Extract and write Python code ────────────────────────────
    py_code = _extract_code_block(report_md, "python")
    if py_code:
        py_path = output_dir / "pipeline_code.py"
        py_path.write_text(py_code)
        paths["pipeline_code"] = py_path
        logger.info("Written: %s", py_path)

    # ── 4. Extract and write R code ──────────────────────────────────
    r_code = _extract_code_block(report_md, "r")
    if r_code:
        r_path = output_dir / "scenario_analysis.R"
        r_path.write_text(r_code)
        paths["scenario_analysis"] = r_path
        logger.info("Written: %s", r_path)

    # ── 5. Extract risk table and write CSV ─────────────────────────
    risk_rows = _extract_risk_table(report_md)
    if risk_rows:
        csv_path = output_dir / "risk_assessment.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["Risk", "Likelihood", "Impact", "Trigger Metric", "Mitigation"])
            writer.writeheader()
            writer.writerows(risk_rows)
        paths["risk_assessment"] = csv_path
        logger.info("Written: %s (%d rows)", csv_path, len(risk_rows))

    return paths


def _extract_code_block(markdown: str, language: str) -> str:
    """Extract the first fenced code block for a given language."""
    pattern = rf"```{language}\s*\n(.*?)```"
    match = re.search(pattern, markdown, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _extract_risk_table(markdown: str) -> list[dict]:
    """Parse a markdown table in Section 5 into a list of dicts."""
    rows = []
    in_risk = False
    header = None
    for line in markdown.splitlines():
        if "risk assessment" in line.lower() and line.startswith("#"):
            in_risk = True
            continue
        if not in_risk:
            continue
        if line.startswith("#") and in_risk:
            break  # another section started
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue
        if header is None:
            # First pipe row is the header
            if any(h.lower() in ("risk", "likelihood") for h in cells):
                header = cells
            continue
        if all(re.match(r"^[-: ]+$", c) for c in cells if c):
            continue  # separator row
        if len(cells) >= len(header):
            rows.append(dict(zip(header, cells[:len(header)])))

    return rows


def print_summary(paths: dict[str, Path], features_json: str) -> None:
    try:
        data = json.loads(features_json)
        s = data.get("summary", {})
    except Exception:
        s = {}

    print("\n" + "=" * 70)
    print("  MULTI-SENSOR GEOSPATIAL WATER RESOURCE PIPELINE — RESULTS")
    print("=" * 70)
    print(f"  ROI               : {data.get('roi', {}).get('name', 'Unknown')}")
    print(f"  Analysis period   : {data.get('baseline_year')} → {data.get('analysis_year')}")
    print(f"  NDVI (GEE)        : {s.get('ndvi_gee', 'N/A')} (Δ {s.get('ndvi_change_2018_2024', 0):+.4f})")
    print(f"  NDWI (GEE)        : {s.get('ndwi_mean', 'N/A')}")
    print(f"  EVI (GEE)         : {s.get('evi_mean', 'N/A')}")
    print(f"  Water area        : {s.get('water_area_km2', 'N/A')} km²")
    print(f"  Embedding change  : {s.get('embedding_change_intensity', 'N/A')}")
    print(f"  Maxar scenes      : {s.get('maxar_scenes_available', 'N/A')}")
    if s.get("dem_slope_mean_deg"):
        print(f"  DEM slope mean    : {s['dem_slope_mean_deg']}°")
    print("\nOutput files:")
    for name, path in paths.items():
        print(f"  {name:<22} {path}")
    print("=" * 70)

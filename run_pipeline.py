#!/usr/bin/env python3
"""
Multi-Sensor Geospatial Intelligence Pipeline — Main Orchestrator
=================================================================
Cybernetic feedback loop:
  Sense  → ingest (GEE Sentinel-2 + Satellite Embeddings, Maxar STAC, local rasters)
  Process → spectral indices, DEM, change detection, Prithvi anomaly score
  Model  → feature aggregation → JSON
  Plan   → Claude analyst generates 5-section water resource report
  Output → water_plan.md, pipeline_code.py, scenario_analysis.R, risk_assessment.csv,
            feature_summary.json

Usage:
  # Demo mode (auto-generates synthetic data, no API keys needed):
  python run_pipeline.py --demo

  # With real local files:
  python run_pipeline.py --ms /path/to/LISS4.tif --dem /path/to/dem.tif

  # With all APIs:
  python run_pipeline.py --demo  # (set .env with ANTHROPIC_API_KEY etc.)
"""
import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")


def parse_args():
    p = argparse.ArgumentParser(
        description="Multi-sensor geospatial water resource pipeline (MVP/POC)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--demo",   action="store_true", help="Generate synthetic data and run end-to-end")
    p.add_argument("--ms",     default="",   metavar="PATH", help="Multispectral GeoTIFF (LISS-4 or HLS 6-band)")
    p.add_argument("--dem",    default="",   metavar="PATH", help="DEM GeoTIFF")
    p.add_argument("--roi",    nargs=4, type=float, default=None, metavar=("W","S","E","N"),
                   help="Bounding box in WGS-84 (default: Maharashtra pilot area)")
    p.add_argument("--baseline-year", type=int, default=2018)
    p.add_argument("--analysis-year", type=int, default=2024)
    p.add_argument("--out",    default="workspace/output", metavar="DIR")
    p.add_argument("--no-gee",   action="store_true", help="Skip GEE (use simulated data)")
    p.add_argument("--no-maxar", action="store_true", help="Skip Maxar (use simulated scenes)")
    p.add_argument("--no-claude", action="store_true", help="Skip Claude API (use template report)")
    return p.parse_args()


def main():
    args = parse_args()

    # ── 0. Configuration ────────────────────────────────────────────
    from satellite_pipeline.config import Config, ROI
    config = Config()
    if args.roi:
        config.roi = ROI(*args.roi)
    config.baseline_year = args.baseline_year
    config.analysis_year = args.analysis_year
    config.output_dir = Path(args.out)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    if args.no_claude:
        config.anthropic_api_key = ""
    if args.no_gee:
        config.gee_project = ""
        config.gee_service_account = ""
    if args.no_maxar:
        config.maxar_api_key = ""

    logger.info("Pipeline start — ROI: %s  |  %d→%d", config.roi.name, config.baseline_year, config.analysis_year)
    logger.info("APIs: Anthropic=%s  GEE=%s  Maxar=%s",
                "YES" if config.has_anthropic else "NO (template)",
                "YES" if config.has_gee else "NO (simulated)",
                "YES" if config.has_maxar else "NO (simulated)")

    # ── 1. Demo data generation ──────────────────────────────────────
    ms_path = args.ms
    dem_path = args.dem

    if args.demo:
        logger.info("DEMO MODE — generating synthetic GeoTIFFs …")
        from satellite_pipeline.demo.generate_sample_data import generate_all
        sample_files = generate_all(config.input_dir, roi_bbox=config.roi.bbox)
        if not ms_path:
            ms_path = str(sample_files["hls_analysis"])
        if not dem_path:
            dem_path = str(sample_files["dem"])

    # ── 2. Local raster ingestion ────────────────────────────────────
    from satellite_pipeline.ingest.local_raster import (
        inspect_raster, compute_spectral_stats, compute_dem_stats
    )

    raster_infos = []
    spectral_stats = None
    dem_stats = None

    if ms_path and Path(ms_path).exists():
        logger.info("Inspecting multispectral: %s", ms_path)
        info = inspect_raster(ms_path)
        raster_infos.append(info)
        if info.sensor_type in ("LISS4", "HLS"):
            spectral_stats = compute_spectral_stats(ms_path, info)
            logger.info("Local NDVI: %.4f  NDWI: %.4f  veg_frac: %.3f",
                        spectral_stats.ndvi_mean, spectral_stats.ndwi_mean, spectral_stats.vegetation_fraction)

    if dem_path and Path(dem_path).exists():
        logger.info("Computing DEM stats: %s", dem_path)
        dem_info = inspect_raster(dem_path)
        raster_infos.append(dem_info)
        dem_stats = compute_dem_stats(dem_path)
        logger.info("DEM: elev %.0f–%.0fm  slope mean %.2f°  flat %.1f%%",
                    dem_stats.elev_min, dem_stats.elev_max, dem_stats.slope_mean, dem_stats.flat_fraction * 100)

    # ── 3. Google Earth Engine ───────────────────────────────────────
    logger.info("Fetching GEE data (Sentinel-2 + Satellite Embeddings) …")
    from satellite_pipeline.ingest.gee_client import fetch_gee_data
    gee_result = fetch_gee_data(config)
    logger.info("GEE [%s]: NDVI=%.4f (Δ%.4f) NDWI=%.4f water=%.2f km² emb_change=%.4f",
                gee_result.source, gee_result.ndvi_mean, gee_result.ndvi_change,
                gee_result.ndwi_mean, gee_result.water_area_km2,
                gee_result.embedding_cosine_change or 0)

    # ── 4. Maxar STAC discovery ──────────────────────────────────────
    logger.info("Querying Maxar MGP catalog …")
    from satellite_pipeline.ingest.maxar_client import search_maxar_imagery
    maxar_result = search_maxar_imagery(config)
    logger.info("Maxar [%s]: %d scenes found", maxar_result.source, maxar_result.total_scenes)

    # ── 5. Change detection ──────────────────────────────────────────
    change_stats = None
    anomaly_score = None

    if args.demo:
        logger.info("Computing change detection (HLS baseline vs analysis) …")
        from satellite_pipeline.ingest.local_raster import read_bands
        from satellite_pipeline.process.change_detection import compute_index_change, prithvi_style_reconstruction_error
        from satellite_pipeline.process.spectral_indices import ndvi as compute_ndvi

        try:
            baseline_bands, _ = read_bands(str(sample_files["hls_baseline"]))
            analysis_bands, _ = read_bands(str(sample_files["hls_analysis"]))

            # Scale from DN to reflectance
            baseline_bands = baseline_bands / 10_000
            analysis_bands = analysis_bands / 10_000

            # NDVI from bands [Green, Red, NIR] = indices [1, 2, 3] (0-based)
            base_ndvi = compute_ndvi(baseline_bands[3], baseline_bands[2])
            anal_ndvi = compute_ndvi(analysis_bands[3], analysis_bands[2])

            chg = compute_index_change(base_ndvi, anal_ndvi)
            change_stats = {
                "mean_change": chg.mean_change,
                "change_intensity": chg.change_intensity,
                "gain_fraction": chg.gain_fraction,
                "loss_fraction": chg.loss_fraction,
                "stable_fraction": chg.stable_fraction,
            }
            logger.info("Change: mean=%.4f  intensity=%.4f  gain=%.3f  loss=%.3f",
                        chg.mean_change, chg.change_intensity, chg.gain_fraction, chg.loss_fraction)

            anomaly_score = prithvi_style_reconstruction_error(analysis_bands)
            logger.info("Prithvi-style anomaly score: %.6f", anomaly_score)

        except Exception as exc:
            logger.warning("Change detection failed: %s", exc)

    # ── 6. Feature aggregation ───────────────────────────────────────
    logger.info("Aggregating features …")
    from satellite_pipeline.fusion.feature_aggregator import build_features, to_json
    features = build_features(
        config=config,
        local_raster_infos=raster_infos,
        local_spectral_stats=spectral_stats,
        dem_stats=dem_stats,
        gee_result=gee_result,
        maxar_result=maxar_result,
        change_stats=change_stats,
        anomaly_score=anomaly_score,
    )
    features_json = to_json(features)

    # ── 7. Claude intelligence layer ─────────────────────────────────
    logger.info("Generating water resource report (Claude %s) …", config.claude_model)
    from satellite_pipeline.intelligence.claude_analyst import generate_report
    report_md = generate_report(features_json, config)

    # ── 8. Write all outputs ─────────────────────────────────────────
    from satellite_pipeline.output.report_writer import write_all, print_summary
    output_paths = write_all(report_md, features_json, config.output_dir)
    print_summary(output_paths, features_json)

    logger.info("Pipeline complete. Run ID: %s", features.run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())

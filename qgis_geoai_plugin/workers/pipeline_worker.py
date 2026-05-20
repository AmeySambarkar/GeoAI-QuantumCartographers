"""
QThread worker — runs the satellite_pipeline in the background so QGIS
UI stays responsive. Emits progress signals consumed by the dock panel.
"""
from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

from qgis.PyQt.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class PipelineWorker(QThread):
    """
    Runs run_pipeline.main() in a background thread.
    Signals:
      progress(int 0-100)        — emitted at each major stage
      stage_changed(str)         — human-readable stage description
      finished_ok(str, str)      — (features_json, report_md) on success
      finished_error(str)        — error message on failure
    """
    progress      = pyqtSignal(int)
    stage_changed = pyqtSignal(str)
    finished_ok   = pyqtSignal(str, str)   # features_json, report_md
    finished_error = pyqtSignal(str)

    def __init__(
        self,
        config,
        ms_path: str = "",
        dem_path: str = "",
        demo_mode: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.config    = config
        self.ms_path   = ms_path
        self.dem_path  = dem_path
        self.demo_mode = demo_mode

    def run(self):
        try:
            self._execute()
        except Exception as exc:
            tb = traceback.format_exc()
            self.finished_error.emit(f"{exc}\n\n{tb}")

    def _execute(self):
        repo_root = str(Path(__file__).resolve().parents[2])
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)

        config = self.config

        # ── Stage 1: demo data ──────────────────────────────────────
        self.stage_changed.emit("Generating synthetic data…" if self.demo_mode else "Checking input files…")
        self.progress.emit(5)

        ms_path   = self.ms_path
        dem_path  = self.dem_path
        sample_files = {}

        if self.demo_mode:
            from satellite_pipeline.demo.generate_sample_data import generate_all
            sample_files = generate_all(config.input_dir, roi_bbox=config.roi.bbox)
            if not ms_path:
                ms_path = str(sample_files.get("hls_analysis", ""))
            if not dem_path:
                dem_path = str(sample_files.get("dem", ""))

        self.progress.emit(15)

        # ── Stage 2: local raster ingestion ────────────────────────
        self.stage_changed.emit("Inspecting local rasters…")
        from satellite_pipeline.ingest.local_raster import (
            inspect_raster, compute_spectral_stats, compute_dem_stats,
        )

        raster_infos   = []
        spectral_stats = None
        dem_stats      = None

        if ms_path and Path(ms_path).exists():
            info = inspect_raster(ms_path)
            raster_infos.append(info)
            if info.sensor_type in ("LISS4", "HLS"):
                spectral_stats = compute_spectral_stats(ms_path, info)

        if dem_path and Path(dem_path).exists():
            dem_info = inspect_raster(dem_path)
            raster_infos.append(dem_info)
            dem_stats = compute_dem_stats(dem_path)

        self.progress.emit(30)

        # ── Stage 3: GEE ──────────────────────────────────────────
        self.stage_changed.emit("Fetching GEE data (Sentinel-2 + Embeddings)…")
        from satellite_pipeline.ingest.gee_client import fetch_gee_data
        gee_result = fetch_gee_data(config)
        self.progress.emit(50)

        # ── Stage 4: Maxar ─────────────────────────────────────────
        self.stage_changed.emit("Searching Maxar catalog…")
        from satellite_pipeline.ingest.maxar_client import search_maxar_imagery
        maxar_result = search_maxar_imagery(config)
        self.progress.emit(60)

        # ── Stage 5: change detection ───────────────────────────────
        self.stage_changed.emit("Computing change detection…")
        change_stats = None
        anomaly_score = None

        if self.demo_mode and sample_files:
            from satellite_pipeline.ingest.local_raster import read_bands
            from satellite_pipeline.process.change_detection import (
                compute_index_change, prithvi_style_reconstruction_error,
            )
            from satellite_pipeline.process.spectral_indices import ndvi as compute_ndvi

            try:
                b_bands, _ = read_bands(str(sample_files["hls_baseline"]))
                a_bands, _ = read_bands(str(sample_files["hls_analysis"]))
                b_bands, a_bands = b_bands / 10_000, a_bands / 10_000
                base_ndvi = compute_ndvi(b_bands[3], b_bands[2])
                anal_ndvi = compute_ndvi(a_bands[3], a_bands[2])
                chg = compute_index_change(base_ndvi, anal_ndvi)
                change_stats = {
                    "mean_change": chg.mean_change,
                    "change_intensity": chg.change_intensity,
                    "gain_fraction": chg.gain_fraction,
                    "loss_fraction": chg.loss_fraction,
                    "stable_fraction": chg.stable_fraction,
                }
                anomaly_score = prithvi_style_reconstruction_error(a_bands)
            except Exception:
                pass

        self.progress.emit(70)

        # ── Stage 6: feature aggregation ───────────────────────────
        self.stage_changed.emit("Aggregating features…")
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
        features_json = to_json(features, config.output_dir / "feature_summary.json")
        self.progress.emit(85)

        # ── Stage 7: Claude report ──────────────────────────────────
        self.stage_changed.emit("Generating report (Claude)…")
        from satellite_pipeline.intelligence.claude_analyst import generate_report
        from satellite_pipeline.output.report_writer import write_all
        report_md = generate_report(features_json, config)
        write_all(report_md, features_json, config.output_dir)
        self.progress.emit(100)

        self.finished_ok.emit(features_json, report_md)

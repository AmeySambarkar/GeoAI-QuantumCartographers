"""
Temporal change detection engine.
Compares two raster layers and produces:
  1. NDVI z-score change map (layer)
  2. Cosine embedding dissimilarity map (layer, if 64-band embeddings available)
  3. Water body gain/loss classification (layer)
  4. Summary statistics dict for the monitoring engine
"""
from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from typing import Optional

import numpy as np

from qgis.core import QgsRasterLayer, QgsMessageLog, Qgis

from .layer_manager import get_layer_bands, add_index_layer_from_array
from .index_engine import _safe, _detect_band_map

logger = logging.getLogger(__name__)


@dataclass
class ChangeReport:
    index_used: str
    mean_change: float
    change_intensity: float   # RMS of z-scores
    gain_fraction: float      # pixels z > +1.96
    loss_fraction: float      # pixels z < -1.96
    stable_fraction: float
    new_water_fraction: float
    lost_water_fraction: float
    embedding_dissimilarity: Optional[float]  # None if not 64-band
    baseline_mean: float
    analysis_mean: float


def run_change_detection(
    baseline_layer: QgsRasterLayer,
    analysis_layer: QgsRasterLayer,
    index_name: str = "NDVI",
    scale_factor: float = 10_000.0,
    progress_callback=None,
) -> ChangeReport:
    """
    Main entry point. Computes change between two raster layers and
    adds styled change layers to the QGIS project.
    """
    baseline_bands = get_layer_bands(baseline_layer)
    analysis_bands = get_layer_bands(analysis_layer)

    n = baseline_bands.shape[0]
    bmap = _detect_band_map(n)

    # Scale if needed
    if np.nanmax(baseline_bands) > 2.0:
        baseline_bands = baseline_bands / scale_factor
    if np.nanmax(analysis_bands) > 2.0:
        analysis_bands = analysis_bands / scale_factor

    if progress_callback:
        progress_callback(10)

    # ── Spectral index change ──────────────────────────────────────────
    if bmap and "nir" in bmap and "red" in bmap:
        base_idx = _safe(
            baseline_bands[bmap["nir"]] - baseline_bands[bmap["red"]],
            baseline_bands[bmap["nir"]] + baseline_bands[bmap["red"]],
        )
        anal_idx = _safe(
            analysis_bands[bmap["nir"]] - analysis_bands[bmap["red"]],
            analysis_bands[bmap["nir"]] + analysis_bands[bmap["red"]],
        )
        idx_used = "NDVI"
    else:
        # Single-band fallback (DEM or panchromatic)
        base_idx = baseline_bands[0]
        anal_idx = analysis_bands[0]
        idx_used = "Band1"

    diff = anal_idx - base_idx
    z_score = (diff - float(np.nanmean(diff))) / (float(np.nanstd(diff)) + 1e-8)

    if progress_callback:
        progress_callback(40)

    # Add change layer (z-score)
    layer_name = f"Change ({idx_used}) — {baseline_layer.name()} → {analysis_layer.name()}"
    add_index_layer_from_array(z_score, baseline_layer, "CHANGE_ZSCORE", display_name=layer_name)

    # ── Water body change ──────────────────────────────────────────────
    new_water = lost_water = 0.0
    if bmap and "green" in bmap and "nir" in bmap:
        b_ndwi = _safe(
            baseline_bands[bmap["green"]] - baseline_bands[bmap["nir"]],
            baseline_bands[bmap["green"]] + baseline_bands[bmap["nir"]],
        )
        a_ndwi = _safe(
            analysis_bands[bmap["green"]] - analysis_bands[bmap["nir"]],
            analysis_bands[bmap["green"]] + analysis_bands[bmap["nir"]],
        )
        b_water = b_ndwi > 0.0
        a_water = a_ndwi > 0.0

        # 4-class water change map: 0=dry, 1=new water, 2=lost water, 3=persistent
        water_change = np.zeros_like(b_ndwi, dtype=np.float32)
        water_change[~b_water & a_water] = 1.0   # new water (gain)
        water_change[b_water & ~a_water] = -1.0  # lost water
        water_change[b_water & a_water]  = 0.5   # persistent

        add_index_layer_from_array(
            water_change, baseline_layer, "CHANGE_ZSCORE",
            display_name=f"Water Change — {baseline_layer.name()} → {analysis_layer.name()}"
        )

        valid = ~np.isnan(b_ndwi)
        new_water  = float(np.mean(water_change[valid] == 1.0))
        lost_water = float(np.mean(water_change[valid] == -1.0))

    if progress_callback:
        progress_callback(70)

    # ── Embedding-style cosine dissimilarity (if 64-band input) ───────
    emb_dissim = None
    if n >= 32:  # treat as embedding stack (Google Satellite Embedding V1 = 64 bands)
        norm_b = np.linalg.norm(baseline_bands, axis=0, keepdims=True) + 1e-8
        norm_a = np.linalg.norm(analysis_bands, axis=0, keepdims=True) + 1e-8
        cos_sim = np.sum(
            (baseline_bands / norm_b) * (analysis_bands / norm_a), axis=0
        )
        cos_dissim = np.clip(1.0 - cos_sim, 0.0, 2.0)
        add_index_layer_from_array(
            cos_dissim, baseline_layer, "EMBEDDING_CHANGE",
            display_name=f"Embedding Dissimilarity — {baseline_layer.name()} → {analysis_layer.name()}"
        )
        emb_dissim = round(float(np.nanmean(cos_dissim)), 4)

    if progress_callback:
        progress_callback(100)

    valid_z = z_score[~np.isnan(z_score)]
    report = ChangeReport(
        index_used=idx_used,
        mean_change=round(float(np.nanmean(diff)), 4),
        change_intensity=round(float(np.sqrt(np.nanmean(z_score**2))), 4),
        gain_fraction=round(float(np.mean(valid_z > 1.96)), 4),
        loss_fraction=round(float(np.mean(valid_z < -1.96)), 4),
        stable_fraction=round(float(np.mean(np.abs(valid_z) <= 1.96)), 4),
        new_water_fraction=round(new_water, 4),
        lost_water_fraction=round(lost_water, 4),
        embedding_dissimilarity=emb_dissim,
        baseline_mean=round(float(np.nanmean(base_idx)), 4),
        analysis_mean=round(float(np.nanmean(anal_idx)), 4),
    )

    QgsMessageLog.logMessage(
        f"Change detection: {idx_used} {report.baseline_mean:.4f}→{report.analysis_mean:.4f} "
        f"(Δ{report.mean_change:+.4f}) | loss={report.loss_fraction:.3f} gain={report.gain_fraction:.3f}",
        "GeoAI", Qgis.Info,
    )
    return report

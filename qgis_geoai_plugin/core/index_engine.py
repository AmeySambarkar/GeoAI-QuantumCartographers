"""
Spectral index computation from QGIS raster layers.
Detects sensor type from band count, computes all valid indices,
writes each as a styled layer in the GeoAI group.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from qgis.core import QgsRasterLayer, QgsMessageLog, Qgis

from .layer_manager import get_layer_bands, add_index_layer_from_array, list_raster_layers

logger = logging.getLogger(__name__)

# Band indices (0-based) by sensor type
_BAND_MAP = {
    # [Blue, Green, Red, NIR, SWIR1, SWIR2]  — HLS / Sentinel-2 style
    6: {"blue": 0, "green": 1, "red": 2, "nir": 3, "swir1": 4, "swir2": 5},
    # [Green, Red, NIR]  — LISS-4 / Landsat reduced
    3: {"green": 0, "red": 1, "nir": 2},
    # [Red, Green, Blue]  — RGB true colour
    "rgb3": {"red": 0, "green": 1, "blue": 2},
}


def _safe(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(np.abs(den) > 1e-6, num / den, np.nan)
    return np.clip(out, -1.0, 1.0)


def _detect_band_map(n_bands: int) -> Optional[dict]:
    if n_bands >= 6:
        return _BAND_MAP[6]
    if n_bands == 3:
        return _BAND_MAP[3]
    return None


def compute_and_add_indices(
    source_layer: QgsRasterLayer,
    indices_requested: list[str] | None = None,
    scale_factor: float = 10_000.0,
    progress_callback=None,
) -> dict[str, np.ndarray]:
    """
    Main entry point called from the dock panel.
    Computes requested spectral indices from source_layer and adds each as a
    styled QGIS layer. Returns dict of index_name → array for downstream use.
    """
    bands_raw = get_layer_bands(source_layer)
    n = bands_raw.shape[0]
    bmap = _detect_band_map(n)

    if bmap is None:
        QgsMessageLog.logMessage(
            f"Cannot compute spectral indices: {n}-band layer not supported. "
            "Need 3-band (LISS-4) or 6-band (HLS/Sentinel-2) input.",
            "GeoAI", Qgis.Warning,
        )
        return {}

    # Scale DN → reflectance (if values look like DNs > 2)
    if np.nanmax(bands_raw) > 2.0:
        bands = bands_raw / scale_factor
    else:
        bands = bands_raw

    results = {}
    all_possible = _available_indices(bmap)
    targets = [i.upper() for i in (indices_requested or all_possible)]

    for i, index_name in enumerate(targets):
        if index_name not in all_possible:
            continue
        arr = _compute_index(index_name, bands, bmap)
        if arr is None:
            continue
        results[index_name] = arr
        label = f"{index_name} — {source_layer.name()}"
        add_index_layer_from_array(arr, source_layer, index_name, display_name=label)
        QgsMessageLog.logMessage(
            f"Added {index_name}: mean={float(np.nanmean(arr)):.4f} std={float(np.nanstd(arr)):.4f}",
            "GeoAI", Qgis.Info,
        )
        if progress_callback:
            progress_callback(int((i + 1) / len(targets) * 100))

    return results


def _compute_index(name: str, b: np.ndarray, bmap: dict) -> Optional[np.ndarray]:
    g = lambda k: b[bmap[k]] if k in bmap else None

    blue  = g("blue")
    green = g("green")
    red   = g("red")
    nir   = g("nir")
    swir1 = g("swir1")
    swir2 = g("swir2")

    if name == "NDVI":
        return _safe(nir - red, nir + red)
    if name == "NDWI":
        return _safe(green - nir, green + nir)
    if name == "EVI" and blue is not None:
        return np.clip(2.5 * (nir - red) / (nir + 6*red - 7.5*blue + 1), -1, 1)
    if name == "MNDWI" and swir1 is not None:
        return _safe(green - swir1, green + swir1)
    if name == "SAVI":
        L = 0.5
        return _safe((nir - red) * (1 + L), nir + red + L)
    if name == "NBR" and swir2 is not None:
        return _safe(nir - swir2, nir + swir2)
    return None


def _available_indices(bmap: dict) -> list[str]:
    keys = set(bmap.keys())
    indices = []
    if "nir" in keys and "red" in keys:
        indices += ["NDVI", "SAVI"]
    if "green" in keys and "nir" in keys:
        indices.append("NDWI")
    if "blue" in keys and "nir" in keys and "red" in keys:
        indices.append("EVI")
    if "green" in keys and "swir1" in keys:
        indices.append("MNDWI")
    if "nir" in keys and "swir2" in keys:
        indices.append("NBR")
    return indices


def index_statistics(array: np.ndarray) -> dict:
    valid = array[~np.isnan(array)]
    if valid.size == 0:
        return {}
    return {
        "mean": round(float(np.mean(valid)), 4),
        "std":  round(float(np.std(valid)), 4),
        "min":  round(float(np.min(valid)), 4),
        "max":  round(float(np.max(valid)), 4),
        "p25":  round(float(np.percentile(valid, 25)), 4),
        "p75":  round(float(np.percentile(valid, 75)), 4),
        "veg_fraction":    round(float(np.mean(valid > 0.3)), 4) if valid.max() <= 1.1 else None,
        "water_fraction":  round(float(np.mean(valid > 0.0)), 4) if valid.min() >= -1.1 else None,
    }

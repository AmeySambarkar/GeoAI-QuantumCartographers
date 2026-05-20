"""
Spectral index computations.
All functions operate on float32 numpy arrays in [0, 1] reflectance space.
"""
from __future__ import annotations

import numpy as np


def _safe_ratio(num: np.ndarray, denom: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(np.abs(denom) > 1e-6, num / denom, np.nan)
    return np.clip(out, -1.0, 1.0)


def ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    """Normalized Difference Vegetation Index [-1, 1]."""
    return _safe_ratio(nir - red, nir + red)


def evi(nir: np.ndarray, red: np.ndarray, blue: np.ndarray, L: float = 1.0, C1: float = 6.0, C2: float = 7.5, G: float = 2.5) -> np.ndarray:
    """Enhanced Vegetation Index — less soil/atmosphere sensitive than NDVI."""
    denom = nir + C1 * red - C2 * blue + L
    with np.errstate(invalid="ignore", divide="ignore"):
        result = np.where(np.abs(denom) > 1e-6, G * (nir - red) / denom, np.nan)
    return np.clip(result, -1.0, 1.0)


def mndwi(green: np.ndarray, swir1: np.ndarray) -> np.ndarray:
    """Modified Normalized Difference Water Index (Xu 2006)."""
    return _safe_ratio(green - swir1, green + swir1)


def ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """Normalized Difference Water Index (McFeeters 1996)."""
    return _safe_ratio(green - nir, green + nir)


def savi(nir: np.ndarray, red: np.ndarray, L: float = 0.5) -> np.ndarray:
    """Soil-Adjusted Vegetation Index."""
    return _safe_ratio((nir - red) * (1 + L), nir + red + L)


def nbr(nir: np.ndarray, swir2: np.ndarray) -> np.ndarray:
    """Normalized Burn Ratio."""
    return _safe_ratio(nir - swir2, nir + swir2)


def compute_all_indices(bands: np.ndarray, sensor_type: str) -> dict[str, np.ndarray]:
    """
    Compute all available indices from a band stack.
    Returns a dict of index_name -> 2D array.
    """
    results = {}

    if sensor_type == "LISS4" and bands.shape[0] >= 3:
        green, red, nir = bands[0] / 10_000, bands[1] / 10_000, bands[2] / 10_000
        results["NDVI"] = ndvi(nir, red)
        results["NDWI"] = ndwi(green, nir)
        results["SAVI"] = savi(nir, red)

    elif sensor_type == "HLS" and bands.shape[0] >= 6:
        blue = bands[0] / 10_000
        green = bands[1] / 10_000
        red = bands[2] / 10_000
        nir = bands[3] / 10_000
        swir1 = bands[4] / 10_000
        swir2 = bands[5] / 10_000
        results["NDVI"] = ndvi(nir, red)
        results["EVI"] = evi(nir, red, blue)
        results["NDWI"] = ndwi(green, nir)
        results["MNDWI"] = mndwi(green, swir1)
        results["SAVI"] = savi(nir, red)
        results["NBR"] = nbr(nir, swir2)

    return results


def index_stats(arr: np.ndarray) -> dict:
    valid = arr[~np.isnan(arr)]
    if valid.size == 0:
        return {"mean": None, "std": None, "min": None, "max": None, "p10": None, "p90": None}
    return {
        "mean": round(float(np.mean(valid)), 4),
        "std": round(float(np.std(valid)), 4),
        "min": round(float(np.min(valid)), 4),
        "max": round(float(np.max(valid)), 4),
        "p10": round(float(np.percentile(valid, 10)), 4),
        "p90": round(float(np.percentile(valid, 90)), 4),
    }

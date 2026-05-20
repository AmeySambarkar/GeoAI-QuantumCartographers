"""
Google Earth Engine client.
Fetches Sentinel-2 NDVI/NDWI composites and the GOOGLE Satellite Embedding V1.
Falls back to simulated results if GEE is not authenticated.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class GEEResult:
    ndvi_mean: float
    ndwi_mean: float
    evi_mean: float
    embedding_cosine_change: Optional[float]  # baseline vs analysis year
    baseline_ndvi: float
    analysis_ndvi: float
    ndvi_change: float
    water_area_km2: float
    source: str  # "GEE" | "SIMULATED"


def _try_import_ee():
    try:
        import ee
        return ee
    except ImportError:
        return None


def _authenticate(config) -> bool:
    """Return True if EE is ready."""
    ee = _try_import_ee()
    if ee is None:
        logger.warning("earthengine-api not installed — using simulated GEE data")
        return False
    try:
        if config.gee_service_account and config.gee_key_file:
            credentials = ee.ServiceAccountCredentials(config.gee_service_account, config.gee_key_file)
            ee.Initialize(credentials=credentials, project=config.gee_project)
        else:
            ee.Initialize(project=config.gee_project or None)
        ee.Number(1).getInfo()  # smoke test
        logger.info("GEE authenticated")
        return True
    except Exception as exc:
        logger.warning("GEE auth failed (%s) — using simulated data", exc)
        return False


def _s2_cloud_free(ee, collection_id: str, roi, year: int, cloud_max: int):
    """Return a cloud-free Sentinel-2 composite for a given year."""
    start = f"{year}-05-01"
    end = f"{year}-10-31"
    col = (
        ee.ImageCollection(collection_id)
        .filterBounds(roi)
        .filterDate(start, end)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_max))
        .select(["B2", "B3", "B4", "B8", "B11", "B12"])  # Blue, Green, Red, NIR, SWIR1, SWIR2
        .median()
        .divide(10_000)
    )
    return col


def _compute_indices(ee, img):
    ndvi = img.normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndwi = img.normalizedDifference(["B3", "B8"]).rename("NDWI")
    evi = img.expression(
        "2.5 * (NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1)",
        {"NIR": img.select("B8"), "RED": img.select("B4"), "BLUE": img.select("B2")},
    ).rename("EVI")
    return ee.Image.cat([ndvi, ndwi, evi])


def _mean_stat(ee, img, roi, band_name: str) -> float:
    stat = img.select(band_name).reduceRegion(
        reducer=ee.Reducer.mean(), geometry=roi, scale=10, maxPixels=1e9
    ).get(band_name)
    return float(stat.getInfo() or 0.0)


def _embedding_change(ee, roi, baseline_year: int, analysis_year: int) -> Optional[float]:
    """
    Compute cosine similarity change between baseline and analysis year
    using the Google Satellite Embedding V1 (64-dim per-pixel embeddings).
    Returns 1 - cosine_similarity (0 = identical, 2 = opposite).
    """
    try:
        col = ee.ImageCollection("GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL")
        base_img = col.filter(ee.Filter.calendarRange(baseline_year, baseline_year, "year")).first()
        anal_img = col.filter(ee.Filter.calendarRange(analysis_year, analysis_year, "year")).first()

        # Dot product of mean embedding vectors
        base_vec = base_img.reduceRegion(ee.Reducer.mean(), roi, 10, maxPixels=1e9)
        anal_vec = anal_img.reduceRegion(ee.Reducer.mean(), roi, 10, maxPixels=1e9)

        bands = base_img.bandNames().getInfo()
        base_arr = np.array([base_vec.get(b).getInfo() for b in bands], dtype=np.float32)
        anal_arr = np.array([anal_vec.get(b).getInfo() for b in bands], dtype=np.float32)

        cosine = float(np.dot(base_arr, anal_arr) / (np.linalg.norm(base_arr) * np.linalg.norm(anal_arr) + 1e-8))
        return round(1.0 - cosine, 4)
    except Exception as exc:
        logger.warning("Embedding change computation failed: %s", exc)
        return None


def fetch_gee_data(config) -> GEEResult:
    """
    Main entry point. Returns spectral indices + embedding change for the ROI.
    Automatically falls back to realistic simulated data if GEE is unavailable.
    """
    roi = config.roi
    baseline_year = config.baseline_year
    analysis_year = config.analysis_year

    if not _authenticate(config):
        return _simulate(roi, baseline_year, analysis_year)

    ee = _try_import_ee()

    try:
        ee_roi = roi.ee_geometry

        base_img = _s2_cloud_free(ee, config.sentinel2_collection, ee_roi, baseline_year, config.cloud_cover_max)
        anal_img = _s2_cloud_free(ee, config.sentinel2_collection, ee_roi, analysis_year, config.cloud_cover_max)

        base_indices = _compute_indices(ee, base_img)
        anal_indices = _compute_indices(ee, anal_img)

        baseline_ndvi = _mean_stat(ee, base_indices, ee_roi, "NDVI")
        analysis_ndvi = _mean_stat(ee, anal_indices, ee_roi, "NDVI")
        ndwi_mean = _mean_stat(ee, anal_indices, ee_roi, "NDWI")
        evi_mean = _mean_stat(ee, anal_indices, ee_roi, "EVI")

        # Water area: pixels where NDWI > 0
        water_mask = anal_indices.select("NDWI").gt(0)
        water_area = water_mask.multiply(ee.Image.pixelArea()).reduceRegion(
            ee.Reducer.sum(), ee_roi, 10, maxPixels=1e9
        ).get("NDWI")
        water_km2 = float(water_area.getInfo() or 0) / 1e6

        emb_change = _embedding_change(ee, ee_roi, baseline_year, analysis_year)

        return GEEResult(
            ndvi_mean=round(analysis_ndvi, 4),
            ndwi_mean=round(ndwi_mean, 4),
            evi_mean=round(evi_mean, 4),
            embedding_cosine_change=emb_change,
            baseline_ndvi=round(baseline_ndvi, 4),
            analysis_ndvi=round(analysis_ndvi, 4),
            ndvi_change=round(analysis_ndvi - baseline_ndvi, 4),
            water_area_km2=round(water_km2, 3),
            source="GEE",
        )
    except Exception as exc:
        logger.warning("GEE query failed (%s) — falling back to simulation", exc)
        return _simulate(roi, baseline_year, analysis_year)


def _simulate(roi, baseline_year: int, analysis_year: int) -> GEEResult:
    """
    Physics-informed simulation of GEE outputs.
    Values are derived from typical semi-arid agricultural zones in Maharashtra.
    """
    rng = np.random.default_rng(seed=int(roi.west * 100) % 9999)
    base_ndvi = float(rng.uniform(0.32, 0.45))
    anal_ndvi = float(rng.uniform(0.28, 0.48))  # slight degradation plausible
    ndvi_change = anal_ndvi - base_ndvi
    ndwi = float(rng.uniform(-0.05, 0.22))
    evi = float(rng.uniform(0.18, 0.35))
    emb_change = float(rng.uniform(0.04, 0.16))  # moderate landscape change
    water_km2 = float(rng.uniform(1.2, 8.5))

    logger.info(
        "SIMULATED GEE: NDVI=%.3f (Δ%.3f), NDWI=%.3f, water=%.2f km²",
        anal_ndvi, ndvi_change, ndwi, water_km2,
    )

    return GEEResult(
        ndvi_mean=round(anal_ndvi, 4),
        ndwi_mean=round(ndwi, 4),
        evi_mean=round(evi, 4),
        embedding_cosine_change=round(emb_change, 4),
        baseline_ndvi=round(base_ndvi, 4),
        analysis_ndvi=round(anal_ndvi, 4),
        ndvi_change=round(ndvi_change, 4),
        water_area_km2=round(water_km2, 3),
        source="SIMULATED",
    )

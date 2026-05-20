"""
Google Earth Engine → QGIS bridge.
Fetches cloud-free Sentinel-2 composites and Google Satellite Embedding V1
layers, exports them to temporary GeoTIFFs, then loads them into QGIS.

Two modes:
  1. Full GEE export (requires authenticated earthengine-api):
     Exports to Google Drive, then expects user to download and load.
  2. Direct pixel pull via ee.Image.getPixels() for small extents (<10k pixels):
     Loads directly without Drive export — used for POC/demo ROIs.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np

from qgis.core import QgsRasterLayer, QgsMessageLog, Qgis, QgsProject

from ..core.layer_manager import add_raster_layer
from ..core.symbology import apply_index_style

logger = logging.getLogger(__name__)

GEE_S2_COLLECTION      = "COPERNICUS/S2_SR_HARMONIZED"
GEE_EMBEDDING_COLLECTION = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
GEE_EXPORT_SCALE       = 10   # metres


def _try_ee_init(project: str = "") -> Optional[object]:
    try:
        import ee
        try:
            ee.Initialize(project=project or None)
        except Exception:
            ee.Authenticate()
            ee.Initialize(project=project or None)
        return ee
    except ImportError:
        QgsMessageLog.logMessage(
            "earthengine-api not installed. Run: pip install earthengine-api",
            "GeoAI", Qgis.Warning,
        )
        return None
    except Exception as exc:
        QgsMessageLog.logMessage(f"GEE auth failed: {exc}", "GeoAI", Qgis.Warning)
        return None


def load_sentinel2_composite(
    bbox: list[float],           # [west, south, east, north]
    year: int,
    gee_project: str = "",
    cloud_max: int = 20,
    display_name: Optional[str] = None,
) -> Optional[QgsRasterLayer]:
    """
    Fetch a cloud-free Sentinel-2 growing-season composite for the given year/ROI,
    write to a temp GeoTIFF, and load into QGIS with NDVI-style colouring.
    Returns None if GEE is unavailable (graceful degradation).
    """
    ee = _try_ee_init(gee_project)
    if ee is None:
        QgsMessageLog.logMessage("GEE unavailable — Sentinel-2 layer skipped", "GeoAI", Qgis.Warning)
        return None

    roi = ee.Geometry.Rectangle(bbox)
    start, end = f"{year}-05-01", f"{year}-10-31"

    try:
        composite = (
            ee.ImageCollection(GEE_S2_COLLECTION)
            .filterBounds(roi)
            .filterDate(start, end)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_max))
            .select(["B4", "B8"])  # Red, NIR for NDVI
            .median()
            .divide(10_000)
        )
        ndvi_img = composite.normalizedDifference(["B8", "B4"]).rename("NDVI")

        # Direct pixel pull for small ROI (avoids Drive export for demo)
        pixels = _pull_pixels(ee, ndvi_img, roi, scale=GEE_EXPORT_SCALE, bands=["NDVI"])
        if pixels is None:
            return None

        tmp = _save_to_geotiff(pixels["NDVI"], bbox, f"S2_NDVI_{year}")
        name = display_name or f"Sentinel-2 NDVI {year}"
        layer = add_raster_layer(tmp, name, index_style="NDVI")
        QgsMessageLog.logMessage(f"GEE: Loaded Sentinel-2 NDVI {year}", "GeoAI", Qgis.Info)
        return layer

    except Exception as exc:
        QgsMessageLog.logMessage(f"GEE Sentinel-2 load failed: {exc}", "GeoAI", Qgis.Warning)
        return None


def load_satellite_embeddings(
    bbox: list[float],
    year: int,
    gee_project: str = "",
    n_pca_components: int = 3,     # reduce 64-dim to 3 for RGB visualisation
    display_name: Optional[str] = None,
) -> Optional[QgsRasterLayer]:
    """
    Load Google Satellite Embedding V1 (64-dim annual embeddings at 10m).
    Reduces to 3 components via PCA for RGB false-colour display in QGIS.
    High-change areas appear as distinctly coloured clusters.
    """
    ee = _try_ee_init(gee_project)
    if ee is None:
        return None

    roi = ee.Geometry.Rectangle(bbox)
    try:
        emb_col = ee.ImageCollection(GEE_EMBEDDING_COLLECTION)
        emb_img = emb_col.filter(ee.Filter.calendarRange(year, year, "year")).first()
        if emb_img is None:
            QgsMessageLog.logMessage(f"No embedding data for year {year}", "GeoAI", Qgis.Warning)
            return None

        band_names = emb_img.bandNames().getInfo()
        # Pull first n_pca_components*4 bands for PCA (avoid pulling all 64 for small demo)
        select_bands = band_names[:min(16, len(band_names))]
        sub_img = emb_img.select(select_bands)

        pixels = _pull_pixels(ee, sub_img, roi, scale=GEE_EXPORT_SCALE, bands=select_bands)
        if pixels is None:
            return None

        # Stack into [bands, H, W]
        H, W = list(pixels.values())[0].shape
        stack = np.stack([pixels[b] for b in select_bands], axis=0).astype(np.float32)

        # PCA to 3 components for RGB visualisation
        rgb = _pca_to_rgb(stack)

        tmp = _save_to_geotiff(rgb, bbox, f"EmbeddingPCA_{year}", bands=3)
        name = display_name or f"Satellite Embedding PCA {year}"
        layer = QgsRasterLayer(tmp, name)
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            QgsMessageLog.logMessage(f"GEE: Loaded Embedding PCA {year}", "GeoAI", Qgis.Info)
            return layer

    except Exception as exc:
        QgsMessageLog.logMessage(f"GEE Embedding load failed: {exc}", "GeoAI", Qgis.Warning)
    return None


def compute_change_layer_gee(
    bbox: list[float],
    baseline_year: int,
    analysis_year: int,
    gee_project: str = "",
) -> Optional[QgsRasterLayer]:
    """
    Compute NDVI change magnitude from GEE and load as a styled CHANGE_ZSCORE layer.
    """
    ee = _try_ee_init(gee_project)
    if ee is None:
        return None

    roi = ee.Geometry.Rectangle(bbox)

    def s2_ndvi(year):
        return (
            ee.ImageCollection(GEE_S2_COLLECTION)
            .filterBounds(roi)
            .filterDate(f"{year}-05-01", f"{year}-10-31")
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
            .select(["B4", "B8"])
            .median()
            .divide(10_000)
            .normalizedDifference(["B8", "B4"])
            .rename("NDVI")
        )

    try:
        base_ndvi = s2_ndvi(baseline_year)
        anal_ndvi = s2_ndvi(analysis_year)
        diff = anal_ndvi.subtract(base_ndvi).rename("CHANGE")

        pixels = _pull_pixels(ee, diff, roi, scale=GEE_EXPORT_SCALE, bands=["CHANGE"])
        if pixels is None:
            return None

        chg = pixels["CHANGE"]
        # Z-score normalise
        z = (chg - float(np.nanmean(chg))) / (float(np.nanstd(chg)) + 1e-8)

        tmp = _save_to_geotiff(z, bbox, f"GEE_Change_{baseline_year}_{analysis_year}")
        name = f"GEE Change {baseline_year}→{analysis_year}"
        return add_raster_layer(tmp, name, index_style="CHANGE_ZSCORE")

    except Exception as exc:
        QgsMessageLog.logMessage(f"GEE change layer failed: {exc}", "GeoAI", Qgis.Warning)
        return None


# ── Helpers ──────────────────────────────────────────────────────────

def _pull_pixels(ee, img, roi, scale: int, bands: list[str]) -> Optional[dict[str, np.ndarray]]:
    """
    Pull pixel data as numpy arrays for a small ROI.
    Uses getRegion() which returns a flat list — fast for POC extents.
    """
    try:
        data = img.select(bands).getRegion(roi, scale).getInfo()
        header = data[0]   # ["longitude","latitude","time", band1, band2, ...]
        rows = data[1:]

        lons = [r[0] for r in rows]
        lats = [r[1] for r in rows]

        unique_lons = sorted(set(lons))
        unique_lats = sorted(set(lats), reverse=True)
        W, H = len(unique_lons), len(unique_lats)

        lon_idx = {v: i for i, v in enumerate(unique_lons)}
        lat_idx = {v: i for i, v in enumerate(unique_lats)}

        result = {}
        for b_idx, band in enumerate(bands):
            col_idx = header.index(band)
            arr = np.full((H, W), np.nan, dtype=np.float32)
            for r, lon, lat in zip(rows, lons, lats):
                arr[lat_idx[lat], lon_idx[lon]] = r[col_idx] if r[col_idx] is not None else np.nan
            result[band] = arr

        return result

    except Exception as exc:
        QgsMessageLog.logMessage(f"GEE pixel pull failed (ROI may be too large): {exc}", "GeoAI", Qgis.Warning)
        return None


def _save_to_geotiff(
    array: np.ndarray,
    bbox: list[float],
    name: str,
    bands: int = 1,
) -> str:
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.crs import CRS

    if array.ndim == 2:
        H, W = array.shape
        n_bands = 1
    else:
        n_bands, H, W = array.shape

    transform = from_bounds(bbox[0], bbox[1], bbox[2], bbox[3], W, H)
    tmp = tempfile.NamedTemporaryFile(suffix=f"_{name}.tif", delete=False)
    tmp.close()

    with rasterio.open(
        tmp.name, "w", driver="GTiff",
        height=H, width=W, count=n_bands,
        dtype="float32", crs=CRS.from_epsg(4326), transform=transform,
    ) as dst:
        if array.ndim == 2:
            dst.write(array.astype(np.float32), 1)
        else:
            for i, b in enumerate(array, 1):
                dst.write(b.astype(np.float32), i)

    return tmp.name


def _pca_to_rgb(stack: np.ndarray) -> np.ndarray:
    """Reduce [bands, H, W] to [3, H, W] via PCA for RGB false-colour display."""
    n, H, W = stack.shape
    X = stack.reshape(n, -1).T  # [pixels, bands]
    valid_mask = ~np.any(np.isnan(X), axis=1)
    X_valid = X[valid_mask]

    mean = X_valid.mean(axis=0)
    X_c = X_valid - mean
    cov = np.cov(X_c.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    top3 = eigvecs[:, -3:]  # top 3 principal components

    proj = X_c @ top3  # [valid_pixels, 3]

    result = np.full((H * W, 3), np.nan, dtype=np.float32)
    result[valid_mask] = proj

    rgb = result.T.reshape(3, H, W)
    # Normalise each component to [0, 1] for display
    for i in range(3):
        ch = rgb[i]
        vmin, vmax = np.nanmin(ch), np.nanmax(ch)
        rgb[i] = (ch - vmin) / (vmax - vmin + 1e-8)

    return rgb

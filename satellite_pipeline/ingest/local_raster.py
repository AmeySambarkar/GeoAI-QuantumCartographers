"""
Local GeoTIFF inspection and band-math using rasterio.
Replicates the GDAL MCP raster_info / raster_stats / band_math workflow.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class RasterInfo:
    path: str
    sensor_type: str       # "LISS4" | "HLS" | "DEM" | "PAN" | "UNKNOWN"
    band_count: int
    width: int
    height: int
    crs: str
    transform: list[float]
    dtype: str
    nodata: Optional[float]
    extent: dict           # {west, south, east, north}
    resolution_m: float


@dataclass
class SpectralStats:
    ndvi_mean: float
    ndvi_std: float
    evi_mean: Optional[float]
    mndwi_mean: Optional[float]
    ndwi_mean: Optional[float]
    water_fraction: float  # fraction of pixels with NDWI > 0
    vegetation_fraction: float  # fraction with NDVI > 0.3


@dataclass
class DEMStats:
    elev_min: float
    elev_max: float
    elev_mean: float
    slope_mean: float
    slope_std: float
    flat_fraction: float   # fraction with slope < 2°


def _sensor_type(band_count: int, nodata: Optional[float], dtype: str) -> str:
    if band_count == 1:
        if dtype in ("float32", "float64"):
            return "DEM"
        return "PAN"
    if band_count == 3:
        return "LISS4"
    if band_count >= 6:
        return "HLS"
    return "UNKNOWN"


def inspect_raster(path: str | Path) -> RasterInfo:
    """Return metadata for any GeoTIFF — equivalent to GDAL MCP raster_info."""
    try:
        import rasterio
        from rasterio.crs import CRS
    except ImportError:
        raise ImportError("rasterio is required: pip install rasterio")

    path = str(path)
    with rasterio.open(path) as src:
        bounds = src.bounds
        res_m = abs(src.transform.a)
        # Rough metres from degrees (at equator ~111 km/deg)
        if src.crs and src.crs.is_geographic:
            res_m = abs(src.transform.a) * 111_320

        info = RasterInfo(
            path=path,
            sensor_type=_sensor_type(src.count, src.nodata, src.dtypes[0]),
            band_count=src.count,
            width=src.width,
            height=src.height,
            crs=str(src.crs),
            transform=list(src.transform),
            dtype=src.dtypes[0],
            nodata=src.nodata,
            extent={
                "west": bounds.left,
                "south": bounds.bottom,
                "east": bounds.right,
                "north": bounds.top,
            },
            resolution_m=round(res_m, 2),
        )

    logger.info("Inspected %s: %s bands, %s, %.1fm", path, info.band_count, info.sensor_type, info.resolution_m)
    return info


def read_bands(path: str | Path, indices: list[int] | None = None) -> tuple[np.ndarray, dict]:
    """Read bands (1-indexed) as float32 array [bands, H, W]. Returns (array, profile)."""
    import rasterio

    with rasterio.open(path) as src:
        profile = src.profile.copy()
        if indices is None:
            data = src.read().astype(np.float32)
        else:
            data = src.read(indices).astype(np.float32)
        nodata = src.nodata

    if nodata is not None:
        data = np.where(data == nodata, np.nan, data)

    return data, profile


def compute_spectral_stats(path: str | Path, info: RasterInfo) -> SpectralStats:
    """
    Compute NDVI/EVI/MNDWI from local file.
    Band assignment by sensor type:
      LISS4 (3-band): [Green, Red, NIR]
      HLS   (6-band): [Blue, Green, Red, NIR_Narrow, SWIR1, SWIR2]
    """
    data, _ = read_bands(path)

    if info.sensor_type == "LISS4" and info.band_count >= 3:
        green, red, nir = data[0], data[1], data[2]
        swir1 = None
    elif info.sensor_type == "HLS" and info.band_count >= 6:
        _, green, red, nir, swir1, _ = data[0], data[1], data[2], data[3], data[4], data[5]
    else:
        logger.warning("Cannot compute spectral stats for sensor type %s", info.sensor_type)
        return SpectralStats(0, 0, None, None, None, 0, 0)

    # Normalise reflectance to 0-1 if values suggest DN scale
    max_val = np.nanmax(data)
    if max_val > 10:
        data = data / 10_000.0
        green, red, nir = green / 10_000, red / 10_000, nir / 10_000
        if swir1 is not None:
            swir1 = swir1 / 10_000

    ndvi = _safe_ratio(nir - red, nir + red)
    evi_mean = float(np.nanmean(2.5 * _safe_ratio(nir - red, nir + 6 * red - 7.5 * data[0] / (max_val or 1) + 1))) if info.band_count >= 6 else None
    mndwi_mean = float(np.nanmean(_safe_ratio(green - swir1, green + swir1))) if swir1 is not None else None
    ndwi = _safe_ratio(green - nir, green + nir)

    return SpectralStats(
        ndvi_mean=round(float(np.nanmean(ndvi)), 4),
        ndvi_std=round(float(np.nanstd(ndvi)), 4),
        evi_mean=round(evi_mean, 4) if evi_mean is not None else None,
        mndwi_mean=round(mndwi_mean, 4) if mndwi_mean is not None else None,
        ndwi_mean=round(float(np.nanmean(ndwi)), 4),
        water_fraction=round(float(np.nanmean(ndwi > 0)), 4),
        vegetation_fraction=round(float(np.nanmean(ndvi > 0.3)), 4),
    )


def compute_dem_stats(path: str | Path) -> DEMStats:
    """Compute elevation and slope statistics from a DEM GeoTIFF."""
    import rasterio
    from rasterio.transform import from_bounds

    data, profile = read_bands(path)
    elev = data[0]

    with rasterio.open(path) as src:
        res_x = abs(src.transform.a)
        res_y = abs(src.transform.e)
        if src.crs and src.crs.is_geographic:
            res_x *= 111_320
            res_y *= 111_320

    # Gradient-based slope in degrees
    dy, dx = np.gradient(np.where(np.isnan(elev), 0, elev), res_y, res_x)
    slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
    slope_deg = np.degrees(slope_rad)

    valid = ~np.isnan(elev)
    return DEMStats(
        elev_min=round(float(np.nanmin(elev)), 2),
        elev_max=round(float(np.nanmax(elev)), 2),
        elev_mean=round(float(np.nanmean(elev)), 2),
        slope_mean=round(float(np.mean(slope_deg[valid])), 3),
        slope_std=round(float(np.std(slope_deg[valid])), 3),
        flat_fraction=round(float(np.mean(slope_deg[valid] < 2.0)), 4),
    )


def _safe_ratio(num: np.ndarray, denom: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        result = np.where(np.abs(denom) > 1e-6, num / denom, np.nan)
    return np.clip(result, -1, 1)


def write_geotiff(path: str | Path, array: np.ndarray, profile: dict) -> None:
    """Write a float32 array to GeoTIFF."""
    import rasterio

    profile = profile.copy()
    profile.update(dtype="float32", count=array.shape[0] if array.ndim == 3 else 1)
    with rasterio.open(path, "w", **profile) as dst:
        if array.ndim == 2:
            dst.write(array.astype(np.float32), 1)
        else:
            for i, band in enumerate(array, 1):
                dst.write(band.astype(np.float32), i)
    logger.info("Written %s", path)

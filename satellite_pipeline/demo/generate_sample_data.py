"""
Generates synthetic but physically realistic GeoTIFFs for pipeline demonstration.
No real satellite data required — the pipeline runs end-to-end immediately.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Maharashtra semi-arid typical reflectance values (DN × 10,000)
_LISS4_PARAMS = {
    "green": {"base": 1200, "var": 200, "texture_scale": 0.15},
    "red":   {"base": 1800, "var": 300, "texture_scale": 0.20},
    "nir":   {"base": 4200, "var": 600, "texture_scale": 0.25},
}

_HLS_PARAMS = {
    "blue":  {"base": 800,  "var": 120},
    "green": {"base": 1100, "var": 180},
    "red":   {"base": 1600, "var": 280},
    "nir":   {"base": 3800, "var": 550},
    "swir1": {"base": 2100, "var": 320},
    "swir2": {"base": 1400, "var": 240},
}


def _perlin_noise(H: int, W: int, scale: float = 0.1, rng=None) -> np.ndarray:
    """Simple sum-of-sines spatial texture to mimic landscape heterogeneity."""
    if rng is None:
        rng = np.random.default_rng(42)
    x = np.linspace(0, 2 * np.pi * scale * W, W)
    y = np.linspace(0, 2 * np.pi * scale * H, H)
    X, Y = np.meshgrid(x, y)
    noise = (np.sin(X) * np.cos(Y) + 0.5 * np.sin(2*X) * np.cos(0.5*Y) +
             0.25 * rng.normal(0, 1, (H, W)))
    noise = (noise - noise.min()) / (noise.max() - noise.min() + 1e-8)
    return noise.astype(np.float32)


def _add_water_bodies(band: np.ndarray, nir: np.ndarray, noise: np.ndarray,
                      water_threshold: float = 0.15) -> np.ndarray:
    """Suppress NIR in water-body pixels (low noise regions → lakes)."""
    water_mask = noise < water_threshold
    result = band.copy()
    result[water_mask] = band[water_mask] * 0.3  # water absorbs NIR
    return result


def generate_liss4(output_path: str | Path, H: int = 256, W: int = 256,
                   roi_bbox: list[float] | None = None) -> Path:
    """Create a 3-band LISS-4 style GeoTIFF [Green, Red, NIR] at ~5.8m resolution."""
    try:
        import rasterio
        from rasterio.crs import CRS
        from rasterio.transform import from_bounds
    except ImportError:
        raise ImportError("rasterio required: pip install rasterio")

    if roi_bbox is None:
        roi_bbox = [73.0, 18.5, 73.5, 19.0]

    rng = np.random.default_rng(seed=100)
    noise = _perlin_noise(H, W, scale=0.08, rng=rng)

    bands = []
    for name, params in _LISS4_PARAMS.items():
        band = (params["base"] + params["var"] * noise + rng.normal(0, 50, (H, W))).astype(np.float32)
        if name == "nir":
            band = _add_water_bodies(band, band, noise)
        bands.append(np.clip(band, 200, 10_000))

    transform = from_bounds(*roi_bbox, W, H)
    crs = CRS.from_epsg(4326)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", driver="GTiff", height=H, width=W,
                       count=3, dtype="float32", crs=crs, transform=transform) as dst:
        for i, band in enumerate(bands, 1):
            dst.write(band, i)

    logger.info("LISS-4 sample written: %s  [%d×%d, 3 bands]", output_path, H, W)
    return output_path


def generate_hls(output_path: str | Path, H: int = 256, W: int = 256,
                 roi_bbox: list[float] | None = None, year: int = 2024) -> Path:
    """Create a 6-band HLS-style GeoTIFF [B,G,R,NIR,SWIR1,SWIR2] at 30m."""
    try:
        import rasterio
        from rasterio.crs import CRS
        from rasterio.transform import from_bounds
    except ImportError:
        raise ImportError("rasterio required: pip install rasterio")

    if roi_bbox is None:
        roi_bbox = [73.0, 18.5, 73.5, 19.0]

    seed = year % 1000  # different noise for different years → change detection
    rng = np.random.default_rng(seed=seed)
    noise = _perlin_noise(H, W, scale=0.06, rng=rng)

    # Slight drought shift in older years (lower NIR = less vegetation)
    drought_factor = 0.88 if year < 2022 else 1.0

    bands = []
    for name, params in _HLS_PARAMS.items():
        scale = drought_factor if name == "nir" else 1.0
        band = (params["base"] * scale + params["var"] * noise + rng.normal(0, 40, (H, W))).astype(np.float32)
        if name == "nir":
            band = _add_water_bodies(band, band, noise, water_threshold=0.12)
        bands.append(np.clip(band, 100, 10_000))

    transform = from_bounds(*roi_bbox, W, H)
    crs = CRS.from_epsg(4326)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", driver="GTiff", height=H, width=W,
                       count=6, dtype="float32", crs=crs, transform=transform) as dst:
        for i, band in enumerate(bands, 1):
            dst.write(band, i)

    logger.info("HLS sample written: %s  [%d×%d, 6 bands, year=%d]", output_path, H, W, year)
    return output_path


def generate_dem(output_path: str | Path, H: int = 256, W: int = 256,
                 roi_bbox: list[float] | None = None,
                 elev_range: tuple[float, float] = (480, 720)) -> Path:
    """Create a synthetic DEM GeoTIFF (single band, float32, metres)."""
    try:
        import rasterio
        from rasterio.crs import CRS
        from rasterio.transform import from_bounds
    except ImportError:
        raise ImportError("rasterio required: pip install rasterio")

    if roi_bbox is None:
        roi_bbox = [73.0, 18.5, 73.5, 19.0]

    rng = np.random.default_rng(seed=77)
    # Smooth elevation surface + micro-topography
    macro = _perlin_noise(H, W, scale=0.03, rng=rng)
    micro = _perlin_noise(H, W, scale=0.18, rng=rng) * 0.15
    elev = (macro + micro)
    lo, hi = elev_range
    elev = (lo + (hi - lo) * (elev - elev.min()) / (elev.max() - elev.min() + 1e-8)).astype(np.float32)

    transform = from_bounds(*roi_bbox, W, H)
    crs = CRS.from_epsg(4326)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", driver="GTiff", height=H, width=W,
                       count=1, dtype="float32", crs=crs, transform=transform) as dst:
        dst.write(elev, 1)

    logger.info("DEM sample written: %s  [%d×%d, elev %.0f–%.0fm]", output_path, H, W, lo, hi)
    return output_path


def generate_all(base_dir: str | Path = "workspace/input",
                 roi_bbox: list[float] | None = None) -> dict[str, Path]:
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    if roi_bbox is None:
        roi_bbox = [73.0, 18.5, 73.5, 19.0]

    return {
        "liss4": generate_liss4(base_dir / "LISS4_sample.tif", roi_bbox=roi_bbox),
        "hls_baseline": generate_hls(base_dir / "HLS_2018.tif", roi_bbox=roi_bbox, year=2018),
        "hls_analysis": generate_hls(base_dir / "HLS_2024.tif", roi_bbox=roi_bbox, year=2024),
        "dem": generate_dem(base_dir / "DEM_sample.tif", roi_bbox=roi_bbox),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Generate synthetic GeoTIFFs for pipeline demo")
    parser.add_argument("--out", default="workspace/input")
    args = parser.parse_args()
    paths = generate_all(args.out)
    for name, path in paths.items():
        print(f"  {name:<20} {path}")

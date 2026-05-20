"""
Feature aggregator — merges all sensor sources into a single structured JSON.
This is the 'in-memory feature JSON' that feeds the Claude reasoning layer.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class AggregatedFeatures:
    run_id: str
    timestamp: str
    roi: dict
    baseline_year: int
    analysis_year: int

    # Local raster results
    local_rasters: list[dict]
    has_dem: bool
    dem_stats: Optional[dict]
    local_spectral: Optional[dict]

    # GEE results
    gee: dict

    # Maxar catalog
    maxar: dict

    # Change detection
    change: dict

    # Prithvi-style anomaly score
    anomaly_score: Optional[float]

    # Summary metrics (flat, for easy Claude consumption)
    summary: dict


def build_features(
    config,
    local_raster_infos: list,
    local_spectral_stats: Optional[Any],
    dem_stats: Optional[Any],
    gee_result: Any,
    maxar_result: Any,
    change_stats: Optional[dict],
    anomaly_score: Optional[float],
) -> AggregatedFeatures:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    roi = asdict(config.roi)

    local_rasters = []
    for info in local_raster_infos:
        local_rasters.append({
            "path": info.path,
            "sensor_type": info.sensor_type,
            "band_count": info.band_count,
            "resolution_m": info.resolution_m,
            "crs": info.crs,
            "extent": info.extent,
        })

    local_spec = None
    if local_spectral_stats:
        from dataclasses import asdict as _asdict
        local_spec = {k: v for k, v in _asdict(local_spectral_stats).items() if v is not None}

    dem_d = None
    if dem_stats:
        from dataclasses import asdict as _asdict
        dem_d = _asdict(dem_stats)

    gee_d = {
        "ndvi_mean": gee_result.ndvi_mean,
        "ndwi_mean": gee_result.ndwi_mean,
        "evi_mean": gee_result.evi_mean,
        "embedding_cosine_change": gee_result.embedding_cosine_change,
        "baseline_ndvi": gee_result.baseline_ndvi,
        "analysis_ndvi": gee_result.analysis_ndvi,
        "ndvi_change": gee_result.ndvi_change,
        "water_area_km2": gee_result.water_area_km2,
        "source": gee_result.source,
    }

    maxar_d = {
        "total_scenes": maxar_result.total_scenes,
        "source": maxar_result.source,
        "best_scene": None,
    }
    if maxar_result.best_scene:
        bs = maxar_result.best_scene
        maxar_d["best_scene"] = {
            "scene_id": bs.scene_id,
            "datetime": bs.datetime,
            "cloud_cover_pct": bs.cloud_cover,
            "resolution_m": bs.resolution_m,
            "sensor": bs.sensor,
        }

    # Build flat summary for easy LLM consumption
    ndvi_primary = (local_spec or {}).get("ndvi_mean") or gee_result.ndvi_mean
    summary = {
        "ndvi_primary": round(ndvi_primary, 4),
        "ndvi_gee": gee_result.ndvi_mean,
        "ndvi_change_2018_2024": gee_result.ndvi_change,
        "ndwi_mean": gee_result.ndwi_mean,
        "evi_mean": gee_result.evi_mean,
        "water_area_km2": gee_result.water_area_km2,
        "embedding_change_intensity": gee_result.embedding_cosine_change,
        "dem_slope_mean_deg": dem_d["slope_mean"] if dem_d else None,
        "dem_elev_range_m": (dem_d["elev_max"] - dem_d["elev_min"]) if dem_d else None,
        "flat_fraction": dem_d["flat_fraction"] if dem_d else None,
        "maxar_scenes_available": maxar_result.total_scenes,
        "change_intensity": (change_stats or {}).get("change_intensity"),
        "vegetation_loss_fraction": (change_stats or {}).get("loss_fraction"),
        "vegetation_gain_fraction": (change_stats or {}).get("gain_fraction"),
        "anomaly_score": anomaly_score,
        "data_sources": ["GEE-Sentinel2", "GEE-SatelliteEmbeddings", "Maxar-STAC"]
            + (["Local-Multispectral"] if local_spec else [])
            + (["Local-DEM"] if dem_d else []),
    }

    return AggregatedFeatures(
        run_id=run_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        roi=roi,
        baseline_year=config.baseline_year,
        analysis_year=config.analysis_year,
        local_rasters=local_rasters,
        has_dem=dem_d is not None,
        dem_stats=dem_d,
        local_spectral=local_spec,
        gee=gee_d,
        maxar=maxar_d,
        change=change_stats or {},
        anomaly_score=anomaly_score,
        summary=summary,
    )


def to_json(features: AggregatedFeatures, path: Optional[Path] = None) -> str:
    from dataclasses import asdict
    data = asdict(features)
    text = json.dumps(data, indent=2, default=str)
    if path:
        Path(path).write_text(text)
        logger.info("Feature JSON written to %s", path)
    return text

"""
Maxar Geospatial Platform (MGP) client.
Uses the STAC Discovery API and Streaming Basemap endpoints.
Degrades gracefully to simulated metadata when no API key is set.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

MAXAR_STAC_URL = "https://api.maxar.com/discovery/v1/stac/search"
MAXAR_WMS_URL = "https://api.maxar.com/streaming/v1/ogc/wms"


@dataclass
class MaxarScene:
    scene_id: str
    datetime: str
    cloud_cover: float
    off_nadir: float
    resolution_m: float
    sensor: str
    collection: str
    bbox: list[float]
    download_url: Optional[str]
    thumbnail_url: Optional[str]


@dataclass
class MaxarSearchResult:
    scenes: list[MaxarScene]
    total_scenes: int
    best_scene: Optional[MaxarScene]
    source: str  # "MAXAR_API" | "SIMULATED"


def _build_stac_payload(roi_bbox: list[float], start_date: str, end_date: str, limit: int = 10) -> dict:
    return {
        "bbox": roi_bbox,
        "datetime": f"{start_date}T00:00:00Z/{end_date}T23:59:59Z",
        "collections": ["wv04-natgeo", "wv03-natgeo", "wv02-natgeo", "ge01-natgeo"],
        "limit": limit,
        "filter": {
            "op": "and",
            "args": [
                {"op": "<=", "args": [{"property": "view:off_nadir"}, 30]},
                {"op": "<=", "args": [{"property": "eo:cloud_cover"}, 20]},
            ],
        },
        "filter-lang": "cql2-json",
        "sortby": [{"field": "datetime", "direction": "desc"}],
    }


def search_maxar_imagery(config) -> MaxarSearchResult:
    """
    Search Maxar catalog for high-resolution imagery over the ROI.
    Returns MaxarSearchResult with discovered scenes.
    """
    if not config.has_maxar:
        logger.info("No MAXAR_API_KEY — returning simulated scene catalog")
        return _simulate_scenes(config.roi)

    try:
        import requests

        roi = config.roi
        start = f"{config.baseline_year}-01-01"
        end = f"{config.analysis_year}-12-31"
        payload = _build_stac_payload(roi.bbox, start, end)
        headers = {
            "Authorization": f"Bearer {config.maxar_api_key}",
            "Content-Type": "application/json",
        }

        resp = requests.post(MAXAR_STAC_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        scenes = []
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            assets = feature.get("assets", {})
            scenes.append(MaxarScene(
                scene_id=feature.get("id", ""),
                datetime=props.get("datetime", ""),
                cloud_cover=props.get("eo:cloud_cover", 0),
                off_nadir=props.get("view:off_nadir", 0),
                resolution_m=props.get("gsd", 0.5),
                sensor=props.get("platform", "UNKNOWN"),
                collection=feature.get("collection", ""),
                bbox=feature.get("bbox", []),
                download_url=assets.get("data", {}).get("href"),
                thumbnail_url=assets.get("thumbnail", {}).get("href"),
            ))

        best = min(scenes, key=lambda s: s.cloud_cover) if scenes else None
        logger.info("Maxar search: %d scenes found, best cloud cover %.1f%%",
                    len(scenes), best.cloud_cover if best else 0)

        return MaxarSearchResult(
            scenes=scenes,
            total_scenes=data.get("context", {}).get("returned", len(scenes)),
            best_scene=best,
            source="MAXAR_API",
        )

    except Exception as exc:
        logger.warning("Maxar API call failed (%s) — using simulated scenes", exc)
        return _simulate_scenes(config.roi)


def get_streaming_tile_url(config, zoom: int = 15) -> str:
    """
    Return a WMS GetMap URL for the Maxar Vivid streaming basemap.
    Requires a valid API key; otherwise returns a placeholder.
    """
    if not config.has_maxar:
        return (
            f"# Maxar Streaming Basemap (requires MAXAR_API_KEY)\n"
            f"# {MAXAR_WMS_URL}?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap"
            f"&LAYERS={config.maxar_basemap_collection}&FORMAT=image/jpeg"
            f"&WIDTH=256&HEIGHT=256&SRS=EPSG:3857"
        )

    bbox_mercator = _wgs84_to_mercator_bbox(config.roi.bbox)
    return (
        f"{MAXAR_WMS_URL}?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap"
        f"&LAYERS={config.maxar_basemap_collection}"
        f"&FORMAT=image%2Fjpeg&WIDTH=1024&HEIGHT=1024&SRS=EPSG%3A3857"
        f"&BBOX={','.join(str(x) for x in bbox_mercator)}"
        f"&connectid={config.maxar_api_key}"
    )


def _simulate_scenes(roi) -> MaxarSearchResult:
    """Realistic simulated Maxar catalog for demo purposes."""
    scenes = [
        MaxarScene(
            scene_id=f"10500100{i:06d}FF00",
            datetime=f"2024-0{i+1}-15T09:32:00Z",
            cloud_cover=float(i * 3.2),
            off_nadir=float(10 + i * 4),
            resolution_m=0.5,
            sensor=["WV04", "WV03", "WV02"][i % 3],
            collection=["wv04-natgeo", "wv03-natgeo", "wv02-natgeo"][i % 3],
            bbox=roi.bbox,
            download_url=None,
            thumbnail_url=None,
        )
        for i in range(5)
    ]
    best = min(scenes, key=lambda s: s.cloud_cover)
    logger.info("SIMULATED Maxar: %d scenes, best cloud %.1f%%", len(scenes), best.cloud_cover)
    return MaxarSearchResult(scenes=scenes, total_scenes=5, best_scene=best, source="SIMULATED")


def _wgs84_to_mercator_bbox(bbox: list[float]) -> list[float]:
    import math
    def lon_to_x(lon): return lon * 20037508.342789244 / 180
    def lat_to_y(lat): return math.log(math.tan((90 + lat) * math.pi / 360)) / (math.pi / 180) * 20037508.342789244 / 180
    return [lon_to_x(bbox[0]), lat_to_y(bbox[1]), lon_to_x(bbox[2]), lat_to_y(bbox[3])]

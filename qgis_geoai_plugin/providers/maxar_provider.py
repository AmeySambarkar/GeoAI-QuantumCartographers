"""
Maxar Geospatial Platform provider for QGIS.

Adds Maxar layers as:
  1. WMS raster layer (streaming basemap — Vivid / Precision)
  2. XYZ tile layer (for fast map canvas display)
  3. STAC search results as point/polygon vector layer

Authentication: Maxar uses a `connectid` query parameter for WMS/WMTS,
or a Bearer token for the MGP REST API. Both are supported here.

Maxar WMS endpoint:
  https://api.maxar.com/streaming/v1/ogc/wms
  Legacy SecureWatch: https://securewatch.digitalglobe.com/mapservice/wmsaccess

WMTS endpoint (XYZ tiles):
  https://api.maxar.com/streaming/v1/ogc/wmts/{connectid}/google3857/{z}/{x}/{y}
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from qgis.core import (
    QgsRasterLayer,
    QgsProject,
    QgsMessageLog,
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsRectangle,
    QgsField,
    QgsFields,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

logger = logging.getLogger(__name__)

# ── Maxar endpoint constants ───────────────────────────────────────────
MAXAR_WMS_URL      = "https://api.maxar.com/streaming/v1/ogc/wms"
MAXAR_WMTS_TMPL    = "https://api.maxar.com/streaming/v1/ogc/wmts/{connectid}/google3857/{z}/{x}/{y}"
MAXAR_STAC_URL     = "https://api.maxar.com/discovery/v1/stac/search"
SECUREWATCH_WMS    = "https://securewatch.digitalglobe.com/mapservice/wmsaccess"

MAXAR_WMS_LAYERS = {
    "Vivid Standard":     "Maxar:Vivid:Standard",
    "Vivid Premium":      "Maxar:Vivid:Premium",
    "Precision Monitor":  "Maxar:PrecisionMonitor",
    "Change Detection":   "Maxar:ChangeDetection",
    "SecureWatch":        "DigitalGlobe:Imagery",    # legacy
}


def add_maxar_wms_layer(
    connectid_or_bearer: str,
    layer_type: str = "Vivid Standard",
    display_name: Optional[str] = None,
    use_https: bool = True,
) -> Optional[QgsRasterLayer]:
    """
    Add a Maxar streaming WMS layer to the current QGIS project.

    Parameters
    ----------
    connectid_or_bearer : str
        Either a Maxar connectid (UUID) or a full Bearer token.
        If it looks like a Bearer token (starts with 'Bearer ' or is >40 chars
        and contains no '-' in UUID pattern), it will be passed as Authorization header.
    layer_type : str
        One of the keys in MAXAR_WMS_LAYERS.
    """
    layer_name_wms = MAXAR_WMS_LAYERS.get(layer_type, MAXAR_WMS_LAYERS["Vivid Standard"])
    display = display_name or f"Maxar {layer_type}"

    # Build WMS URI using QGIS URI syntax
    # Format: url=<WMS_URL>&format=<format>&layers=<layers>&styles=&crs=<CRS>
    # For Maxar auth: either append ?connectid=... to URL or set authcfg
    is_bearer = len(connectid_or_bearer) > 40 and "-" not in connectid_or_bearer[:8]

    if is_bearer:
        # Use QGIS auth manager (NetworkMgr injects Authorization header)
        base_url = MAXAR_WMS_URL
        # Build URI with custom header (QGIS 3.18+ supports customHeaders in WMS URI)
        uri = (
            f"url={base_url}"
            f"&format=image/jpeg"
            f"&layers={layer_name_wms}"
            f"&styles="
            f"&crs=EPSG:3857"
            f"&version=1.3.0"
            f"&IgnoreGetMapUrl=1"
            f"&customHeaderName=Authorization"
            f"&customHeaderValue=Bearer {connectid_or_bearer}"
        )
    else:
        # ConnectID appended as URL parameter
        base_url = f"{MAXAR_WMS_URL}?connectid={connectid_or_bearer}"
        uri = (
            f"url={base_url}"
            f"&format=image/jpeg"
            f"&layers={layer_name_wms}"
            f"&styles="
            f"&crs=EPSG:3857"
            f"&version=1.3.0"
            f"&IgnoreGetMapUrl=1"
        )

    layer = QgsRasterLayer(uri, display, "wms")
    if not layer.isValid():
        QgsMessageLog.logMessage(
            f"Maxar WMS layer invalid (check API key / connectid): {uri[:120]}...",
            "GeoAI", Qgis.Warning,
        )
        return None

    # Add at bottom of layer stack (basemap position)
    QgsProject.instance().addMapLayer(layer, False)
    root = QgsProject.instance().layerTreeRoot()
    root.addLayer(layer)          # adds at bottom

    QgsMessageLog.logMessage(f"Added Maxar WMS: {display}", "GeoAI", Qgis.Info)
    return layer


def add_maxar_xyz_layer(
    connectid: str,
    display_name: str = "Maxar Vivid (XYZ)",
) -> Optional[QgsRasterLayer]:
    """
    Add Maxar streaming as an XYZ tiles layer (faster than WMS for map navigation).
    Requires a connectid (not Bearer token).
    """
    tile_url = MAXAR_WMTS_TMPL.format(connectid=connectid, z="{z}", x="{x}", y="{y}")
    uri = f"type=xyz&url={tile_url}&zmin=1&zmax=20&crs=EPSG:3857"

    layer = QgsRasterLayer(uri, display_name, "wms")
    if not layer.isValid():
        QgsMessageLog.logMessage(f"Maxar XYZ layer invalid: {uri[:80]}", "GeoAI", Qgis.Warning)
        return None

    QgsProject.instance().addMapLayer(layer, False)
    root = QgsProject.instance().layerTreeRoot()
    root.addLayer(layer)
    QgsMessageLog.logMessage(f"Added Maxar XYZ tiles: {display_name}", "GeoAI", Qgis.Info)
    return layer


def search_maxar_stac(
    bearer_token: str,
    bbox: list[float],
    start_date: str,
    end_date: str,
    cloud_max: int = 20,
    off_nadir_max: int = 30,
    limit: int = 20,
) -> Optional[QgsVectorLayer]:
    """
    Search Maxar MGP STAC catalog and return results as a QGIS vector layer
    with scene footprints as polygons and metadata as attributes.

    Parameters
    ----------
    bbox : [west, south, east, north]
    """
    try:
        import requests
    except ImportError:
        QgsMessageLog.logMessage("requests not installed", "GeoAI", Qgis.Warning)
        return None

    payload = {
        "bbox": bbox,
        "datetime": f"{start_date}T00:00:00Z/{end_date}T23:59:59Z",
        "collections": ["wv04-natgeo", "wv03-natgeo", "wv02-natgeo", "ge01-natgeo"],
        "limit": limit,
        "filter": {
            "op": "and",
            "args": [
                {"op": "<=", "args": [{"property": "eo:cloud_cover"}, cloud_max]},
                {"op": "<=", "args": [{"property": "view:off_nadir"}, off_nadir_max]},
            ],
        },
        "filter-lang": "cql2-json",
        "sortby": [{"field": "datetime", "direction": "desc"}],
    }

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(MAXAR_STAC_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        features = resp.json().get("features", [])
    except Exception as exc:
        QgsMessageLog.logMessage(f"Maxar STAC search failed: {exc}", "GeoAI", Qgis.Warning)
        return None

    if not features:
        QgsMessageLog.logMessage("Maxar STAC: no scenes found for the given criteria", "GeoAI", Qgis.Info)
        return None

    return _stac_features_to_layer(features)


def _stac_features_to_layer(features: list[dict]) -> QgsVectorLayer:
    """Convert STAC feature list to a styled polygon vector layer."""
    fields = QgsFields()
    for fname, ftype in [
        ("scene_id",    QVariant.String),
        ("datetime",    QVariant.String),
        ("cloud_cover", QVariant.Double),
        ("off_nadir",   QVariant.Double),
        ("resolution",  QVariant.Double),
        ("sensor",      QVariant.String),
        ("collection",  QVariant.String),
    ]:
        fields.append(QgsField(fname, ftype))

    layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "Maxar STAC Scenes", "memory")
    provider = layer.dataProvider()
    provider.addAttributes(fields)
    layer.updateFields()

    qfeatures = []
    for feat in features:
        props = feat.get("properties", {})
        geom_data = feat.get("geometry", {})
        bbox = feat.get("bbox", [])

        if geom_data.get("type") == "Polygon":
            coords = geom_data["coordinates"][0]
            wkt = "POLYGON((" + ", ".join(f"{x} {y}" for x, y in coords) + "))"
            geom = QgsGeometry.fromWkt(wkt)
        elif bbox:
            geom = QgsGeometry.fromRect(
                QgsRectangle(bbox[0], bbox[1], bbox[2], bbox[3])
            )
        else:
            continue

        qf = QgsFeature(fields)
        qf.setGeometry(geom)
        qf.setAttributes([
            feat.get("id", ""),
            props.get("datetime", ""),
            props.get("eo:cloud_cover", None),
            props.get("view:off_nadir", None),
            props.get("gsd", None),
            props.get("platform", ""),
            feat.get("collection", ""),
        ])
        qfeatures.append(qf)

    provider.addFeatures(qfeatures)
    layer.updateExtents()

    # Style: semi-transparent outline only (so basemap shows through)
    from qgis.core import QgsFillSymbol, QgsSimpleFillSymbolLayer
    symbol = QgsFillSymbol.createSimple({
        "color": "0,0,255,30",           # very transparent blue fill
        "outline_color": "0,0,200,200",  # solid blue border
        "outline_width": "0.5",
    })
    layer.renderer().setSymbol(symbol)

    QgsProject.instance().addMapLayer(layer)
    QgsMessageLog.logMessage(
        f"Maxar STAC: added {len(qfeatures)} scene footprints", "GeoAI", Qgis.Info
    )
    return layer

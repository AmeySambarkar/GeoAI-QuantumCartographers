"""
QGIS layer management — add, style, group, and update raster/vector layers.
All operations go through this module to keep the rest of the plugin clean.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np

from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsLayerTree,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsMessageLog,
    Qgis,
    QgsRasterDataProvider,
    QgsRasterBandStats,
    QgsCoordinateReferenceSystem,
)
from qgis.PyQt.QtWidgets import QApplication

from .symbology import apply_index_style

logger = logging.getLogger(__name__)
PLUGIN_GROUP = "GeoAI Layers"


def _get_or_create_group(name: str = PLUGIN_GROUP) -> QgsLayerTreeGroup:
    root = QgsProject.instance().layerTreeRoot()
    group = root.findGroup(name)
    if group is None:
        group = root.insertGroup(0, name)
    return group


def _array_to_temp_raster(
    array: np.ndarray,
    reference_layer: QgsRasterLayer,
    name: str,
) -> str:
    """Write a numpy array to a temp GeoTIFF using the reference layer's CRS/transform."""
    try:
        import rasterio
        from rasterio.transform import from_bounds
        from rasterio.crs import CRS as RioCRS
    except ImportError:
        raise ImportError("rasterio required: pip install rasterio")

    ext = reference_layer.extent()
    crs_str = reference_layer.crs().toWkt()
    H, W = array.shape[-2], array.shape[-1]

    transform = from_bounds(ext.xMinimum(), ext.yMinimum(),
                             ext.xMaximum(), ext.yMaximum(), W, H)

    tmpfile = tempfile.NamedTemporaryFile(suffix=f"_{name}.tif", delete=False)
    tmpfile.close()

    count = 1 if array.ndim == 2 else array.shape[0]
    with rasterio.open(
        tmpfile.name, "w",
        driver="GTiff", height=H, width=W,
        count=count, dtype="float32",
        crs=rasterio.crs.CRS.from_wkt(crs_str),
        transform=transform,
    ) as dst:
        if array.ndim == 2:
            dst.write(array.astype(np.float32), 1)
            dst.update_tags(1, DESCRIPTION=name)
        else:
            for i, band in enumerate(array, 1):
                dst.write(band.astype(np.float32), i)

    return tmpfile.name


def add_raster_layer(
    path: str,
    display_name: str,
    index_style: Optional[str] = None,
    group: Optional[QgsLayerTreeGroup] = None,
    replace_existing: bool = True,
) -> Optional[QgsRasterLayer]:
    """
    Add a GeoTIFF to the QGIS project under the GeoAI group.
    If index_style is set (e.g. 'NDVI'), applies the matching colormap.
    Returns the layer or None on failure.
    """
    if replace_existing:
        _remove_layer_by_name(display_name)

    layer = QgsRasterLayer(path, display_name)
    if not layer.isValid():
        QgsMessageLog.logMessage(f"Invalid layer: {path}", "GeoAI", Qgis.Warning)
        return None

    if index_style:
        apply_index_style(layer, index_style)

    QgsProject.instance().addMapLayer(layer, False)
    target_group = group or _get_or_create_group()
    target_group.insertLayer(0, layer)

    QgsMessageLog.logMessage(f"Added layer: {display_name}", "GeoAI", Qgis.Info)
    return layer


def add_index_layer_from_array(
    array: np.ndarray,
    reference_layer: QgsRasterLayer,
    index_name: str,
    display_name: Optional[str] = None,
) -> Optional[QgsRasterLayer]:
    """
    Write array to temp GeoTIFF, add as styled layer.
    Used after computing NDVI/EVI/change etc. in-memory.
    """
    display_name = display_name or index_name
    tmp_path = _array_to_temp_raster(array, reference_layer, index_name)
    return add_raster_layer(tmp_path, display_name, index_style=index_name)


def get_layer_array(layer: QgsRasterLayer, band: int = 1) -> np.ndarray:
    """Read a single band from a QGIS raster layer as float32 numpy array."""
    try:
        import rasterio
    except ImportError:
        raise ImportError("rasterio required")

    src_path = layer.dataProvider().dataSourceUri()
    with rasterio.open(src_path) as src:
        data = src.read(band).astype(np.float32)
        nodata = src.nodata
    if nodata is not None:
        data = np.where(data == nodata, np.nan, data)
    return data


def get_layer_bands(layer: QgsRasterLayer) -> np.ndarray:
    """Read all bands from a QGIS raster layer as float32 [bands, H, W]."""
    try:
        import rasterio
    except ImportError:
        raise ImportError("rasterio required")

    src_path = layer.dataProvider().dataSourceUri()
    with rasterio.open(src_path) as src:
        data = src.read().astype(np.float32)
        nodata = src.nodata
    if nodata is not None:
        data = np.where(data == nodata, np.nan, data)
    return data


def get_selected_raster_layer() -> Optional[QgsRasterLayer]:
    """Return the currently selected layer in the Layers panel if it's a raster."""
    layers = QgsProject.instance().mapLayersByName
    from qgis.utils import iface
    layer = iface.activeLayer()
    if isinstance(layer, QgsRasterLayer):
        return layer
    return None


def list_raster_layers() -> list[tuple[str, QgsRasterLayer]]:
    """Return all raster layers currently in the project as (name, layer) pairs."""
    return [
        (lyr.name(), lyr)
        for lyr in QgsProject.instance().mapLayers().values()
        if isinstance(lyr, QgsRasterLayer)
    ]


def set_layer_opacity(layer: QgsRasterLayer, opacity: float) -> None:
    """Set layer opacity (0.0 fully transparent, 1.0 fully opaque)."""
    layer.setOpacity(opacity)
    layer.triggerRepaint()


def _remove_layer_by_name(name: str) -> None:
    for lyr in QgsProject.instance().mapLayers().values():
        if lyr.name() == name:
            QgsProject.instance().removeMapLayer(lyr.id())
            return


def zoom_to_layer(layer: QgsRasterLayer) -> None:
    from qgis.utils import iface
    iface.mapCanvas().setExtent(layer.extent())
    iface.mapCanvas().refresh()

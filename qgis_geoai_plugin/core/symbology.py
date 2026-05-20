"""
Spectral index and change-detection colormaps for QGIS raster layers.
All functions return a configured QgsRasterRenderer ready to apply to a QgsRasterLayer.
"""
from __future__ import annotations

from qgis.core import (
    QgsColorRampShader,
    QgsRasterLayer,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
    QgsContrastEnhancement,
    QgsRasterMinMaxOrigin,
)
from qgis.PyQt.QtGui import QColor


def _make_renderer(
    layer: QgsRasterLayer,
    band: int,
    stops: list[tuple[float, str, str]],  # (value, hex_color, label)
    min_val: float = -1.0,
    max_val: float = 1.0,
    interp: int = QgsColorRampShader.Interpolated,
) -> QgsSingleBandPseudoColorRenderer:
    shader_fn = QgsColorRampShader(min_val, max_val)
    shader_fn.setColorRampType(interp)
    shader_fn.setClassificationMode(QgsColorRampShader.Continuous)
    shader_fn.setColorRampItemList([
        QgsColorRampShader.ColorRampItem(v, QColor(c), lbl)
        for v, c, lbl in stops
    ])
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(shader_fn)
    renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), band, shader)
    return renderer


# ── Index-specific colour schemes ─────────────────────────────────────

def ndvi_renderer(layer: QgsRasterLayer, band: int = 1) -> QgsSingleBandPseudoColorRenderer:
    """NDVI: brown (bare/stressed) → yellow (sparse) → dark green (dense vegetation)."""
    stops = [
        (-1.0,  "#7f4f24", "Water / Built"),
        (-0.05, "#c9a84c", "Bare soil"),
        (0.10,  "#ffffcc", "Sparse / dry"),
        (0.25,  "#a8d08d", "Moderate"),
        (0.50,  "#4caf50", "Healthy"),
        (0.75,  "#1b5e20", "Dense"),
        (1.00,  "#003300", "Max vegetation"),
    ]
    return _make_renderer(layer, band, stops, -1.0, 1.0)


def ndwi_renderer(layer: QgsRasterLayer, band: int = 1) -> QgsSingleBandPseudoColorRenderer:
    """NDWI: brown (dry land) → white (transition) → blue (water body)."""
    stops = [
        (-1.0, "#8b4513", "Dry land"),
        (-0.2, "#d2b48c", "Dry/semi-arid"),
        (0.00, "#f5f5dc", "Transition"),
        (0.20, "#87ceeb", "Wet / moist"),
        (0.50, "#1565c0", "Open water"),
        (1.00, "#01579b", "Deep water"),
    ]
    return _make_renderer(layer, band, stops, -1.0, 1.0)


def evi_renderer(layer: QgsRasterLayer, band: int = 1) -> QgsSingleBandPseudoColorRenderer:
    """EVI: grey (low) → lime (moderate) → forest green (high)."""
    stops = [
        (-0.2, "#b0bec5", "Non-vegetated"),
        (0.10, "#dcedc8", "Sparse"),
        (0.25, "#8bc34a", "Moderate"),
        (0.45, "#33691e", "Dense"),
        (0.80, "#1b5e20", "Max"),
    ]
    return _make_renderer(layer, band, stops, -0.2, 0.8)


def mndwi_renderer(layer: QgsRasterLayer, band: int = 1) -> QgsSingleBandPseudoColorRenderer:
    """MNDWI: sand/soil → water — highlights urban water bodies well."""
    stops = [
        (-1.0, "#c8a96e", "Dry / built-up"),
        (-0.3, "#f5deb3", "Semi-dry"),
        (0.00, "#e8f5e9", "Transition"),
        (0.30, "#64b5f6", "Wet"),
        (0.70, "#0d47a1", "Open water"),
        (1.00, "#002171", "Deep water"),
    ]
    return _make_renderer(layer, band, stops, -1.0, 1.0)


def savi_renderer(layer: QgsRasterLayer, band: int = 1) -> QgsSingleBandPseudoColorRenderer:
    """SAVI: soil-adjusted; emphasises vegetated land in arid zones."""
    stops = [
        (-0.5, "#c4a35a", "Bare soil"),
        (0.00, "#fffde7", "Sparse"),
        (0.20, "#c5e1a5", "Low"),
        (0.40, "#66bb6a", "Moderate"),
        (0.70, "#1b5e20", "Dense"),
    ]
    return _make_renderer(layer, band, stops, -0.5, 0.7)


def change_renderer(layer: QgsRasterLayer, band: int = 1) -> QgsSingleBandPseudoColorRenderer:
    """
    Diverging red–white–green change map.
    Loss (NDVI decrease): red  |  Stable: white  |  Gain: green
    """
    stops = [
        (-3.0, "#b71c1c", "Significant loss"),
        (-1.96,"#ef9a9a", "Loss (95% CI)"),
        (-0.5, "#ffcdd2", "Slight loss"),
        (0.00, "#f5f5f5", "Stable"),
        (0.50, "#c8e6c9", "Slight gain"),
        (1.96, "#81c784", "Gain (95% CI)"),
        (3.00, "#1b5e20", "Significant gain"),
    ]
    return _make_renderer(layer, band, stops, -3.0, 3.0)


def embedding_change_renderer(layer: QgsRasterLayer, band: int = 1) -> QgsSingleBandPseudoColorRenderer:
    """
    Cosine dissimilarity from Google Satellite Embedding V1.
    0 = identical (blue) → 0.5 = moderate change (yellow) → 1.0 = maximum change (red).
    """
    stops = [
        (0.00, "#0d47a1", "Stable"),
        (0.10, "#42a5f5", "Low change"),
        (0.20, "#fffde7", "Moderate"),
        (0.40, "#ff9800", "High change"),
        (1.00, "#b71c1c", "Max change"),
    ]
    return _make_renderer(layer, band, stops, 0.0, 1.0)


def nbr_renderer(layer: QgsRasterLayer, band: int = 1) -> QgsSingleBandPseudoColorRenderer:
    """NBR: fire severity — grey (unburnt) → red (high severity burn)."""
    stops = [
        (-1.0, "#b71c1c", "High severity burn"),
        (-0.1, "#ff9800", "Moderate burn"),
        (0.10, "#ffd54f", "Low burn"),
        (0.30, "#f5f5f5", "Unburnt / sparse"),
        (0.70, "#2e7d32", "Healthy vegetation"),
        (1.00, "#1b5e20", "Dense green"),
    ]
    return _make_renderer(layer, band, stops, -1.0, 1.0)


INDEX_RENDERERS = {
    "NDVI": ndvi_renderer,
    "NDWI": ndwi_renderer,
    "EVI": evi_renderer,
    "MNDWI": mndwi_renderer,
    "SAVI": savi_renderer,
    "NBR": nbr_renderer,
    "CHANGE_ZSCORE": change_renderer,
    "EMBEDDING_CHANGE": embedding_change_renderer,
}


def apply_index_style(layer: QgsRasterLayer, index_name: str, band: int = 1) -> None:
    """Apply the appropriate colormap to a layer in-place and refresh."""
    renderer_fn = INDEX_RENDERERS.get(index_name.upper(), ndvi_renderer)
    renderer = renderer_fn(layer, band)
    layer.setRenderer(renderer)
    layer.triggerRepaint()

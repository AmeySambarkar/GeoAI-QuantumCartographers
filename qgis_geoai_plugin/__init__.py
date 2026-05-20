"""QGIS plugin factory function — required entry point."""


def classFactory(iface):
    from .plugin import GeoAIPlugin
    return GeoAIPlugin(iface)

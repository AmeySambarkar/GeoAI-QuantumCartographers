"""
GeoAI Water Resource Intelligence — main plugin lifecycle class.
Registered with QGIS via classFactory() in __init__.py.
"""
from __future__ import annotations

import os
from pathlib import Path

from qgis.core import QgsApplication, QgsMessageLog, Qgis
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QToolBar

from .ui.dock_panel import GeoAIDockPanel

PLUGIN_DIR = Path(__file__).parent
LOG_TAG = "GeoAI"


def log(msg: str, level=Qgis.Info):
    QgsMessageLog.logMessage(msg, LOG_TAG, level)


class GeoAIPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dock: GeoAIDockPanel | None = None
        self._actions: list[QAction] = []
        self._toolbar: QToolBar | None = None

        # Ensure satellite_pipeline is importable from inside QGIS Python env
        repo_root = str(PLUGIN_DIR.parent)
        if repo_root not in __import__("sys").path:
            __import__("sys").path.insert(0, repo_root)

    # ── QGIS lifecycle ────────────────────────────────────────────────

    def initGui(self):
        """Called by QGIS when the plugin is loaded."""
        self._toolbar = self.iface.addToolBar("GeoAI")
        self._toolbar.setObjectName("GeoAIToolbar")

        # Main panel toggle
        toggle_action = QAction(
            self._icon("satellite.svg"),
            "GeoAI Water Resource Intelligence",
            self.iface.mainWindow(),
        )
        toggle_action.setCheckable(True)
        toggle_action.setStatusTip("Open GeoAI analysis panel")
        toggle_action.triggered.connect(self._toggle_panel)
        self._toolbar.addAction(toggle_action)
        self.iface.addPluginToMenu("&GeoAI", toggle_action)
        self._actions.append(toggle_action)
        self._toggle_action = toggle_action

        # Quick-run actions
        for label, slot, icon in [
            ("Compute Spectral Indices", self._run_indices,      "indices.svg"),
            ("Run Change Detection",     self._run_change,       "change.svg"),
            ("Add Maxar WMS Layer",      self._add_maxar,        "maxar.svg"),
            ("Load GEE Composite",       self._load_gee,         "gee.svg"),
            ("Run Full Pipeline",        self._run_pipeline,     "pipeline.svg"),
        ]:
            act = QAction(self._icon(icon), label, self.iface.mainWindow())
            act.triggered.connect(slot)
            self._toolbar.addAction(act)
            self.iface.addPluginToMenu("&GeoAI", act)
            self._actions.append(act)

        # Create dock panel (hidden by default)
        self.dock = GeoAIDockPanel(self.iface)
        self.iface.mainWindow().addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.hide()

        log("GeoAI plugin initialised")

    def unload(self):
        """Called by QGIS when the plugin is unloaded."""
        for action in self._actions:
            self.iface.removePluginMenu("&GeoAI", action)
            self.iface.removeToolBarIcon(action)
        if self._toolbar:
            del self._toolbar
        if self.dock:
            self.dock.cleanup()
            self.iface.mainWindow().removeDockWidget(self.dock)
            self.dock.deleteLater()
        log("GeoAI plugin unloaded")

    # ── Toolbar slot forwarding ────────────────────────────────────────

    def _toggle_panel(self, checked: bool):
        if self.dock:
            self.dock.setVisible(checked)

    def _run_indices(self):
        self._open_panel()
        self.dock.run_indices()

    def _run_change(self):
        self._open_panel()
        self.dock.run_change_detection()

    def _add_maxar(self):
        self._open_panel()
        self.dock.add_maxar_layer()

    def _load_gee(self):
        self._open_panel()
        self.dock.load_gee_composite()

    def _run_pipeline(self):
        self._open_panel()
        self.dock.run_full_pipeline()

    def _open_panel(self):
        if self.dock and not self.dock.isVisible():
            self.dock.show()
            self._toggle_action.setChecked(True)

    def _icon(self, name: str) -> QIcon:
        path = PLUGIN_DIR / "resources" / "icons" / name
        if path.exists():
            return QIcon(str(path))
        return QgsApplication.getThemeIcon("/mActionAddRasterLayer.svg")

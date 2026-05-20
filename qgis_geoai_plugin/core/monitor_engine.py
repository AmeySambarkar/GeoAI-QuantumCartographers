"""
Threshold-based monitoring engine.
Uses QTimer to periodically re-compute spectral indices on the active layer
and fires QGIS message bar alerts when user-defined thresholds are crossed.

Cybernetic feedback loop: sense → compare → alert → (human acts) → re-sense.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from qgis.core import QgsRasterLayer, QgsMessageLog, Qgis
from qgis.PyQt.QtCore import QTimer, QObject, pyqtSignal

logger = logging.getLogger(__name__)


@dataclass
class MonitorRule:
    name: str
    layer_name: str
    index_name: str          # e.g. "NDVI"
    threshold_value: float
    direction: str           # "below" | "above"
    band_map: dict           # band assignments from IndexEngine
    severity: str = "warning"  # "info" | "warning" | "critical"
    last_value: Optional[float] = None
    triggered: bool = False
    trigger_count: int = 0


@dataclass
class MonitorEvent:
    timestamp: str
    rule_name: str
    layer_name: str
    index_name: str
    current_value: float
    threshold_value: float
    direction: str
    severity: str


class MonitorEngine(QObject):
    """
    QObject so it can own QTimers and emit Qt signals.
    Instantiate once per QGIS session; rules are added/removed at runtime.
    """
    alert_fired = pyqtSignal(MonitorEvent)   # emitted when a threshold is crossed
    check_complete = pyqtSignal(list)        # emitted after each check cycle (list[MonitorEvent])

    # Built-in thresholds derived from peer-reviewed water-stress literature
    DEFAULT_RULES = [
        {"name": "NDVI drought stress",   "index": "NDVI",  "threshold": 0.20, "direction": "below",  "severity": "critical"},
        {"name": "NDWI water body loss",  "index": "NDWI",  "threshold": 0.05, "direction": "below",  "severity": "warning"},
        {"name": "EVI vegetation health", "index": "EVI",   "threshold": 0.15, "direction": "below",  "severity": "warning"},
        {"name": "MNDWI water gain",      "index": "MNDWI", "threshold": 0.40, "direction": "above",  "severity": "info"},
    ]

    def __init__(self, iface, log_path: Optional[Path] = None):
        super().__init__()
        self.iface = iface
        self.rules: list[MonitorRule] = []
        self.events: list[MonitorEvent] = []
        self.log_path = log_path or Path("workspace/output/monitor_log.jsonl")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._run_check)
        self._active = False

    # ── Public API ─────────────────────────────────────────────────────

    def start(self, interval_seconds: int = 300) -> None:
        self._timer.start(interval_seconds * 1000)
        self._active = True
        QgsMessageLog.logMessage(
            f"Monitoring started (interval={interval_seconds}s, {len(self.rules)} rules)",
            "GeoAI", Qgis.Info,
        )

    def stop(self) -> None:
        self._timer.stop()
        self._active = False
        QgsMessageLog.logMessage("Monitoring stopped", "GeoAI", Qgis.Info)

    @property
    def is_active(self) -> bool:
        return self._active

    def add_rule(self, rule: MonitorRule) -> None:
        self.rules = [r for r in self.rules if r.name != rule.name]
        self.rules.append(rule)

    def remove_rule(self, name: str) -> None:
        self.rules = [r for r in self.rules if r.name != name]

    def add_default_rules(self, layer_name: str, band_map: dict) -> None:
        for cfg in self.DEFAULT_RULES:
            self.add_rule(MonitorRule(
                name=cfg["name"],
                layer_name=layer_name,
                index_name=cfg["index"],
                threshold_value=cfg["threshold"],
                direction=cfg["direction"],
                band_map=band_map,
                severity=cfg["severity"],
            ))

    def run_check_now(self) -> list[MonitorEvent]:
        return self._run_check()

    # ── Internal check loop ────────────────────────────────────────────

    def _run_check(self) -> list[MonitorEvent]:
        from qgis.core import QgsProject
        from .layer_manager import get_layer_bands
        from .index_engine import _safe, _compute_index

        fired: list[MonitorEvent] = []

        for rule in self.rules:
            # Find layer by name
            matches = [
                lyr for lyr in QgsProject.instance().mapLayers().values()
                if lyr.name() == rule.layer_name and isinstance(lyr, QgsRasterLayer)
            ]
            if not matches:
                continue
            layer = matches[0]

            try:
                bands_raw = get_layer_bands(layer)
                if np.nanmax(bands_raw) > 2.0:
                    bands = bands_raw / 10_000.0
                else:
                    bands = bands_raw

                arr = _compute_index(rule.index_name, bands, rule.band_map)
                if arr is None:
                    continue
                current_val = float(np.nanmean(arr))
                rule.last_value = current_val

                triggered = (
                    (rule.direction == "below" and current_val < rule.threshold_value) or
                    (rule.direction == "above" and current_val > rule.threshold_value)
                )

                if triggered:
                    rule.trigger_count += 1
                    event = MonitorEvent(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        rule_name=rule.name,
                        layer_name=rule.layer_name,
                        index_name=rule.index_name,
                        current_value=round(current_val, 4),
                        threshold_value=rule.threshold_value,
                        direction=rule.direction,
                        severity=rule.severity,
                    )
                    self.events.append(event)
                    fired.append(event)
                    self._fire_alert(event)
                    self._log_event(event)

                rule.triggered = triggered

            except Exception as exc:
                QgsMessageLog.logMessage(
                    f"Monitor check failed for rule '{rule.name}': {exc}",
                    "GeoAI", Qgis.Warning,
                )

        self.check_complete.emit(fired)
        return fired

    def _fire_alert(self, event: MonitorEvent) -> None:
        severity_map = {
            "info": Qgis.Info,
            "warning": Qgis.Warning,
            "critical": Qgis.Critical,
        }
        level = severity_map.get(event.severity, Qgis.Warning)
        msg = (
            f"[GeoAI Monitor] {event.rule_name}: "
            f"{event.index_name} = {event.current_value:.4f} "
            f"({event.direction} threshold {event.threshold_value})"
        )
        self.iface.messageBar().pushMessage("GeoAI Monitor", msg, level=level, duration=10)
        QgsMessageLog.logMessage(msg, "GeoAI", level)
        self.alert_fired.emit(event)

    def _log_event(self, event: MonitorEvent) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a") as f:
                f.write(json.dumps(asdict(event)) + "\n")
        except Exception:
            pass

    def get_rule_status(self) -> list[dict]:
        return [
            {
                "name": r.name,
                "layer": r.layer_name,
                "index": r.index_name,
                "threshold": r.threshold_value,
                "direction": r.direction,
                "last_value": r.last_value,
                "triggered": r.triggered,
                "trigger_count": r.trigger_count,
                "severity": r.severity,
            }
            for r in self.rules
        ]

    def cleanup(self) -> None:
        self.stop()
        self._timer.deleteLater()

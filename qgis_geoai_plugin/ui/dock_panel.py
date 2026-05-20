"""
GeoAI Water Resource Intelligence — main QGIS dock panel.
Programmatic Qt5/6 UI with five tabs:
  1. Layers      — load files, add Maxar WMS, load GEE composite
  2. Indices     — select + compute spectral indices with colormaps
  3. Change      — temporal change detection between two layers
  4. Monitor     — threshold rules + QTimer-based alert engine
  5. Report      — run full pipeline, show Claude report, export
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsMessageLog,
    Qgis,
)
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QFont, QColor
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QGroupBox, QLabel, QPushButton,
    QComboBox, QCheckBox, QLineEdit, QSpinBox,
    QDoubleSpinBox, QProgressBar, QTextEdit,
    QFileDialog, QSplitter, QScrollArea,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QSlider, QSizePolicy,
)


class GeoAIDockPanel(QDockWidget):
    def __init__(self, iface):
        super().__init__("GeoAI Water Intelligence", iface.mainWindow())
        self.iface = iface
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setMinimumWidth(380)

        # Late-initialized engines (avoid QGIS import errors at module load)
        self._monitor_engine = None
        self._worker = None
        self._last_features_json: Optional[str] = None
        self._last_report_md: Optional[str] = None

        self._build_ui()

    # ── UI Construction ───────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget()
        self.setWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)

        # Header
        hdr = QLabel("🛰️  GeoAI Water Resource Intelligence")
        hdr.setFont(QFont("Arial", 10, QFont.Bold))
        hdr.setStyleSheet("color: #1565c0; padding: 4px;")
        layout.addWidget(hdr)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs)

        self._build_layers_tab()
        self._build_indices_tab()
        self._build_change_tab()
        self._build_monitor_tab()
        self._build_report_tab()

        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #555; font-size: 10px; padding: 2px 4px;")
        layout.addWidget(self.status_label)

    # ── Tab 1: Layers ─────────────────────────────────────────────────

    def _build_layers_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # ── Load local GeoTIFFs ──
        grp_local = QGroupBox("Local Raster Files")
        vl = QVBoxLayout(grp_local)

        for label, attr in [("Multispectral (LISS-4 / HLS 6-band)", "ms_edit"),
                             ("DEM GeoTIFF", "dem_edit")]:
            row = QHBoxLayout()
            edit = QLineEdit()
            edit.setPlaceholderText(f"Path to {label} …")
            btn = QPushButton("Browse")
            btn.setMaximumWidth(70)
            btn.clicked.connect(lambda _, e=edit: self._browse_raster(e))
            row.addWidget(edit)
            row.addWidget(btn)
            vl.addWidget(QLabel(label))
            vl.addLayout(row)
            setattr(self, attr, edit)

        self.load_local_btn = QPushButton("Load Files into QGIS")
        self.load_local_btn.clicked.connect(self._load_local_files)
        vl.addWidget(self.load_local_btn)
        layout.addWidget(grp_local)

        # ── Demo data ──
        grp_demo = QGroupBox("Demo / Synthetic Data")
        vl2 = QVBoxLayout(grp_demo)
        self.demo_roi_label = QLabel("ROI: Maharashtra Pilot (73°E–73.5°E, 18.5°N–19°N)")
        vl2.addWidget(self.demo_roi_label)
        gen_btn = QPushButton("Generate Synthetic GeoTIFFs + Load")
        gen_btn.clicked.connect(self._generate_and_load_demo)
        vl2.addWidget(gen_btn)
        layout.addWidget(grp_demo)

        # ── Maxar WMS ──
        grp_maxar = QGroupBox("Maxar Streaming Basemap (WMS)")
        vl3 = QVBoxLayout(grp_maxar)
        vl3.addWidget(QLabel("API Key / ConnectID:"))
        self.maxar_key_edit = QLineEdit()
        self.maxar_key_edit.setPlaceholderText("Bearer token or connectid UUID")
        self.maxar_key_edit.setEchoMode(QLineEdit.Password)
        vl3.addWidget(self.maxar_key_edit)
        vl3.addWidget(QLabel("Layer type:"))
        self.maxar_layer_combo = QComboBox()
        self.maxar_layer_combo.addItems([
            "Vivid Standard", "Vivid Premium",
            "Precision Monitor", "Change Detection", "SecureWatch"
        ])
        vl3.addWidget(self.maxar_layer_combo)
        maxar_row = QHBoxLayout()
        add_wms_btn = QPushButton("Add WMS Layer")
        add_wms_btn.clicked.connect(self.add_maxar_layer)
        search_stac_btn = QPushButton("Search STAC Catalog")
        search_stac_btn.clicked.connect(self._search_maxar_stac)
        maxar_row.addWidget(add_wms_btn)
        maxar_row.addWidget(search_stac_btn)
        vl3.addLayout(maxar_row)
        layout.addWidget(grp_maxar)

        # ── GEE ──
        grp_gee = QGroupBox("Google Earth Engine")
        vl4 = QVBoxLayout(grp_gee)
        vl4.addWidget(QLabel("GEE Project ID:"))
        self.gee_proj_edit = QLineEdit()
        self.gee_proj_edit.setPlaceholderText("your-gee-project-id (optional)")
        vl4.addWidget(self.gee_proj_edit)
        gee_row = QHBoxLayout()
        self.gee_year_spin = QSpinBox()
        self.gee_year_spin.setRange(2015, 2030)
        self.gee_year_spin.setValue(2024)
        gee_row.addWidget(QLabel("Year:"))
        gee_row.addWidget(self.gee_year_spin)
        vl4.addLayout(gee_row)
        gee_btn_row = QHBoxLayout()
        load_s2_btn = QPushButton("Load S2 NDVI")
        load_s2_btn.clicked.connect(self.load_gee_composite)
        load_emb_btn = QPushButton("Load Embeddings (PCA)")
        load_emb_btn.clicked.connect(self._load_gee_embeddings)
        gee_change_btn = QPushButton("GEE Change Map")
        gee_change_btn.clicked.connect(self._load_gee_change)
        gee_btn_row.addWidget(load_s2_btn)
        gee_btn_row.addWidget(load_emb_btn)
        gee_btn_row.addWidget(gee_change_btn)
        vl4.addLayout(gee_btn_row)
        layout.addWidget(grp_gee)

        layout.addStretch()
        self.tabs.addTab(tab, "Layers")

    # ── Tab 2: Spectral Indices ────────────────────────────────────────

    def _build_indices_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        grp = QGroupBox("Compute Spectral Indices")
        vl = QVBoxLayout(grp)

        vl.addWidget(QLabel("Source layer:"))
        self.idx_layer_combo = QComboBox()
        self.idx_layer_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        refresh_btn = QPushButton("↻")
        refresh_btn.setMaximumWidth(32)
        refresh_btn.clicked.connect(self._refresh_layer_combos)
        row = QHBoxLayout()
        row.addWidget(self.idx_layer_combo)
        row.addWidget(refresh_btn)
        vl.addLayout(row)

        vl.addWidget(QLabel("Indices to compute:"))
        self.idx_checks: dict[str, QCheckBox] = {}
        for idx_name, desc in [
            ("NDVI",  "Vegetation vigour — NIR/Red ratio"),
            ("NDWI",  "Water bodies — Green/NIR ratio"),
            ("EVI",   "Enhanced veg — atmospheric corrected"),
            ("MNDWI", "Modified water — Green/SWIR ratio"),
            ("SAVI",  "Soil-adjusted vegetation"),
            ("NBR",   "Normalised Burn Ratio"),
        ]:
            cb = QCheckBox(f"{idx_name}  —  {desc}")
            cb.setChecked(idx_name in ("NDVI", "NDWI", "EVI"))
            self.idx_checks[idx_name] = cb
            vl.addWidget(cb)

        self.idx_progress = QProgressBar()
        self.idx_progress.setVisible(False)
        vl.addWidget(self.idx_progress)

        self.compute_btn = QPushButton("Compute Selected Indices")
        self.compute_btn.setStyleSheet("background:#1565c0; color:white; padding:6px;")
        self.compute_btn.clicked.connect(self.run_indices)
        vl.addWidget(self.compute_btn)

        layout.addWidget(grp)

        # Statistics display
        grp_stats = QGroupBox("Index Statistics")
        stats_vl = QVBoxLayout(grp_stats)
        self.stats_table = QTableWidget(0, 5)
        self.stats_table.setHorizontalHeaderLabels(["Index", "Mean", "Std", "Min", "Max"])
        self.stats_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.stats_table.setAlternatingRowColors(True)
        stats_vl.addWidget(self.stats_table)
        layout.addWidget(grp_stats)

        # Layer opacity
        grp_op = QGroupBox("Layer Opacity")
        op_vl = QVBoxLayout(grp_op)
        op_row = QHBoxLayout()
        self.opacity_layer_combo = QComboBox()
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_label = QLabel("100%")
        self.opacity_slider.valueChanged.connect(lambda v: self.opacity_label.setText(f"{v}%"))
        self.opacity_slider.sliderReleased.connect(self._apply_opacity)
        op_row.addWidget(self.opacity_layer_combo)
        op_row.addWidget(self.opacity_slider)
        op_row.addWidget(self.opacity_label)
        op_vl.addLayout(op_row)
        layout.addWidget(grp_op)

        layout.addStretch()
        self.tabs.addTab(tab, "Indices")

    # ── Tab 3: Change Detection ────────────────────────────────────────

    def _build_change_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        grp = QGroupBox("Temporal Change Detection")
        vl = QVBoxLayout(grp)

        for label, attr in [("Baseline layer (earlier date):", "chg_base_combo"),
                             ("Analysis layer (later date):", "chg_anal_combo")]:
            vl.addWidget(QLabel(label))
            combo = QComboBox()
            setattr(self, attr, combo)
            vl.addWidget(combo)

        vl.addWidget(QLabel("Index for change detection:"))
        self.chg_index_combo = QComboBox()
        self.chg_index_combo.addItems(["NDVI", "NDWI", "EVI", "Band1"])
        vl.addWidget(self.chg_index_combo)

        self.chg_progress = QProgressBar()
        self.chg_progress.setVisible(False)
        vl.addWidget(self.chg_progress)

        run_chg_btn = QPushButton("Run Change Detection")
        run_chg_btn.setStyleSheet("background:#2e7d32; color:white; padding:6px;")
        run_chg_btn.clicked.connect(self.run_change_detection)
        vl.addWidget(run_chg_btn)

        layout.addWidget(grp)

        # Results
        grp_res = QGroupBox("Change Report")
        res_vl = QVBoxLayout(grp_res)
        self.change_table = QTableWidget(0, 2)
        self.change_table.setHorizontalHeaderLabels(["Metric", "Value"])
        self.change_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.change_table.setAlternatingRowColors(True)
        res_vl.addWidget(self.change_table)
        layout.addWidget(grp_res)

        layout.addStretch()
        self.tabs.addTab(tab, "Change")

    # ── Tab 4: Monitor ────────────────────────────────────────────────

    def _build_monitor_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Control
        grp_ctrl = QGroupBox("Monitoring Control")
        vl = QVBoxLayout(grp_ctrl)

        row = QHBoxLayout()
        row.addWidget(QLabel("Check interval (seconds):"))
        self.monitor_interval_spin = QSpinBox()
        self.monitor_interval_spin.setRange(30, 3600)
        self.monitor_interval_spin.setValue(300)
        self.monitor_interval_spin.setSuffix(" s")
        row.addWidget(self.monitor_interval_spin)
        vl.addLayout(row)

        btn_row = QHBoxLayout()
        self.monitor_start_btn = QPushButton("▶ Start Monitoring")
        self.monitor_start_btn.setStyleSheet("background:#1b5e20; color:white;")
        self.monitor_start_btn.clicked.connect(self._start_monitoring)
        self.monitor_stop_btn = QPushButton("■ Stop")
        self.monitor_stop_btn.setEnabled(False)
        self.monitor_stop_btn.clicked.connect(self._stop_monitoring)
        self.monitor_now_btn = QPushButton("Check Now")
        self.monitor_now_btn.clicked.connect(self._check_now)
        btn_row.addWidget(self.monitor_start_btn)
        btn_row.addWidget(self.monitor_stop_btn)
        btn_row.addWidget(self.monitor_now_btn)
        vl.addLayout(btn_row)

        self.monitor_status_label = QLabel("Status: Idle")
        self.monitor_status_label.setStyleSheet("color: #555;")
        vl.addWidget(self.monitor_status_label)
        layout.addWidget(grp_ctrl)

        # Add custom rule
        grp_rule = QGroupBox("Add Monitoring Rule")
        rule_vl = QVBoxLayout(grp_rule)

        rule_row1 = QHBoxLayout()
        rule_row1.addWidget(QLabel("Layer:"))
        self.rule_layer_combo = QComboBox()
        rule_row1.addWidget(self.rule_layer_combo)
        rule_vl.addLayout(rule_row1)

        rule_row2 = QHBoxLayout()
        rule_row2.addWidget(QLabel("Index:"))
        self.rule_index_combo = QComboBox()
        self.rule_index_combo.addItems(["NDVI", "NDWI", "EVI", "MNDWI", "SAVI"])
        self.rule_dir_combo = QComboBox()
        self.rule_dir_combo.addItems(["below", "above"])
        self.rule_thresh_spin = QDoubleSpinBox()
        self.rule_thresh_spin.setRange(-1.0, 2.0)
        self.rule_thresh_spin.setSingleStep(0.01)
        self.rule_thresh_spin.setValue(0.20)
        rule_row2.addWidget(self.rule_index_combo)
        rule_row2.addWidget(self.rule_dir_combo)
        rule_row2.addWidget(self.rule_thresh_spin)
        rule_vl.addLayout(rule_row2)

        sev_row = QHBoxLayout()
        sev_row.addWidget(QLabel("Severity:"))
        self.rule_sev_combo = QComboBox()
        self.rule_sev_combo.addItems(["info", "warning", "critical"])
        self.rule_sev_combo.setCurrentText("warning")
        sev_row.addWidget(self.rule_sev_combo)
        add_rule_btn = QPushButton("Add Rule")
        add_rule_btn.clicked.connect(self._add_monitor_rule)
        sev_row.addWidget(add_rule_btn)
        rule_vl.addLayout(sev_row)

        defaults_btn = QPushButton("Load Default Rules (NDVI/NDWI/EVI drought thresholds)")
        defaults_btn.clicked.connect(self._load_default_rules)
        rule_vl.addWidget(defaults_btn)
        layout.addWidget(grp_rule)

        # Rules table
        grp_rules = QGroupBox("Active Rules")
        rules_vl = QVBoxLayout(grp_rules)
        self.rules_table = QTableWidget(0, 6)
        self.rules_table.setHorizontalHeaderLabels(["Rule", "Layer", "Index", "Direction", "Threshold", "Last Value"])
        self.rules_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.rules_table.setAlternatingRowColors(True)
        rules_vl.addWidget(self.rules_table)
        layout.addWidget(grp_rules)

        # Alert log
        grp_log = QGroupBox("Alert Log")
        log_vl = QVBoxLayout(grp_log)
        self.alert_log = QTextEdit()
        self.alert_log.setReadOnly(True)
        self.alert_log.setMaximumHeight(120)
        self.alert_log.setFont(QFont("Courier", 9))
        log_vl.addWidget(self.alert_log)
        layout.addWidget(grp_log)

        self.tabs.addTab(tab, "Monitor")

    # ── Tab 5: Report ─────────────────────────────────────────────────

    def _build_report_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Config
        grp_cfg = QGroupBox("Pipeline Configuration")
        cfg_vl = QVBoxLayout(grp_cfg)

        api_row = QHBoxLayout()
        api_row.addWidget(QLabel("Anthropic API Key:"))
        self.claude_key_edit = QLineEdit()
        self.claude_key_edit.setEchoMode(QLineEdit.Password)
        self.claude_key_edit.setPlaceholderText("sk-ant-… (enables full Claude report)")
        self.claude_key_edit.setText(os.getenv("ANTHROPIC_API_KEY", ""))
        api_row.addWidget(self.claude_key_edit)
        cfg_vl.addLayout(api_row)

        year_row = QHBoxLayout()
        year_row.addWidget(QLabel("Baseline:"))
        self.baseline_spin = QSpinBox()
        self.baseline_spin.setRange(2000, 2030)
        self.baseline_spin.setValue(2018)
        year_row.addWidget(self.baseline_spin)
        year_row.addWidget(QLabel("Analysis:"))
        self.analysis_spin = QSpinBox()
        self.analysis_spin.setRange(2000, 2030)
        self.analysis_spin.setValue(2024)
        year_row.addWidget(self.analysis_spin)
        cfg_vl.addLayout(year_row)

        self.demo_check = QCheckBox("Use synthetic demo data (no real files needed)")
        self.demo_check.setChecked(True)
        cfg_vl.addWidget(self.demo_check)
        layout.addWidget(grp_cfg)

        # Run
        self.run_pipeline_btn = QPushButton("▶ Run Full Pipeline + Generate Report")
        self.run_pipeline_btn.setStyleSheet(
            "background:#1565c0; color:white; padding:8px; font-weight:bold;"
        )
        self.run_pipeline_btn.clicked.connect(self.run_full_pipeline)
        layout.addWidget(self.run_pipeline_btn)

        self.pipeline_progress = QProgressBar()
        self.pipeline_progress.setVisible(False)
        self.pipeline_stage_label = QLabel("")
        self.pipeline_stage_label.setStyleSheet("color:#1565c0; font-size:10px;")
        layout.addWidget(self.pipeline_progress)
        layout.addWidget(self.pipeline_stage_label)

        # Report display
        grp_report = QGroupBox("Water Resource Intelligence Report")
        report_vl = QVBoxLayout(grp_report)
        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        self.report_text.setFont(QFont("Courier", 9))
        report_vl.addWidget(self.report_text)

        export_row = QHBoxLayout()
        export_md_btn = QPushButton("Export .md")
        export_md_btn.clicked.connect(lambda: self._export_report("md"))
        export_json_btn = QPushButton("Export JSON")
        export_json_btn.clicked.connect(lambda: self._export_report("json"))
        load_into_qgis_btn = QPushButton("Load Results into QGIS")
        load_into_qgis_btn.clicked.connect(self._load_pipeline_outputs_into_qgis)
        export_row.addWidget(export_md_btn)
        export_row.addWidget(export_json_btn)
        export_row.addWidget(load_into_qgis_btn)
        report_vl.addLayout(export_row)
        layout.addWidget(grp_report)

        self.tabs.addTab(tab, "Report")

    # ── Slot Implementations ──────────────────────────────────────────

    def _browse_raster(self, edit: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select GeoTIFF", "", "GeoTIFF files (*.tif *.tiff)"
        )
        if path:
            edit.setText(path)

    def _refresh_layer_combos(self):
        layers = [(n, l) for n, l in _raster_layers()]
        names = [n for n, _ in layers]
        for combo in [
            self.idx_layer_combo, self.chg_base_combo, self.chg_anal_combo,
            self.rule_layer_combo, self.opacity_layer_combo,
        ]:
            current = combo.currentText()
            combo.clear()
            combo.addItems(names)
            if current in names:
                combo.setCurrentText(current)
        self._set_status(f"Refreshed: {len(names)} raster layers")

    def _load_local_files(self):
        from ..core.layer_manager import add_raster_layer
        for path, style in [
            (self.ms_edit.text(), "NDVI"),
            (self.dem_edit.text(), None),
        ]:
            if path and Path(path).exists():
                add_raster_layer(path, Path(path).stem, index_style=style)
        self._refresh_layer_combos()
        self._set_status("Local files loaded")

    def _generate_and_load_demo(self):
        from ..core.layer_manager import add_raster_layer
        try:
            from satellite_pipeline.demo.generate_sample_data import generate_all
            files = generate_all("workspace/input")
            for name, path in files.items():
                style = "NDVI" if "hls" in name else None
                add_raster_layer(str(path), f"Demo_{name}", index_style=style)
            self._refresh_layer_combos()
            self._set_status(f"Demo data generated: {len(files)} layers loaded")
        except Exception as exc:
            self._set_status(f"Demo generation failed: {exc}", error=True)

    # ── Maxar ──

    def add_maxar_layer(self):
        from ..providers.maxar_provider import add_maxar_wms_layer
        key = self.maxar_key_edit.text().strip()
        if not key:
            self.iface.messageBar().pushMessage(
                "GeoAI", "Enter Maxar API key / connectid to add WMS layer",
                level=Qgis.Warning, duration=5,
            )
            return
        layer_type = self.maxar_layer_combo.currentText()
        layer = add_maxar_wms_layer(key, layer_type)
        msg = f"Maxar {layer_type} added" if layer else "Maxar WMS layer invalid (check key)"
        self._set_status(msg, error=(layer is None))

    def _search_maxar_stac(self):
        from ..providers.maxar_provider import search_maxar_stac
        from ..core.layer_manager import list_raster_layers
        key = self.maxar_key_edit.text().strip()
        if not key:
            self.iface.messageBar().pushMessage(
                "GeoAI", "Enter Maxar Bearer token to search STAC catalog",
                level=Qgis.Warning, duration=5,
            )
            return
        bbox = [73.0, 18.5, 73.5, 19.0]  # TODO: from current canvas extent
        layer = search_maxar_stac(key, bbox, "2018-01-01", "2024-12-31")
        self._set_status("Maxar STAC results added as vector layer" if layer else "STAC search failed")

    # ── GEE ──

    def load_gee_composite(self):
        from ..providers.gee_provider import load_sentinel2_composite
        year = self.gee_year_spin.value()
        proj = self.gee_proj_edit.text().strip()
        layer = load_sentinel2_composite(
            bbox=[73.0, 18.5, 73.5, 19.0],
            year=year,
            gee_project=proj,
        )
        self._refresh_layer_combos()
        self._set_status(f"GEE S2 NDVI {year} loaded" if layer else "GEE unavailable (simulated)")

    def _load_gee_embeddings(self):
        from ..providers.gee_provider import load_satellite_embeddings
        year = self.gee_year_spin.value()
        proj = self.gee_proj_edit.text().strip()
        layer = load_satellite_embeddings(bbox=[73.0, 18.5, 73.5, 19.0], year=year, gee_project=proj)
        self._refresh_layer_combos()
        self._set_status(f"Embedding PCA {year} loaded" if layer else "GEE embedding unavailable")

    def _load_gee_change(self):
        from ..providers.gee_provider import compute_change_layer_gee
        proj = self.gee_proj_edit.text().strip()
        layer = compute_change_layer_gee(
            bbox=[73.0, 18.5, 73.5, 19.0],
            baseline_year=self.baseline_spin.value(),
            analysis_year=self.analysis_spin.value(),
            gee_project=proj,
        )
        self._refresh_layer_combos()
        self._set_status("GEE change layer loaded" if layer else "GEE change map unavailable")

    # ── Indices ──

    def run_indices(self):
        from ..core.index_engine import compute_and_add_indices, index_statistics

        layer = self._get_combo_layer(self.idx_layer_combo)
        if layer is None:
            self._set_status("Select a raster layer first", error=True)
            return

        targets = [n for n, cb in self.idx_checks.items() if cb.isChecked()]
        if not targets:
            self._set_status("Select at least one index", error=True)
            return

        self.idx_progress.setVisible(True)
        self.idx_progress.setValue(0)
        self.compute_btn.setEnabled(False)

        def progress(v):
            self.idx_progress.setValue(v)

        try:
            results = compute_and_add_indices(layer, targets, progress_callback=progress)
            self._populate_stats_table(results)
            self._refresh_layer_combos()
            self._set_status(f"Computed: {', '.join(results.keys())}")
        except Exception as exc:
            self._set_status(f"Index computation failed: {exc}", error=True)
        finally:
            self.idx_progress.setVisible(False)
            self.compute_btn.setEnabled(True)

    def _populate_stats_table(self, results: dict):
        from ..core.index_engine import index_statistics
        import numpy as np

        self.stats_table.setRowCount(0)
        for idx_name, arr in results.items():
            stats = index_statistics(arr)
            if not stats:
                continue
            row = self.stats_table.rowCount()
            self.stats_table.insertRow(row)
            for col, val in enumerate([
                idx_name,
                f"{stats.get('mean', ''):.4f}",
                f"{stats.get('std', ''):.4f}",
                f"{stats.get('min', ''):.4f}",
                f"{stats.get('max', ''):.4f}",
            ]):
                item = QTableWidgetItem(str(val))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.stats_table.setItem(row, col, item)

    def _apply_opacity(self):
        from ..core.layer_manager import set_layer_opacity
        layer = self._get_combo_layer(self.opacity_layer_combo)
        if layer:
            set_layer_opacity(layer, self.opacity_slider.value() / 100.0)

    # ── Change Detection ──

    def run_change_detection(self):
        from ..core.change_engine import run_change_detection

        base  = self._get_combo_layer(self.chg_base_combo)
        anal  = self._get_combo_layer(self.chg_anal_combo)
        if base is None or anal is None or base.id() == anal.id():
            self._set_status("Select two different raster layers", error=True)
            return

        self.chg_progress.setVisible(True)
        self.chg_progress.setValue(0)

        try:
            report = run_change_detection(
                base, anal,
                index_name=self.chg_index_combo.currentText(),
                progress_callback=lambda v: self.chg_progress.setValue(v),
            )
            self._populate_change_table(report)
            self._refresh_layer_combos()
            self._set_status(
                f"Change: {report.index_used} Δ{report.mean_change:+.4f} "
                f"| loss={report.loss_fraction:.3f} gain={report.gain_fraction:.3f}"
            )
        except Exception as exc:
            self._set_status(f"Change detection failed: {exc}", error=True)
        finally:
            self.chg_progress.setVisible(False)

    def _populate_change_table(self, report):
        from dataclasses import asdict
        self.change_table.setRowCount(0)
        for k, v in asdict(report).items():
            if v is None:
                continue
            row = self.change_table.rowCount()
            self.change_table.insertRow(row)
            self.change_table.setItem(row, 0, QTableWidgetItem(k.replace("_", " ").title()))
            self.change_table.setItem(row, 1, QTableWidgetItem(
                f"{v:.4f}" if isinstance(v, float) else str(v)
            ))

    # ── Monitor ──

    def _ensure_monitor_engine(self):
        if self._monitor_engine is None:
            from ..core.monitor_engine import MonitorEngine
            self._monitor_engine = MonitorEngine(self.iface)
            self._monitor_engine.alert_fired.connect(self._on_alert)

    def _start_monitoring(self):
        self._ensure_monitor_engine()
        interval = self.monitor_interval_spin.value()
        self._monitor_engine.start(interval)
        self.monitor_start_btn.setEnabled(False)
        self.monitor_stop_btn.setEnabled(True)
        self.monitor_status_label.setText(f"Status: Active (every {interval}s)")
        self.monitor_status_label.setStyleSheet("color: #1b5e20; font-weight: bold;")

    def _stop_monitoring(self):
        if self._monitor_engine:
            self._monitor_engine.stop()
        self.monitor_start_btn.setEnabled(True)
        self.monitor_stop_btn.setEnabled(False)
        self.monitor_status_label.setText("Status: Stopped")
        self.monitor_status_label.setStyleSheet("color: #c62828;")

    def _check_now(self):
        self._ensure_monitor_engine()
        events = self._monitor_engine.run_check_now()
        self._refresh_rules_table()
        if not events:
            self._set_status("Check complete — no thresholds crossed")
        else:
            self._set_status(f"⚠ {len(events)} alert(s) fired")

    def _add_monitor_rule(self):
        from ..core.monitor_engine import MonitorRule
        from ..core.index_engine import _detect_band_map

        self._ensure_monitor_engine()
        layer = self._get_combo_layer(self.rule_layer_combo)
        if layer is None:
            return

        from ..core.layer_manager import get_layer_bands
        bands = get_layer_bands(layer)
        bmap = _detect_band_map(bands.shape[0]) or {}

        rule = MonitorRule(
            name=f"{self.rule_index_combo.currentText()} {self.rule_dir_combo.currentText()} {self.rule_thresh_spin.value():.2f}",
            layer_name=layer.name(),
            index_name=self.rule_index_combo.currentText(),
            threshold_value=self.rule_thresh_spin.value(),
            direction=self.rule_dir_combo.currentText(),
            band_map=bmap,
            severity=self.rule_sev_combo.currentText(),
        )
        self._monitor_engine.add_rule(rule)
        self._refresh_rules_table()
        self._set_status(f"Rule added: {rule.name}")

    def _load_default_rules(self):
        from ..core.monitor_engine import MonitorEngine
        from ..core.index_engine import _detect_band_map
        from ..core.layer_manager import get_layer_bands

        self._ensure_monitor_engine()
        layer = self._get_combo_layer(self.rule_layer_combo)
        if layer is None:
            self._set_status("Select a layer first", error=True)
            return

        bands = get_layer_bands(layer)
        bmap = _detect_band_map(bands.shape[0]) or {}
        self._monitor_engine.add_default_rules(layer.name(), bmap)
        self._refresh_rules_table()
        self._set_status(f"Default rules loaded for {layer.name()}")

    def _refresh_rules_table(self):
        if self._monitor_engine is None:
            return
        status = self._monitor_engine.get_rule_status()
        self.rules_table.setRowCount(0)
        for rule in status:
            row = self.rules_table.rowCount()
            self.rules_table.insertRow(row)
            lv = f"{rule['last_value']:.4f}" if rule["last_value"] is not None else "—"
            color = QColor("#ffcdd2") if rule["triggered"] else QColor("#ffffff")
            for col, val in enumerate([
                rule["name"], rule["layer"], rule["index"],
                rule["direction"], str(rule["threshold"]), lv,
            ]):
                item = QTableWidgetItem(val)
                item.setBackground(color)
                self.rules_table.setItem(row, col, item)

    def _on_alert(self, event):
        from dataclasses import asdict
        msg = (
            f"[{event.timestamp[11:19]}] ⚠ {event.rule_name}: "
            f"{event.index_name}={event.current_value:.4f} "
            f"({event.direction} {event.threshold_value})\n"
        )
        self.alert_log.append(msg)
        self._refresh_rules_table()

    # ── Report / Pipeline ──

    def run_full_pipeline(self):
        from satellite_pipeline.config import Config, ROI
        from ..workers.pipeline_worker import PipelineWorker

        config = Config()
        config.roi = ROI(73.0, 18.5, 73.5, 19.0)
        config.baseline_year = self.baseline_spin.value()
        config.analysis_year = self.analysis_spin.value()

        key = self.claude_key_edit.text().strip()
        if key:
            config.anthropic_api_key = key

        self.run_pipeline_btn.setEnabled(False)
        self.pipeline_progress.setVisible(True)
        self.pipeline_progress.setValue(0)
        self.pipeline_stage_label.setText("Starting pipeline…")

        self._worker = PipelineWorker(
            config=config,
            ms_path=self.ms_edit.text(),
            dem_path=self.dem_edit.text(),
            demo_mode=self.demo_check.isChecked(),
        )
        self._worker.progress.connect(self.pipeline_progress.setValue)
        self._worker.stage_changed.connect(self.pipeline_stage_label.setText)
        self._worker.finished_ok.connect(self._on_pipeline_success)
        self._worker.finished_error.connect(self._on_pipeline_error)
        self._worker.start()

    def _on_pipeline_success(self, features_json: str, report_md: str):
        self._last_features_json = features_json
        self._last_report_md = report_md
        self.report_text.setPlainText(report_md)
        self.run_pipeline_btn.setEnabled(True)
        self.pipeline_progress.setVisible(False)
        self.pipeline_stage_label.setText("Complete")
        self._set_status("Pipeline finished — report ready")
        self.tabs.setCurrentIndex(4)  # switch to Report tab

    def _on_pipeline_error(self, error_msg: str):
        self.run_pipeline_btn.setEnabled(True)
        self.pipeline_progress.setVisible(False)
        self.pipeline_stage_label.setText("Error")
        self.report_text.setPlainText(f"Pipeline error:\n\n{error_msg}")
        self._set_status("Pipeline failed — see Report tab", error=True)

    def _export_report(self, fmt: str):
        if fmt == "md" and self._last_report_md:
            path, _ = QFileDialog.getSaveFileName(self, "Save Report", "water_plan.md", "Markdown (*.md)")
            if path:
                Path(path).write_text(self._last_report_md)
                self._set_status(f"Report saved: {path}")
        elif fmt == "json" and self._last_features_json:
            path, _ = QFileDialog.getSaveFileName(self, "Save JSON", "feature_summary.json", "JSON (*.json)")
            if path:
                Path(path).write_text(self._last_features_json)
                self._set_status(f"JSON saved: {path}")

    def _load_pipeline_outputs_into_qgis(self):
        from ..core.layer_manager import add_raster_layer
        out_dir = Path("workspace/output")
        added = 0
        for pattern, style in [
            ("*NDVI*.tif", "NDVI"),
            ("*NDWI*.tif", "NDWI"),
            ("*Change*.tif", "CHANGE_ZSCORE"),
            ("*DEM*.tif", None),
        ]:
            for f in (Path("workspace/input").glob(pattern)):
                add_raster_layer(str(f), f.stem, index_style=style)
                added += 1
        self._refresh_layer_combos()
        self._set_status(f"Loaded {added} pipeline output layers into QGIS")

    # ── Helpers ──────────────────────────────────────────────────────

    def _get_combo_layer(self, combo: QComboBox) -> Optional[QgsRasterLayer]:
        name = combo.currentText()
        layers = [l for n, l in _raster_layers() if n == name]
        return layers[0] if layers else None

    def _set_status(self, msg: str, error: bool = False):
        self.status_label.setText(msg)
        color = "#c62828" if error else "#2e7d32"
        self.status_label.setStyleSheet(f"color:{color}; font-size:10px; padding:2px 4px;")
        if error:
            QgsMessageLog.logMessage(msg, "GeoAI", Qgis.Warning)

    # ── Lifecycle ─────────────────────────────────────────────────────

    def cleanup(self):
        if self._monitor_engine:
            self._monitor_engine.cleanup()
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(3000)


# ── Utility ──────────────────────────────────────────────────────────

def _raster_layers() -> list[tuple[str, QgsRasterLayer]]:
    return [
        (lyr.name(), lyr)
        for lyr in QgsProject.instance().mapLayers().values()
        if isinstance(lyr, QgsRasterLayer)
    ]

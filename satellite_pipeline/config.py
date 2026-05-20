"""
Pipeline configuration — reads from environment variables or .env file.
All API keys are optional; each client degrades gracefully when absent.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class ROI:
    """Region of interest as WGS-84 bounding box."""
    west: float = 73.0
    south: float = 18.5
    east: float = 73.5
    north: float = 19.0
    name: str = "Maharashtra_Pilot"

    @property
    def bbox(self) -> list[float]:
        return [self.west, self.south, self.east, self.north]

    @property
    def ee_geometry(self):
        import ee
        return ee.Geometry.Rectangle(self.bbox)


@dataclass
class Config:
    # API credentials
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    maxar_api_key: str = field(default_factory=lambda: os.getenv("MAXAR_API_KEY", ""))
    gee_project: str = field(default_factory=lambda: os.getenv("GEE_PROJECT", ""))
    gee_service_account: str = field(default_factory=lambda: os.getenv("GEE_SERVICE_ACCOUNT", ""))
    gee_key_file: str = field(default_factory=lambda: os.getenv("GEE_KEY_FILE", ""))

    # Analysis parameters
    roi: ROI = field(default_factory=ROI)
    baseline_year: int = 2018
    analysis_year: int = 2024
    cloud_cover_max: int = 20
    sentinel2_collection: str = "COPERNICUS/S2_SR_HARMONIZED"
    gee_embedding_collection: str = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"

    # Maxar endpoints
    maxar_stac_url: str = "https://api.maxar.com/discovery/v1/stac/search"
    maxar_streaming_url: str = "https://api.maxar.com/streaming/v1/ogc/wms"
    maxar_basemap_collection: str = "Maxar:Vivid"

    # Local workspace
    workspace: Path = field(default_factory=lambda: Path("./workspace"))
    input_dir: Path = field(default_factory=lambda: Path("./workspace/input"))
    output_dir: Path = field(default_factory=lambda: Path("./workspace/output"))

    # Claude model
    claude_model: str = "claude-opus-4-7"

    def __post_init__(self):
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_maxar(self) -> bool:
        return bool(self.maxar_api_key)

    @property
    def has_gee(self) -> bool:
        return bool(self.gee_project or self.gee_service_account)


CONFIG = Config()

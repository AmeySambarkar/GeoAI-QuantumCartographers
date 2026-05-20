#!/usr/bin/env python3
"""
Install the GeoAI QGIS plugin into the correct QGIS3 plugins directory.

Usage:
    python qgis_geoai_plugin/install_plugin.py          # auto-detects QGIS profile dir
    python qgis_geoai_plugin/install_plugin.py --check  # check current install
    python qgis_geoai_plugin/install_plugin.py --uninstall

Then restart QGIS and enable the plugin via Plugins → Manage and Install Plugins.
"""
import argparse
import os
import platform
import shutil
import sys
from pathlib import Path


def qgis_plugin_dir() -> Path:
    """Return platform-specific QGIS3 user plugin directory."""
    system = platform.system()
    if system == "Windows":
        base = Path(os.getenv("APPDATA", "")) / "QGIS" / "QGIS3" / "profiles" / "default" / "python" / "plugins"
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support" / "QGIS" / "QGIS3" / "profiles" / "default" / "python" / "plugins"
    else:
        base = Path.home() / ".local" / "share" / "QGIS" / "QGIS3" / "profiles" / "default" / "python" / "plugins"
    return base


PLUGIN_NAME = "qgis_geoai_plugin"
PLUGIN_SRC  = Path(__file__).parent


def install(target_dir: Path) -> None:
    dest = target_dir / PLUGIN_NAME
    if dest.exists():
        print(f"Removing existing install: {dest}")
        shutil.rmtree(dest)
    print(f"Installing plugin: {PLUGIN_SRC} → {dest}")
    shutil.copytree(PLUGIN_SRC, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "install_plugin.py"))
    print(f"\nInstalled to: {dest}")
    print("\nNext steps:")
    print("  1. Open QGIS")
    print("  2. Plugins → Manage and Install Plugins → Installed")
    print(f'  3. Enable "{PLUGIN_NAME}" (tick the checkbox)')
    print("  4. Restart QGIS if prompted")
    print('  5. Toolbar: click the "🛰️ GeoAI" button to open the panel')


def check(target_dir: Path) -> None:
    dest = target_dir / PLUGIN_NAME
    if dest.exists():
        print(f"Plugin is installed at: {dest}")
        meta = dest / "metadata.txt"
        if meta.exists():
            for line in meta.read_text().splitlines():
                if line.startswith(("name=", "version=", "qgisMinimumVersion=")):
                    print(f"  {line}")
    else:
        print(f"Plugin NOT installed. Expected location: {dest}")


def uninstall(target_dir: Path) -> None:
    dest = target_dir / PLUGIN_NAME
    if dest.exists():
        shutil.rmtree(dest)
        print(f"Uninstalled: {dest}")
    else:
        print(f"Plugin not found at {dest}")


def main():
    parser = argparse.ArgumentParser(description="GeoAI QGIS Plugin installer")
    parser.add_argument("--check",     action="store_true", help="Check installation status")
    parser.add_argument("--uninstall", action="store_true", help="Remove the plugin")
    parser.add_argument("--dir",       default=None, help="Override QGIS plugin directory")
    args = parser.parse_args()

    target = Path(args.dir) if args.dir else qgis_plugin_dir()

    if args.check:
        check(target)
    elif args.uninstall:
        uninstall(target)
    else:
        target.mkdir(parents=True, exist_ok=True)
        install(target)


if __name__ == "__main__":
    main()

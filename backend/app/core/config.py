from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_DATA_DIR = PROJECT_ROOT / "runtime_data"
PLAYWRIGHT_BROWSERS_DIR = PROJECT_ROOT / ".playwright-browsers"
MAX_SCREENSHOT_BYTES = 12 * 1024 * 1024


def configure_runtime_environment() -> None:
    """Keep browser downloads and scan artifacts within the project directory."""
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(PLAYWRIGHT_BROWSERS_DIR))


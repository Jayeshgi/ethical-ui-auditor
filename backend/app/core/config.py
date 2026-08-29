from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

RUNTIME_DATA_DIR = PROJECT_ROOT / "runtime_data"
PLAYWRIGHT_BROWSERS_DIR = PROJECT_ROOT / ".playwright-browsers"
MAX_SCREENSHOT_BYTES = 12 * 1024 * 1024
MAX_SCREENSHOT_HEIGHT = int(os.getenv("MAX_SCREENSHOT_HEIGHT", "12000"))
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://auditor:replace-with-local-password@127.0.0.1:5432/ethical_ui_auditor",
)
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "development-only-change-before-deployment")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
VISUAL_MODEL_PATH = Path(
    os.getenv("VISUAL_MODEL_PATH", str(PROJECT_ROOT / "model_artifacts" / "dark_pattern_yolo_v2" / "best.pt"))
)
VISUAL_CONFIDENCE_THRESHOLD = float(os.getenv("VISUAL_CONFIDENCE_THRESHOLD", "0.25"))


def configure_runtime_environment() -> None:
    """Keep browser downloads and scan artifacts within the project directory."""
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(PLAYWRIGHT_BROWSERS_DIR))
    RUNTIME_DATA_DIR.mkdir(parents=True, exist_ok=True)

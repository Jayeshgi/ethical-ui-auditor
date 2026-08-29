from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.flow_analysis.recorder import record_flow  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Record a manual browser journey as a flow action file.")
    parser.add_argument("url", help="Public or controlled website URL to open")
    parser.add_argument("--output", type=Path, help="Optional output JSON path")
    args = parser.parse_args()
    destination = record_flow(args.url, args.output)
    print(f"Recorded flow: {destination}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.flow_analysis.autonomous_schemas import AutonomousFlowRequest  # noqa: E402
from app.flow_analysis.schemas import FlowPairRequest  # noqa: E402


def _write_schema(path: Path, model: type) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(model.model_json_schema(), indent=2) + "\n",
        encoding="utf-8",
    )
    print(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export autonomous and manual paired-flow JSON Schemas.")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "docs" / "flow-pair.schema.json",
        help="Output path for the reviewed manual-definition request schema.",
    )
    parser.add_argument(
        "--autonomous-output",
        type=Path,
        default=PROJECT_ROOT / "docs" / "autonomous-flow.schema.json",
        help="Output path for the URL-first autonomous request schema.",
    )
    args = parser.parse_args()
    _write_schema(args.output, FlowPairRequest)
    _write_schema(args.autonomous_output, AutonomousFlowRequest)


if __name__ == "__main__":
    main()

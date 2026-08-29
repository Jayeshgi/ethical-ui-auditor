from pathlib import Path

import pytest

from app.visual_analysis.model import DarkPatternVisualDetector, VisualModelUnavailableError


def test_missing_visual_weights_fail_with_an_actionable_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.pt"

    with pytest.raises(VisualModelUnavailableError, match="weights are unavailable"):
        DarkPatternVisualDetector(model_path=missing)

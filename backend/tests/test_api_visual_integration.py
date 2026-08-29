from types import SimpleNamespace

import pytest

from app.schemas import ScanRequest
from app.frontend_analysis.schemas import FrontendBehaviorFinding, FrontendBehaviorReport
from app.scans import service


class FakeClassifier:
    version = "bert-test"
    validation_warning = None

    def predict(self, text: str):
        return [SimpleNamespace(category="false_urgency", confidence=0.8, threshold=0.5)]


class FakeVisualDetector:
    version = "yolo-test"
    confidence = 0.25

    def predict(self, screenshot):
        return [
            SimpleNamespace(
                cue="COUNTDOWN TIMER",
                confidence=0.75,
                bounding_box={"x": 0, "y": 0, "width": 100, "height": 50},
            )
        ]


@pytest.mark.asyncio
async def test_scan_response_contains_visual_cues_and_fusion_links(monkeypatch, tmp_path) -> None:
    runtime = tmp_path / "runtime_data"
    monkeypatch.setattr(service, "RUNTIME_DATA_DIR", runtime)
    monkeypatch.setattr(service, "get_classifier", lambda: FakeClassifier())
    monkeypatch.setattr(service, "get_visual_detector", lambda: FakeVisualDetector())
    monkeypatch.setattr(service, "extract_text_blocks", lambda path: [])

    async def fake_capture(
        url: str,
        max_pages: int,
        scroll_steps: int,
        analyse_behavior: bool,
        behavior_observation_seconds: int,
    ):
        assert analyse_behavior is True
        assert behavior_observation_seconds == 30
        return "scan-test", [
            {
                "url": url,
                "title": "Timer",
                "screenshot_path": "runtime_data/scans/scan-test/page.png",
                "dom_blocks": [
                    {
                        "text": "Hurry, offer ends soon",
                        "source": "dom",
                        "selector": ".timer",
                        "bounding_box": {"x": 10, "y": 10, "width": 40, "height": 10},
                    }
                ],
                "frontend_behavior": FrontendBehaviorReport(
                    status="completed",
                    observation_seconds=5,
                    findings=[FrontendBehaviorFinding(
                        category="resetting_countdown",
                        dark_pattern_category="false_urgency",
                        status="detected",
                        severity="high",
                        score=95,
                        confidence=.95,
                        rationale="The timer reset across sessions.",
                    )],
                ),
            }
        ], []

    monkeypatch.setattr(service, "capture_website", fake_capture)
    response = await service.perform_scan(ScanRequest(url="https://example.com", max_pages=1, scroll_steps=0))

    assert response.status == "completed"
    assert response.pages[0].visual_cues[0].cue == "COUNTDOWN TIMER"
    assert response.pages[0].visual_cues[0].supports_categories == ["false_urgency"]
    assert response.pages[0].fusion_links[0].category == "false_urgency"
    assert response.pages[0].fusion_links[0].spatial_overlap == 1.0
    behavior = response.pages[0].frontend_behavior.findings[0]
    assert behavior.bert_categories == ["false_urgency"]
    assert behavior.visual_cues == ["COUNTDOWN TIMER"]

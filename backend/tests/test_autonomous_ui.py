from app.flow_analysis.ui import flow_analysis_ui


def _page() -> str:
    return flow_analysis_ui().body.decode("utf-8")


def test_autonomous_workspace_is_url_first_and_safe_by_default() -> None:
    page = _page()

    assert "Start autonomous analysis" in page
    assert 'id="targetUrl"' in page
    assert '<option value="evidence_only">' in page
    assert "Safe by default" in page
    assert "clearSecrets()" in page


def test_autonomous_workspace_targets_the_documented_async_apis() -> None:
    page = _page()

    assert "/api/v1/flow-runs/autonomous" in page
    assert "/api/v1/autonomous-flow-runs/${currentRun}" in page
    assert "/api/v1/autonomous-flow-review-queue" in page
    assert "/api/v1/autonomous-flow-comparisons" in page
    assert "/api/v1/autonomous-findings/${box.dataset.finding}/review" in page
    assert "/screenshots/${encodeURIComponent(filename)}" in page


def test_autonomous_workspace_exposes_evidence_and_regression_views() -> None:
    page = _page()

    assert "Confidence-gated review queue" in page
    assert "Exploration state graph" in page
    assert "Regression comparison" in page
    assert "Supporting models" in page
    assert "Controlled benchmarks and manual paired definitions" in page
    assert "Dynamic frontend behaviour" in page
    assert "Dynamic frontend research controls" in page
    assert "/behavior-benchmarks/genuine-countdown" in page
    assert "/behavior-benchmarks/fake-countdown" in page
    assert "/behavior-benchmarks/manipulative-store" in page

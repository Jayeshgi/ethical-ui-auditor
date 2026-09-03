from __future__ import annotations

from app.flow_analysis.autonomous_schemas import (
    AutonomousFlowRequest,
    AutonomousFlowRequestSummary,
    SitePageAnalysis,
)
from app.flow_analysis.site_crawler import _aggregate_behavior, _canonical_link
from app.frontend_analysis.schemas import FrontendBehaviorFinding, FrontendBehaviorReport


def test_full_site_request_is_safely_persisted_without_credentials() -> None:
    request = AutonomousFlowRequest(
        url="https://shop.example.com/start",
        scope="full_site",
        policy={"max_pages": 60, "crawl_depth": 4},
    )

    summary = AutonomousFlowRequestSummary.from_request(request)

    assert summary.scope == "full_site"
    assert summary.policy.max_pages == 60
    assert summary.policy.crawl_depth == 4
    assert summary.has_credentials is False


def test_canonical_link_stays_same_origin_and_rejects_secrets_or_assets() -> None:
    origin = "https://shop.example.com"

    assert _canonical_link("/products#top", "https://shop.example.com/", origin, "evidence_only") == (
        "https://shop.example.com/products"
    )
    assert _canonical_link("https://other.example/products", "https://shop.example.com/", origin, "evidence_only") is None
    assert _canonical_link("/account?token=secret", "https://shop.example.com/", origin, "evidence_only") is None
    assert _canonical_link("/image.png", "https://shop.example.com/", origin, "evidence_only") is None
    assert _canonical_link("/delete/account", "https://shop.example.com/", origin, "evidence_only") is None
    assert _canonical_link("/delete/account", "https://shop.example.com/", origin, "controlled") == (
        "https://shop.example.com/delete/account"
    )


def test_site_behavior_aggregation_preserves_affected_page() -> None:
    finding = FrontendBehaviorFinding(
        page_url="https://shop.example.com/sale",
        category="resetting_countdown",
        dark_pattern_category="false_urgency",
        status="detected",
        severity="high",
        score=95,
        confidence=0.95,
        rationale="The timer reset.",
    )
    page = SitePageAnalysis(
        url="https://shop.example.com/sale",
        status="scanned",
        frontend_behavior=FrontendBehaviorReport(
            status="completed",
            observation_seconds=5,
            findings=[finding],
        ),
    )

    aggregate = _aggregate_behavior([page])

    assert aggregate.status == "completed"
    assert aggregate.findings[0].page_url == "https://shop.example.com/sale"
    assert "Aggregated same-origin site evidence" in aggregate.note

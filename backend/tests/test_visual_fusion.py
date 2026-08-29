from app.schemas import BoundingBox, Finding, VisualCue
from app.visual_analysis.fusion import fuse_evidence, supported_categories


def finding(category: str, box: BoundingBox) -> Finding:
    return Finding(
        category=category,
        model_confidence=0.8,
        threshold=0.5,
        model_version="bert-test",
        phrase="test evidence",
        source="dom",
        bounding_box=box,
    )


def cue(name: str, box: BoundingBox) -> VisualCue:
    return VisualCue(
        cue=name,
        model_confidence=0.75,
        threshold=0.25,
        model_version="yolo-test",
        bounding_box=box,
        supports_categories=supported_categories(name),
    )


def test_compatible_spatial_evidence_is_linked_without_combining_scores() -> None:
    findings = [finding("false_urgency", BoundingBox(x=20, y=20, width=40, height=10))]
    cues = [cue("COUNTDOWN TIMER", BoundingBox(x=10, y=10, width=100, height=50))]

    links = fuse_evidence(findings, cues)

    assert len(links) == 1
    assert links[0].category == "false_urgency"
    assert links[0].spatial_overlap == 1.0
    assert findings[0].model_confidence == 0.8
    assert cues[0].model_confidence == 0.75


def test_unmapped_visual_cue_remains_standalone_evidence() -> None:
    findings = [finding("obstruction", BoundingBox(x=0, y=0, width=50, height=50))]
    cues = [cue("NAGGING", BoundingBox(x=0, y=0, width=50, height=50))]

    assert supported_categories("NAGGING") == []
    assert fuse_evidence(findings, cues) == []


def test_compatible_but_distant_evidence_is_not_linked() -> None:
    findings = [finding("false_scarcity", BoundingBox(x=0, y=0, width=20, height=20))]
    cues = [cue("LOW STOCK MESSAGE", BoundingBox(x=100, y=100, width=20, height=20))]

    assert fuse_evidence(findings, cues) == []


def test_high_demand_documents_multiple_possible_support_relationships() -> None:
    assert supported_categories("HIGH DEMAND MESSAGE") == ["false_scarcity", "social_proof"]

from app.text_analysis.evidence_rules import evidence_for_text


def test_extracts_evidence_without_creating_model_predictions() -> None:
    evidence = evidence_for_text("Hurry! Only 2 items left. This offer ends soon.")
    assert set(evidence) == {"false_urgency", "false_scarcity"}


def test_neutral_text_has_no_candidate() -> None:
    assert evidence_for_text("Read our delivery policy.") == {}

from __future__ import annotations

from app.flow_analysis.autonomous_schemas import (
    AutonomousFinding,
    AutonomousPathResult,
    ConfidenceBreakdown,
)
from app.flow_analysis.mechanisms import mechanism_weight


AUTONOMOUS_PIPELINE_VERSION = "autonomous-flow-and-runtime-v2"


def roach_motel_finding(
    acquisition: AutonomousPathResult,
    exit_path: AutonomousPathResult,
    mechanisms: list[AutonomousFinding],
    confidence: ConfidenceBreakdown,
    pairing_confidence: float,
) -> AutonomousFinding:
    acquisition_effort = acquisition.metrics.effort_score
    exit_effort = exit_path.metrics.effort_score
    difference = exit_effort - acquisition_effort
    ratio = exit_effort / max(acquisition_effort, 1.0)
    direct_mechanisms = [item for item in mechanisms if item.status == "detected"]
    terminal_adequate = (
        (acquisition.terminal.verified or acquisition.terminal.commit_frontier)
        and (exit_path.terminal.verified or exit_path.terminal.commit_frontier)
    )
    comparable = pairing_confidence >= 0.65 and terminal_adequate
    candidate = comparable and difference >= 3.0 and ratio >= 1.75 and bool(direct_mechanisms)
    raw_score = max(0.0, difference) * 3.5 + max(0.0, ratio - 1.0) * 12.0 + mechanism_weight(direct_mechanisms)
    score = min(100.0, raw_score)

    if confidence.gate == "inconclusive" or not comparable:
        status = "inconclusive"
        severity = "none"
        score = min(score, 35.0)
    elif candidate:
        status = "detected"
        severity = "high" if score >= 70 else "medium" if score >= 45 else "low"
    else:
        status = "not_detected"
        severity = "none"

    mechanism_names = [item.category for item in direct_mechanisms]
    rationale = (
        f"Equivalent paired journey confidence was {pairing_confidence:.2f}. Exit effort was {ratio:.2f}x "
        f"acquisition effort with a {difference:.2f}-point difference. Direct exit mechanisms: "
        f"{', '.join(mechanism_names) if mechanism_names else 'none'}. Publication gate: {confidence.gate}."
    )
    return AutonomousFinding(
        category="roach_motel",
        status=status,
        severity=severity,
        score=round(score, 2),
        confidence=confidence.overall,
        evidence_refs=[reference for item in direct_mechanisms for reference in item.evidence_refs],
        rationale=rationale,
    )

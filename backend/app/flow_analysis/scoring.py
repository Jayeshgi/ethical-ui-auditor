from __future__ import annotations

from collections import Counter

from app.flow_analysis.schemas import FlowFinding, FlowMetrics, FlowRunResult, FlowStepResult


CALIBRATION_VERSION = "flow-obstruction-provisional-v2"

OBSTRUCTION_WEIGHTS: dict[str, float] = {
    "forced_reason": 3.0,
    "retention_interstitial": 3.0,
    "repeated_confirmation": 2.0,
    "channel_switch": 5.0,
    "forced_contact": 5.0,
    "dead_end": 4.0,
    "delayed_execution": 4.0,
    "information_overload": 1.0,
    "hidden_exit_control": 3.0,
    "redirect_loop": 4.0,
}

JUSTIFIED_WEIGHTS: dict[str, float] = {
    "reauthentication": 2.0,
    "security_verification": 2.0,
    "irreversible_action_warning": 1.5,
    "data_export_option": 1.0,
    "refund_explanation": 1.0,
}


def metrics_for_steps(steps: list[FlowStepResult]) -> FlowMetrics:
    completed_steps = [step for step in steps if step.status == "completed"]
    meaningful = [step for step in completed_steps if step.action in {"click", "fill", "select", "check"}]
    # Count a signal once per page. Filling several fields on one screen must
    # not multiply a single banner or warning into many independent findings.
    tags = Counter(
        tag for url, tag in {(step.url_after, tag) for step in completed_steps for tag in step.evidence.obstruction_tags}
    )
    justified = Counter(
        tag for url, tag in {(step.url_after, tag) for step in completed_steps for tag in step.evidence.justified_tags}
    )
    obstruction_weight = sum(OBSTRUCTION_WEIGHTS.get(tag, 1.0) * count for tag, count in tags.items())
    justified_weight = sum(JUSTIFIED_WEIGHTS.get(tag, 1.0) * count for tag, count in justified.items())
    clicks = sum(step.action == "click" for step in meaningful)
    form_fields = sum(step.action in {"fill", "select", "check"} for step in meaningful)
    transitions = sum(step.page_transition for step in completed_steps)
    active_time = sum(step.duration_ms for step in meaningful)
    # Active time has a deliberately small and capped influence; network latency
    # must not turn a slow website into an obstruction finding.
    time_cost = min(active_time / 30_000.0, 3.0)
    # Legitimate safeguards can explain apparent obstruction, but they cannot
    # erase the real clicks, fields, navigation, or time a person expended.
    net_obstruction = max(0.0, obstruction_weight - justified_weight)
    effort = len(meaningful) + 0.5 * transitions + 0.5 * form_fields + net_obstruction + time_cost
    return FlowMetrics(
        meaningful_actions=len(meaningful),
        clicks=clicks,
        form_fields=form_fields,
        page_transitions=transitions,
        active_time_ms=active_time,
        obstruction_weight=round(obstruction_weight, 2),
        justified_weight=round(justified_weight, 2),
        effort_score=round(effort, 2),
        completed=bool(steps) and all(step.status == "completed" for step in steps),
    )


def compare_flows(acquisition: FlowRunResult, exit_flow: FlowRunResult) -> FlowFinding:
    entry_effort = acquisition.metrics.effort_score
    exit_effort = exit_flow.metrics.effort_score
    difference = exit_effort - entry_effort
    ratio = exit_effort / max(entry_effort, 1.0)
    obstruction_tags = [tag for step in exit_flow.steps for tag in step.evidence.obstruction_tags]
    evidence = list(dict.fromkeys(obstruction_tags))
    completed = acquisition.metrics.completed and exit_flow.metrics.completed

    raw_score = max(0.0, difference) * 4.0 + max(0.0, ratio - 1.0) * 12.0 + len(evidence) * 5.0
    score = min(100.0, raw_score) if completed else min(35.0, raw_score)
    # Require both relative and absolute asymmetry. This avoids treating a
    # harmless one-step versus two-step difference as a strong finding.
    candidate = completed and difference >= 3.0 and ratio >= 1.75 and bool(evidence)
    if candidate and score >= 70:
        severity = "high"
    elif candidate and score >= 45:
        severity = "medium"
    elif candidate:
        severity = "low"
    else:
        severity = "none"
    confidence = 0.9 if completed and evidence else 0.7 if completed else 0.35
    rationale = (
        f"Exit effort was {ratio:.2f}x acquisition effort with a {difference:.2f}-point difference. "
        f"Detected exit-flow obstruction signals: {', '.join(evidence) if evidence else 'none'}. "
        "This is a candidate design finding, not an automatic legal conclusion."
    )
    return FlowFinding(
        severity=severity,
        score=round(score, 2),
        confidence=confidence,
        candidate=candidate,
        effort_difference=round(difference, 2),
        effort_ratio=round(ratio, 2),
        evidence=evidence,
        rationale=rationale,
        calibration_version=CALIBRATION_VERSION,
    )

from __future__ import annotations

from collections import Counter, defaultdict
import re

from app.flow_analysis.autonomous_schemas import (
    AutonomousFinding,
    AutonomousPathResult,
    GraphEdge,
    GraphNode,
    MechanismCategory,
)


MECHANISM_WEIGHTS: dict[MechanismCategory, float] = {
    "hidden_exit": 14.0,
    "forced_reason": 14.0,
    "retention_obstruction": 13.0,
    "repeated_confirmation": 12.0,
    "channel_switch": 20.0,
    "forced_contact": 20.0,
    "delayed_execution": 16.0,
    "redirect_loop": 18.0,
    "dead_end": 16.0,
    "unnecessary_form_burden": 12.0,
    "information_overload": 8.0,
    "policy_interface_mismatch": 16.0,
}

LEGACY_TAG_MAPPING: dict[str, MechanismCategory] = {
    "hidden_exit_control": "hidden_exit",
    "forced_reason": "forced_reason",
    "retention_interstitial": "retention_obstruction",
    "repeated_confirmation": "repeated_confirmation",
    "channel_switch": "channel_switch",
    "forced_contact": "forced_contact",
    "delayed_execution": "delayed_execution",
    "redirect_loop": "redirect_loop",
    "dead_end": "dead_end",
    "information_overload": "information_overload",
    "policy_interface_mismatch": "policy_interface_mismatch",
}


def _finding(
    category: MechanismCategory,
    *,
    confidence: float,
    evidence: list[str],
    rationale: str,
) -> AutonomousFinding:
    score = min(100.0, MECHANISM_WEIGHTS[category] * max(1, len(evidence)))
    severity = "high" if score >= 55 else "medium" if score >= 30 else "low"
    return AutonomousFinding(
        category=category,
        status="detected",
        severity=severity,
        score=round(score, 2),
        confidence=round(confidence, 3),
        evidence_refs=list(dict.fromkeys(evidence)),
        rationale=rationale,
    )


def detect_mechanisms(
    acquisition: AutonomousPathResult,
    exit_path: AutonomousPathResult,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    loop_state_ids: list[str] | None = None,
    dead_end_state_ids: list[str] | None = None,
) -> list[AutonomousFinding]:
    """Extract structural exit mechanisms without using BERT/YOLO as effort."""

    findings: dict[MechanismCategory, AutonomousFinding] = {}
    exit_state_ids = set(exit_path.state_ids)
    exit_nodes = [node for node in nodes if node.state_id in exit_state_ids and node.phase == "exit"]
    exit_edges = [edge for edge in edges if edge.phase == "exit"]

    legacy_refs: dict[MechanismCategory, list[str]] = defaultdict(list)
    for step in exit_path.steps:
        for tag in step.evidence.obstruction_tags:
            mapped = LEGACY_TAG_MAPPING.get(tag)
            if mapped:
                legacy_refs[mapped].append(f"step:{step.index}:{tag}")
    for category, refs in legacy_refs.items():
        findings[category] = _finding(
            category,
            confidence=0.76,
            evidence=refs,
            rationale=f"Exit-path evidence detected {category.replace('_', ' ')}.",
        )

    # Graph transitions can carry structural tags even when a compatibility
    # FlowStepResult was not produced (for example a blocked commit frontier).
    edge_refs: dict[MechanismCategory, list[str]] = defaultdict(list)
    for edge in exit_edges:
        for tag in edge.evidence_tags:
            mapped = LEGACY_TAG_MAPPING.get(tag)
            if mapped:
                edge_refs[mapped].append(f"edge:{edge.edge_id}:{tag}")
    for category, refs in edge_refs.items():
        combined = [*(findings[category].evidence_refs if category in findings else []), *refs]
        findings[category] = _finding(
            category,
            confidence=max(findings[category].confidence if category in findings else 0.0, 0.8),
            evidence=combined,
            rationale=f"Exit-graph evidence detected {category.replace('_', ' ')}.",
        )

    # A reason is structural only when the field itself is required.
    required_reason_controls = [
        (node, control)
        for node in exit_nodes
        for control in node.controls
        if control.required
        and re.search(r"\b(?:reason|why\b.{0,80}\bleav(?:e|ing)?|feedback)\b", control.name, re.I)
    ]
    if required_reason_controls:
        refs = [f"state:{node.state_id}:control:{control.control_id}" for node, control in required_reason_controls]
        findings["forced_reason"] = _finding(
            "forced_reason",
            confidence=0.92,
            evidence=refs,
            rationale="The exit journey requires a reason or leaving-feedback field before progression.",
        )

    # Distinct state confirmations avoid collapsing multiple modals on one URL.
    confirmation_nodes = [
        node
        for node in exit_nodes
        if re.search(r"\b(are you sure|confirm (?:cancellation|deletion)|really want|last chance)\b", " ".join(node.headings) + " " + node.dialog_text, re.I)
    ]
    if len({node.state_id for node in confirmation_nodes}) >= 2:
        findings["repeated_confirmation"] = _finding(
            "repeated_confirmation",
            confidence=0.9,
            evidence=[f"state:{node.state_id}" for node in confirmation_nodes],
            rationale="The exit journey contains multiple distinct blocking confirmation states.",
        )

    retention_nodes = [
        node
        for node in exit_nodes
        if re.search(
            r"\b(?:stay (?:with us|subscribed|a member)|keep (?:your|my) (?:account|plan|subscription|membership)|"
            r"pause instead|special offer|before you go|(?:don't|do not) (?:cancel|leave)|discount (?:to|if you) stay)\b",
            " ".join(node.headings) + " " + node.dialog_text,
            re.I,
        )
    ]
    if retention_nodes:
        findings["retention_obstruction"] = _finding(
            "retention_obstruction",
            confidence=0.84,
            evidence=[f"state:{node.state_id}" for node in retention_nodes],
            rationale="A retention offer interrupts the selected exit path.",
        )

    channel_nodes = []
    for node in exit_nodes:
        node_text = " ".join(node.headings) + " " + node.dialog_text
        if re.search(
            r"\b(?:call (?:us|support)|phone|visit (?:a|our) store|send (?:a )?letter|postal mail)\b"
            r".{0,90}\b(?:cancel|delete|close|unsubscribe|leave|disconnect|return)\b|"
            r"\b(?:cancel|delete|close|unsubscribe|leave|disconnect|return)\b.{0,90}"
            r"\b(?:by (?:phone|mail)|call (?:us|support)|visit (?:a|our) store|postal mail)\b",
            node_text,
            re.I,
        ):
            channel_nodes.append(node)
    if channel_nodes:
        findings["channel_switch"] = _finding(
            "channel_switch",
            confidence=0.91,
            evidence=[f"state:{node.state_id}" for node in channel_nodes],
            rationale="The online exit journey requires switching to phone, store, or postal mail.",
        )

    forced_contact_nodes = [
        node
        for node in exit_nodes
        if re.search(r"\b(must (?:contact|chat|speak)|contact support to|speak to an agent)\b", " ".join(node.headings) + " " + node.dialog_text, re.I)
    ]
    if forced_contact_nodes:
        findings["forced_contact"] = _finding(
            "forced_contact",
            confidence=0.88,
            evidence=[f"state:{node.state_id}" for node in forced_contact_nodes],
            rationale="Exit completion requires contacting a support agent.",
        )

    delayed_nodes = []
    for node in exit_nodes:
        node_text = " ".join(node.headings) + " " + node.dialog_text
        has_delay = re.search(
            r"\b(?:within|after|up to|takes?|may take) \d+ (?:business )?days?\b|"
            r"\bscheduled for (?:deletion|cancellation)\b|\bcooling[ -]off\b",
            node_text,
            re.I,
        )
        has_exit_context = re.search(
            r"\b(?:cancel(?:lation)?|delet(?:e|ion)|clos(?:e|ure)|unsubscribe|disconnect|"
            r"deactivat(?:e|ion)|return|refund|revoke|withdraw)\b",
            node_text,
            re.I,
        )
        if has_delay and has_exit_context:
            delayed_nodes.append(node)
    if delayed_nodes:
        findings["delayed_execution"] = _finding(
            "delayed_execution",
            confidence=0.86,
            evidence=[f"state:{node.state_id}" for node in delayed_nodes],
            rationale="The interface explicitly postpones the requested exit action.",
        )

    if loop_state_ids:
        findings["redirect_loop"] = _finding(
            "redirect_loop",
            confidence=0.9,
            evidence=[f"state:{state_id}" for state_id in loop_state_ids],
            rationale="The exit graph revisits states without progress toward the goal.",
        )
    if dead_end_state_ids:
        findings["dead_end"] = _finding(
            "dead_end",
            confidence=0.85,
            evidence=[f"state:{state_id}" for state_id in dead_end_state_ids],
            rationale="An exit route reaches a non-terminal state with no safe continuation.",
        )

    if exit_path.required_fields >= acquisition.required_fields + 2:
        findings["unnecessary_form_burden"] = _finding(
            "unnecessary_form_burden",
            confidence=0.82,
            evidence=[f"required-fields:acquisition={acquisition.required_fields}:exit={exit_path.required_fields}"],
            rationale="The exit path requires materially more mandatory form fields than acquisition.",
        )

    if exit_path.control_rank and exit_path.control_rank >= 15:
        findings["information_overload"] = _finding(
            "information_overload",
            confidence=0.72,
            evidence=[f"exit-control-rank:{exit_path.control_rank}"],
            rationale="The selected exit control was buried among many unrelated interactive controls.",
        )

    hidden_steps = [
        step
        for step in exit_path.steps
        if step.evidence.target_presentation
        and (
            not step.evidence.target_presentation.visible
            or step.evidence.target_presentation.opacity < 0.55
            or step.evidence.target_presentation.font_size_px < 11
            or step.evidence.target_presentation.viewport_area_ratio < 0.00008
        )
    ]
    if hidden_steps:
        findings["hidden_exit"] = _finding(
            "hidden_exit",
            confidence=0.86,
            evidence=[f"step:{step.index}:target-presentation" for step in hidden_steps],
            rationale="The exit control has materially poor visibility or prominence.",
        )

    # Keep deterministic output order for persistence, tests, and UI.
    order = list(MECHANISM_WEIGHTS)
    return [findings[category] for category in order if category in findings]


def mechanism_weight(findings: list[AutonomousFinding]) -> float:
    counts = Counter(finding.category for finding in findings if finding.status == "detected")
    return sum(MECHANISM_WEIGHTS.get(category, 0) * count for category, count in counts.items())

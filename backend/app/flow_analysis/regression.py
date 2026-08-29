from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from app.database import utc_now
from app.flow_analysis.autonomous_schemas import (
    AutonomousFlowResult,
    BehaviorRegression,
    FlowComparisonResult,
    GoalPairAnalysis,
    GoalRegression,
)


def _normalized_origin(url: str) -> str:
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if not scheme or not hostname:
        return ""
    host = f"[{hostname}]" if ":" in hostname else hostname
    try:
        port = parsed.port
    except ValueError:
        return ""
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    return f"{scheme}://{host}"


def compare_autonomous_results(
    baseline: AutonomousFlowResult,
    candidate: AutonomousFlowResult,
    comparison_id: str | None = None,
) -> FlowComparisonResult:
    comparison_id = comparison_id or str(uuid.uuid4())
    warnings: list[str] = []
    baseline_origin = _normalized_origin(baseline.url)
    candidate_origin = _normalized_origin(candidate.url)
    if baseline_origin != candidate_origin:
        warnings.append("Runs use different origins; regression comparison is inconclusive.")
    if baseline.pipeline_version != candidate.pipeline_version:
        warnings.append("Runs use different analysis pipeline versions; regression comparison is inconclusive.")

    baseline_goals = {goal.signature: goal for goal in baseline.goals}
    candidate_goals = {goal.signature: goal for goal in candidate.goals}
    matched: list[tuple[str, GoalPairAnalysis | None, GoalPairAnalysis | None, str]] = []
    exact_signatures = set(baseline_goals).intersection(candidate_goals)
    for signature in sorted(exact_signatures):
        matched.append((signature, baseline_goals[signature], candidate_goals[signature], ""))

    # A redesign can legitimately change URL-derived object tokens even though
    # the product still exposes one unambiguous goal of that family.  Pair that
    # unique remainder by family; never guess when either side has multiples.
    remaining_left = [goal for key, goal in baseline_goals.items() if key not in exact_signatures]
    remaining_right = [goal for key, goal in candidate_goals.items() if key not in exact_signatures]
    for family in sorted({goal.family for goal in [*remaining_left, *remaining_right]}):
        left_family = [goal for goal in remaining_left if goal.family == family]
        right_family = [goal for goal in remaining_right if goal.family == family]
        if len(left_family) == 1 and len(right_family) == 1:
            matched.append(
                (
                    f"{family}:unique-family-match",
                    left_family[0],
                    right_family[0],
                    "The unique goal in this family was matched across a changed object signature. ",
                )
            )
            remaining_left.remove(left_family[0])
            remaining_right.remove(right_family[0])
    matched.extend((goal.signature, goal, None, "") for goal in remaining_left)
    matched.extend((goal.signature, None, goal, "") for goal in remaining_right)

    regressions: list[GoalRegression] = []
    paired_confidences: list[float] = []
    for signature, left, right, match_note in sorted(matched, key=lambda item: item[0]):
        if left is None or right is None:
            regressions.append(
                GoalRegression(
                    signature=signature,
                    verdict="inconclusive",
                    acquisition_effort_delta=0,
                    exit_effort_delta=0,
                    effort_ratio_delta=0,
                    rationale="The goal signature was not discovered in both runs.",
                )
            )
            continue
        paired_confidences.append(min(left.confidence_gate.overall, right.confidence_gate.overall))
        left_ratio = left.exit.metrics.effort_score / max(left.acquisition.metrics.effort_score, 1.0)
        right_ratio = right.exit.metrics.effort_score / max(right.acquisition.metrics.effort_score, 1.0)
        acquisition_delta = right.acquisition.metrics.effort_score - left.acquisition.metrics.effort_score
        exit_delta = right.exit.metrics.effort_score - left.exit.metrics.effort_score
        ratio_delta = right_ratio - left_ratio
        old_mechanisms = {item.category for item in left.mechanism_findings if item.status == "detected"}
        new_mechanisms = {item.category for item in right.mechanism_findings if item.status == "detected"}
        added, resolved = sorted(new_mechanisms - old_mechanisms), sorted(old_mechanisms - new_mechanisms)
        if left.confidence_gate.gate == "inconclusive" or right.confidence_gate.gate == "inconclusive":
            verdict = "inconclusive"
        elif exit_delta >= 2.0 or ratio_delta >= 0.5 or added:
            verdict = "regressed"
        elif exit_delta <= -2.0 or ratio_delta <= -0.5 or resolved:
            verdict = "improved"
        else:
            verdict = "unchanged"
        regressions.append(
            GoalRegression(
                signature=signature,
                verdict=verdict,
                acquisition_effort_delta=round(acquisition_delta, 2),
                exit_effort_delta=round(exit_delta, 2),
                effort_ratio_delta=round(ratio_delta, 2),
                added_mechanisms=added,
                resolved_mechanisms=resolved,
                rationale=(
                    f"{match_note}Exit effort changed by {exit_delta:.2f}; effort ratio changed by {ratio_delta:.2f}. "
                    f"Added mechanisms: {', '.join(added) if added else 'none'}; resolved: "
                    f"{', '.join(resolved) if resolved else 'none'}."
                ),
            )
        )

    status_rank = {"not_detected": 0, "inconclusive": 1, "suspicious": 2, "detected": 3}
    baseline_behavior = {
        item.category: item
        for item in sorted(baseline.frontend_behavior.findings, key=lambda value: value.confidence)
    }
    candidate_behavior = {
        item.category: item
        for item in sorted(candidate.frontend_behavior.findings, key=lambda value: value.confidence)
    }
    behavior_regressions: list[BehaviorRegression] = []
    behavior_confidences: list[float] = []
    for category in sorted(set(baseline_behavior) | set(candidate_behavior)):
        left, right = baseline_behavior.get(category), candidate_behavior.get(category)
        left_status = left.status if left else None
        right_status = right.status if right else None
        left_rank, right_rank = status_rank[left_status or "not_detected"], status_rank[right_status or "not_detected"]
        if right_rank > left_rank:
            behavior_verdict = "regressed"
        elif right_rank < left_rank:
            behavior_verdict = "improved"
        elif right_status == "inconclusive" or left_status == "inconclusive":
            behavior_verdict = "inconclusive"
        else:
            behavior_verdict = "unchanged"
        left_confidence = left.confidence if left else 0.0
        right_confidence = right.confidence if right else 0.0
        present_confidences = [item.confidence for item in (left, right) if item is not None]
        behavior_confidences.append(min(present_confidences))
        behavior_regressions.append(
            BehaviorRegression(
                category=category,
                verdict=behavior_verdict,
                baseline_status=left_status,
                candidate_status=right_status,
                confidence_delta=round(right_confidence - left_confidence, 3),
                rationale=(
                    f"Dynamic frontend status changed from {left_status or 'not observed'} to {right_status or 'not observed'}; "
                    "the comparison uses repeated runtime observations rather than source-code presence alone."
                ),
            )
        )

    all_verdicts = [item.verdict for item in regressions] + [item.verdict for item in behavior_regressions]
    if warnings or not all_verdicts or all(item == "inconclusive" for item in all_verdicts):
        verdict = "inconclusive"
    elif any(item == "regressed" for item in all_verdicts):
        verdict = "regressed"
    elif any(item == "improved" for item in all_verdicts):
        verdict = "improved"
    else:
        verdict = "unchanged"
    all_confidences = [*paired_confidences, *behavior_confidences]
    confidence = min(all_confidences) if all_confidences else 0.0
    if baseline_origin != candidate_origin or baseline.pipeline_version != candidate.pipeline_version:
        confidence = 0.0
    elif verdict == "inconclusive":
        # Missing/unverified goal pairs cannot support a high-confidence overall
        # regression claim even if another paired goal happened to be stable.
        confidence = min(confidence, 0.49)
    return FlowComparisonResult(
        comparison_id=comparison_id,
        baseline_run_id=baseline.run_id,
        candidate_run_id=candidate.run_id,
        verdict=verdict,
        confidence=round(confidence, 3),
        goal_regressions=regressions,
        behavior_regressions=behavior_regressions,
        warnings=warnings,
        created_at=utc_now(),
    )

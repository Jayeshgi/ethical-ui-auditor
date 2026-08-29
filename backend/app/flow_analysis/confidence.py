"""Confidence aggregation and publication gates for autonomous flow results."""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from app.flow_analysis.autonomous_schemas import (
    AutomationLimitation,
    ConfidenceBreakdown,
    GoalTerminalEvidence,
    LimitationCode,
    PublicationGate,
)


# Goal pairing and terminal evidence carry most weight: a stable replay of the
# wrong goal pair must not create a confident roach-motel finding.
CONFIDENCE_WEIGHTS: dict[str, float] = {
    "goal_equivalence": 0.25,
    "acquisition_terminal": 0.20,
    "exit_terminal": 0.20,
    "replay_stability": 0.15,
    "selector_stability": 0.10,
    "evidence_quality": 0.10,
}

AUTO_REPORT_THRESHOLD = 0.85
CAUTION_THRESHOLD = 0.65
INCOMPLETE_FLOW_CAP = 0.64

_CAP_LIMITATIONS: dict[str, tuple[float, str]] = {
    "credentials_required": (INCOMPLETE_FLOW_CAP, "Required credentials were not supplied"),
    "authentication_failed": (INCOMPLETE_FLOW_CAP, "Authentication could not be completed"),
    "captcha_required": (INCOMPLETE_FLOW_CAP, "A CAPTCHA prevented autonomous verification"),
    "mfa_required": (INCOMPLETE_FLOW_CAP, "MFA prevented autonomous verification"),
    "email_verification_required": (INCOMPLETE_FLOW_CAP, "Email verification was not completed"),
    "payment_required": (INCOMPLETE_FLOW_CAP, "A payment boundary prevented safe verification"),
}


def _unit_interval(name: str, value: float) -> float:
    number = float(value)
    if not 0 <= number <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return number


def _terminal_component(
    name: str,
    value: float | GoalTerminalEvidence,
    verified: bool | None,
) -> tuple[float, bool | None]:
    if isinstance(value, GoalTerminalEvidence):
        if verified is None:
            verified = value.verified or value.commit_frontier
        value = value.confidence
    return _unit_interval(name, value), verified


def _limitation_code(value: AutomationLimitation | str) -> str:
    return value.code if isinstance(value, AutomationLimitation) else str(value)


def _publication_gate(overall: float) -> tuple[PublicationGate, str]:
    if overall >= AUTO_REPORT_THRESHOLD:
        return "auto_report", "not_needed"
    if overall >= CAUTION_THRESHOLD:
        return "report_with_caution", "optional"
    return "inconclusive", "recommended"


def build_confidence_breakdown(
    *,
    goal_equivalence: float,
    acquisition_terminal: float | GoalTerminalEvidence,
    exit_terminal: float | GoalTerminalEvidence,
    replay_stability: float | None = None,
    selector_stability: float,
    evidence_quality: float,
    limitations: Iterable[AutomationLimitation | LimitationCode | str] = (),
    replay_attempts: int | None = None,
    replay_successes: int | None = None,
    acquisition_verified: bool | None = None,
    exit_verified: bool | None = None,
    missing_credentials: bool = False,
    calibrated: bool = False,
) -> ConfidenceBreakdown:
    """Aggregate confidence dimensions and apply safety publication caps.

    ``GoalTerminalEvidence`` inputs automatically carry their ``verified``
    state. If scalar terminal confidences are supplied, callers can provide the
    corresponding ``*_verified`` flags. Unresolved credentials, CAPTCHA, MFA,
    email verification, payment, or unverified terminal states cap the result
    below the caution threshold; these conditions are limitations, not proof of
    obstruction.
    """

    goal_equivalence = _unit_interval("goal_equivalence", goal_equivalence)
    acquisition_terminal, acquisition_verified = _terminal_component(
        "acquisition_terminal", acquisition_terminal, acquisition_verified
    )
    exit_terminal, exit_verified = _terminal_component("exit_terminal", exit_terminal, exit_verified)
    selector_stability = _unit_interval("selector_stability", selector_stability)
    evidence_quality = _unit_interval("evidence_quality", evidence_quality)

    if replay_attempts is not None or replay_successes is not None:
        if replay_attempts is None or replay_successes is None:
            raise ValueError("replay_attempts and replay_successes must be supplied together")
        if replay_attempts <= 0:
            raise ValueError("replay_attempts must be greater than zero")
        if replay_successes < 0 or replay_successes > replay_attempts:
            raise ValueError("replay_successes must be between zero and replay_attempts")
        measured_replay_stability = replay_successes / replay_attempts
        if replay_stability is not None and abs(float(replay_stability) - measured_replay_stability) > 1e-9:
            raise ValueError("replay_stability conflicts with replay attempt results")
        replay_stability = measured_replay_stability
    if replay_stability is None:
        replay_stability = 0.5
    replay_stability = _unit_interval("replay_stability", replay_stability)

    dimensions = {
        "goal_equivalence": goal_equivalence,
        "acquisition_terminal": acquisition_terminal,
        "exit_terminal": exit_terminal,
        "replay_stability": replay_stability,
        "selector_stability": selector_stability,
        "evidence_quality": evidence_quality,
    }
    raw_overall = sum(dimensions[name] * weight for name, weight in CONFIDENCE_WEIGHTS.items())

    reasons: list[str] = []
    for name, value in dimensions.items():
        if value < CAUTION_THRESHOLD:
            reasons.append(f"Low {name.replace('_', ' ')} confidence ({value:.2f})")

    codes = list(dict.fromkeys(_limitation_code(limitation) for limitation in limitations))
    if missing_credentials and "credentials_required" not in codes:
        codes.append("credentials_required")

    cap_candidates: list[tuple[float, str, str]] = []
    for code in codes:
        cap = _CAP_LIMITATIONS.get(code)
        if cap is not None:
            cap_candidates.append((cap[0], code, cap[1]))
    if acquisition_verified is False:
        cap_candidates.append((INCOMPLETE_FLOW_CAP, "acquisition_terminal_unverified", "Acquisition terminal was not verified"))
    if exit_verified is False:
        cap_candidates.append((INCOMPLETE_FLOW_CAP, "exit_terminal_unverified", "Exit terminal was not verified"))
    if replay_attempts == 1:
        cap_candidates.append((0.79, "single_replay", "Only one replay attempt was available"))

    caps: list[str] = []
    overall = raw_overall
    for cap_value, code, message in cap_candidates:
        overall = min(overall, cap_value)
        caps.append(f"{code}: confidence capped at {cap_value:.2f}")
        reasons.append(message)

    # Gate on the unrounded number so 0.849999 remains a caution result.
    gate, review = _publication_gate(overall)
    return ConfidenceBreakdown(
        overall=round(overall, 6),
        goal_equivalence=round(goal_equivalence, 6),
        acquisition_terminal=round(acquisition_terminal, 6),
        exit_terminal=round(exit_terminal, 6),
        replay_stability=round(replay_stability, 6),
        selector_stability=round(selector_stability, 6),
        evidence_quality=round(evidence_quality, 6),
        gate=gate,
        review=cast(str, review),
        calibrated=calibrated,
        reasons=list(dict.fromkeys(reasons)),
        caps=list(dict.fromkeys(caps)),
    )


calculate_confidence = build_confidence_breakdown


__all__ = [
    "AUTO_REPORT_THRESHOLD",
    "CAUTION_THRESHOLD",
    "CONFIDENCE_WEIGHTS",
    "INCOMPLETE_FLOW_CAP",
    "build_confidence_breakdown",
    "calculate_confidence",
]

from __future__ import annotations

import re
from pathlib import Path

from app.flow_analysis.schemas import FlowStepEvidence, TargetPresentation


OBSTRUCTION_PATTERNS: dict[str, tuple[str, ...]] = {
    "forced_reason": ("why are you leaving", "reason for leaving", "tell us why", "reason for cancelling", "reason for deleting"),
    "retention_interstitial": ("stay with us", "keep my", "don't leave", "pause instead", "special offer", "before you go"),
    "repeated_confirmation": ("are you sure", "confirm cancellation", "confirm deletion", "really want to", "last chance"),
    "channel_switch": ("call us", "call support", "phone to cancel", "visit a store", "send a letter"),
    "forced_contact": ("contact support to", "speak to an agent", "chat with an agent"),
    "delayed_execution": ("within 30 days", "after 30 days", "scheduled for deletion", "cooling-off period"),
}

JUSTIFIED_PATTERNS: dict[str, tuple[str, ...]] = {
    "reauthentication": ("re-enter your password", "confirm your password", "password required"),
    "security_verification": ("verification code", "two-factor", "security check", "verify your identity"),
    "irreversible_action_warning": ("cannot be undone", "permanently deleted", "irreversible"),
    "data_export_option": ("download your data", "export your data"),
    "refund_explanation": ("refund", "remaining balance"),
}


def _matching_tags(text: str, patterns: dict[str, tuple[str, ...]]) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    return [tag for tag, phrases in patterns.items() if any(phrase in normalized for phrase in phrases)]


def analyse_step_evidence(
    text: str,
    target: dict | None,
    screenshot: Path | None,
    analyse_models: bool,
    phase: str = "exit",
) -> FlowStepEvidence:
    # Exit-friction language is only meaningful in the exit journey. Ads and
    # unrelated promotional copy on acquisition pages otherwise create noise.
    obstruction = _matching_tags(text, OBSTRUCTION_PATTERNS) if phase == "exit" else []
    justified = _matching_tags(text, JUSTIFIED_PATTERNS) if phase == "exit" else []
    presentation = TargetPresentation.model_validate(target) if target else None
    if presentation and presentation.visible:
        if presentation.opacity < 0.55 or presentation.font_size_px < 11 or presentation.viewport_area_ratio < 0.00008:
            obstruction.append("hidden_exit_control")

    bert_categories: list[str] = []
    visual_cues: list[str] = []
    if analyse_models:
        try:
            from app.scans.service import get_classifier

            classifier = get_classifier()
            snippets = [item.strip() for item in re.split(r"[\n\r]+", text) if 3 <= len(item.strip()) <= 300][:20]
            bert_categories = list(
                dict.fromkeys(prediction.category for snippet in snippets for prediction in classifier.predict(snippet))
            )
        except Exception:
            bert_categories = []
        if screenshot and screenshot.exists():
            try:
                from app.scans.service import get_visual_detector

                visual_cues = list(dict.fromkeys(item.cue for item in get_visual_detector().predict(screenshot)))
            except Exception:
                visual_cues = []

    return FlowStepEvidence(
        obstruction_tags=list(dict.fromkeys(obstruction)),
        justified_tags=list(dict.fromkeys(justified)),
        bert_categories=bert_categories,
        visual_cues=visual_cues,
        text_excerpt=re.sub(r"\s+", " ", text).strip()[:1200],
        target_presentation=presentation,
    )

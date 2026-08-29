from __future__ import annotations

from app.schemas import Finding, FusionLink, VisualCue


# These relationships mean "can support", not "is equivalent to". Visual cues
# without a defensible relationship remain standalone visual evidence.
VISUAL_CUE_SUPPORT: dict[str, tuple[str, ...]] = {
    "ACTIVITY MESSAGE": ("social_proof",),
    "COUNTDOWN TIMER": ("false_urgency",),
    "DEFAULT CHOICE": ("forced_consent",),
    "HIGH DEMAND MESSAGE": ("false_scarcity", "social_proof"),
    "LIMITED TIME MESSAGE": ("false_urgency",),
    "LOW STOCK MESSAGE": ("false_scarcity",),
}


def supported_categories(cue: str) -> list[str]:
    return list(VISUAL_CUE_SUPPORT.get(cue, ()))


def _intersection_over_smaller(first, second) -> float:
    first_right, first_bottom = first.x + first.width, first.y + first.height
    second_right, second_bottom = second.x + second.width, second.y + second.height
    intersection_width = max(0.0, min(first_right, second_right) - max(first.x, second.x))
    intersection_height = max(0.0, min(first_bottom, second_bottom) - max(first.y, second.y))
    intersection = intersection_width * intersection_height
    smaller_area = min(first.width * first.height, second.width * second.height)
    return intersection / smaller_area if smaller_area > 0 else 0.0


def fuse_evidence(findings: list[Finding], visual_cues: list[VisualCue], minimum_overlap: float = 0.5) -> list[FusionLink]:
    """Link spatially aligned, taxonomy-compatible evidence without merging probabilities."""
    links: list[FusionLink] = []
    for finding_index, finding in enumerate(findings):
        if finding.bounding_box is None:
            continue
        for cue_index, cue in enumerate(visual_cues):
            if finding.category not in cue.supports_categories:
                continue
            overlap = _intersection_over_smaller(finding.bounding_box, cue.bounding_box)
            if overlap < minimum_overlap:
                continue
            links.append(
                FusionLink(
                    category=finding.category,
                    text_finding_index=finding_index,
                    visual_cue_index=cue_index,
                    spatial_overlap=round(overlap, 4),
                    rationale=f"{cue.cue} visually supports {finding.category}; model probabilities remain separate.",
                )
            )
    return links

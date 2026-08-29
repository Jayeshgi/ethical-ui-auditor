from __future__ import annotations

import asyncio
from functools import lru_cache

from app.core.config import RUNTIME_DATA_DIR
from app.crawler.service import capture_website
from app.frontend_analysis.schemas import FrontendBehaviorReport
from app.ocr.service import OCRUnavailableError, extract_text_blocks
from app.schemas import Finding, PageResult, ScanRequest, ScanResponse, TextBlock, VisualCue
from app.text_analysis.evidence_rules import evidence_for_text
from app.text_analysis.fusion import fuse_text_blocks
from app.text_analysis.model import DarkPatternBertClassifier
from app.visual_analysis.fusion import fuse_evidence, supported_categories
from app.visual_analysis.model import DarkPatternVisualDetector, VisualModelUnavailableError


class BrowserScanError(RuntimeError):
    """Raised when browser capture fails before a useful scan can be returned."""


@lru_cache(maxsize=1)
def get_classifier() -> DarkPatternBertClassifier:
    return DarkPatternBertClassifier()


@lru_cache(maxsize=1)
def get_visual_detector() -> DarkPatternVisualDetector:
    return DarkPatternVisualDetector()


def _analyse_text_blocks(classifier, text_blocks: list[TextBlock]) -> list[Finding]:
    findings: list[Finding] = []
    for block in text_blocks:
        evidence = evidence_for_text(block.text)
        for prediction in classifier.predict(block.text):
            category_evidence = evidence.get(prediction.category, [])
            findings.append(
                Finding(
                    category=prediction.category,
                    model_confidence=round(prediction.confidence, 4),
                    threshold=prediction.threshold,
                    model_version=classifier.version,
                    phrase=category_evidence[0]["phrase"] if category_evidence else block.text,
                    evidence_rules=[item["rule_id"] for item in category_evidence],
                    source=block.source,
                    bounding_box=block.bounding_box,
                    selector=block.selector,
                )
            )
    return findings


async def perform_scan(request: ScanRequest) -> ScanResponse:
    classifier = get_classifier()
    visual_detector: DarkPatternVisualDetector | None = None
    visual_warning: str | None = None
    try:
        visual_detector = get_visual_detector()
    except VisualModelUnavailableError as error:
        visual_warning = str(error)

    try:
        scan_id, captures, warnings = await capture_website(
            str(request.url),
            request.max_pages,
            request.scroll_steps,
            request.analyse_behavior,
            request.behavior_observation_seconds,
        )
    except Exception as error:
        # UnsafeUrlError remains available as the cause for the API to map to 400.
        raise BrowserScanError(f"Browser scan failed: {type(error).__name__}: {error}") from error

    if classifier.validation_warning:
        warnings.append(classifier.validation_warning)
    if visual_warning:
        warnings.append(visual_warning)

    pages: list[PageResult] = []
    for capture in captures:
        screenshot = RUNTIME_DATA_DIR.parent / capture["screenshot_path"]
        try:
            ocr_blocks = await asyncio.to_thread(extract_text_blocks, screenshot)
        except OCRUnavailableError as error:
            warnings.append(str(error))
            ocr_blocks = []
        except Exception as error:
            warnings.append(f"OCR failed for {capture['url']}: {type(error).__name__}: {error}")
            ocr_blocks = []

        fused = fuse_text_blocks(capture["dom_blocks"], ocr_blocks)
        text_blocks = [TextBlock.model_validate(block) for block in fused]
        findings = await asyncio.to_thread(_analyse_text_blocks, classifier, text_blocks)

        visual_cues: list[VisualCue] = []
        if visual_detector is not None:
            try:
                predictions = await asyncio.to_thread(visual_detector.predict, screenshot)
                visual_cues = [
                    VisualCue(
                        cue=prediction.cue,
                        model_confidence=round(prediction.confidence, 4),
                        threshold=visual_detector.confidence,
                        model_version=visual_detector.version,
                        bounding_box=prediction.bounding_box,
                        supports_categories=supported_categories(prediction.cue),
                    )
                    for prediction in predictions
                ]
            except Exception as error:
                warnings.append(f"Visual analysis failed for {capture['url']}: {type(error).__name__}: {error}")

        behavior = FrontendBehaviorReport.model_validate(capture.get("frontend_behavior", {}))
        if behavior.status != "not_requested":
            enriched_behavior = []
            for behavior_finding in behavior.findings:
                parent = behavior_finding.dark_pattern_category
                enriched_behavior.append(
                    behavior_finding.model_copy(
                        update={
                            "bert_categories": list(dict.fromkeys(
                                finding.category for finding in findings if finding.category == parent
                            )),
                            "visual_cues": list(dict.fromkeys(
                                cue.cue for cue in visual_cues if parent in cue.supports_categories
                            )),
                        }
                    )
                )
            behavior = behavior.model_copy(update={"findings": enriched_behavior})

        pages.append(
            PageResult(
                url=capture["url"],
                title=capture["title"],
                screenshot_path=capture["screenshot_path"],
                text_blocks=text_blocks,
                findings=findings,
                visual_cues=visual_cues,
                fusion_links=fuse_evidence(findings, visual_cues),
                frontend_behavior=behavior,
            )
        )
    return ScanResponse(
        scan_id=scan_id,
        status="completed_with_warnings" if warnings else "completed",
        pages=pages,
        warnings=warnings,
    )

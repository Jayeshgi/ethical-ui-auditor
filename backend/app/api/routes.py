from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException

from app.core.config import RUNTIME_DATA_DIR
from app.core.security import UnsafeUrlError
from app.crawler.service import capture_website
from app.ocr.service import OCRUnavailableError, extract_text_blocks
from app.schemas import Finding, PageResult, ScanRequest, ScanResponse, TextBlock
from app.text_analysis.fusion import fuse_text_blocks
from app.text_analysis.model import DarkPatternBertClassifier, ModelUnavailableError
from app.text_analysis.evidence_rules import evidence_for_text


router = APIRouter(prefix="/api/v1", tags=["scans"])


@lru_cache(maxsize=1)
def get_classifier() -> DarkPatternBertClassifier:
    return DarkPatternBertClassifier()


@router.post("/scans", response_model=ScanResponse)
async def create_scan(request: ScanRequest) -> ScanResponse:
    try:
        classifier = get_classifier()
    except ModelUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    try:
        scan_id, captures, warnings = await capture_website(str(request.url), request.max_pages, request.scroll_steps)
    except UnsafeUrlError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Browser scan failed: {type(error).__name__}: {error}") from error

    if classifier.validation_warning:
        warnings.append(classifier.validation_warning)

    pages: list[PageResult] = []
    for capture in captures:
        screenshot = RUNTIME_DATA_DIR.parent / capture["screenshot_path"]
        try:
            ocr_blocks = extract_text_blocks(screenshot)
        except OCRUnavailableError as error:
            warnings.append(str(error))
            ocr_blocks = []
        except Exception as error:
            warnings.append(f"OCR failed for {capture['url']}: {type(error).__name__}: {error}")
            ocr_blocks = []

        fused = fuse_text_blocks(capture["dom_blocks"], ocr_blocks)
        text_blocks = [TextBlock.model_validate(block) for block in fused]
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
        pages.append(
            PageResult(
                url=capture["url"],
                title=capture["title"],
                screenshot_path=capture["screenshot_path"],
                text_blocks=text_blocks,
                findings=findings,
            )
        )
    return ScanResponse(scan_id=scan_id, status="completed_with_warnings" if warnings else "completed", pages=pages, warnings=warnings)

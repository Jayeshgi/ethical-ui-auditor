from app.text_analysis.fusion import fuse_text_blocks


def test_dom_text_is_preferred_and_ocr_is_retained_as_evidence() -> None:
    merged = fuse_text_blocks(
        [{"text": "Only 2 items left", "selector": ".stock", "bounding_box": {"x": 1, "y": 2, "width": 3, "height": 4}}],
        [{"text": "Only 2 items left", "ocr_confidence": 92.0, "bounding_box": {"x": 1, "y": 2, "width": 3, "height": 4}}],
    )
    assert len(merged) == 1
    assert merged[0]["source"] == "both"
    assert merged[0]["selector"] == ".stock"
    assert merged[0]["ocr_confidence"] == 92.0

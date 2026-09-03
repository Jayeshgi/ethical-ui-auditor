from __future__ import annotations

import asyncio
from collections import Counter, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
import re
import time
from urllib.parse import parse_qsl, urldefrag, urljoin, urlsplit, urlunsplit

from playwright.async_api import Browser, BrowserContext

from app.crawler.service import DOM_EXTRACTION_SCRIPT
from app.flow_analysis.autonomous_schemas import (
    AutonomousFlowRequest,
    GoalFamily,
    SiteCrawlReport,
    SitePageAnalysis,
)
from app.flow_analysis.intents import rank_intent_candidates
from app.flow_analysis.observation import (
    capture_redacted_screenshot,
    observe_controls,
    page_headings,
    page_text,
    redact_observed_text,
)
from app.frontend_analysis.engine import analyze_frontend_behavior
from app.frontend_analysis.schemas import FrontendArtifactSummary, FrontendBehaviorReport
from app.ocr.service import OCRUnavailableError, extract_text_blocks
from app.schemas import TextBlock, VisualCue
from app.scans.service import _analyse_text_blocks, get_classifier, get_visual_detector
from app.text_analysis.fusion import fuse_text_blocks
from app.visual_analysis.fusion import fuse_evidence, supported_categories
from app.visual_analysis.model import VisualModelUnavailableError


ContextFactory = Callable[[], Awaitable[BrowserContext]]
CancellationCallback = Callable[[], bool | Awaitable[bool]]
ProgressCallback = Callable[[int, int], None | Awaitable[None]]

_SENSITIVE_QUERY_KEY = re.compile(
    r"^(?:password|passwd|pwd|token|access_token|refresh_token|id_token|api_?key|"
    r"client_secret|secret|session|session_?id|authorization)$",
    re.I,
)
_NON_HTML_EXTENSION = re.compile(
    r"\.(?:7z|avi|avif|bmp|css|csv|docx?|eot|gif|gz|ico|jpe?g|json|m4a|mkv|mov|"
    r"mp3|mp4|mpeg|pdf|png|pptx?|rar|rss|svg|tar|tiff?|ttf|txt|wav|webm|webp|"
    r"woff2?|xlsx?|xml|zip)$",
    re.I,
)
_RISKY_GET_PATH = re.compile(
    r"(?:^|/)(?:delete|destroy|remove|logout|log-out|signout|sign-out|unsubscribe|"
    r"cancel|revoke|disconnect|close-account)(?:/|$)",
    re.I,
)


@dataclass(slots=True)
class SiteCrawlExecution:
    report: SiteCrawlReport
    goal_entry_urls: dict[GoalFamily, str]
    behavior: FrontendBehaviorReport


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    host = f"[{hostname}]" if ":" in hostname else hostname
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is not None and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    return f"{parsed.scheme.lower()}://{host}"


def _canonical_link(raw: str, base_url: str, target_origin: str, mode: str) -> str | None:
    try:
        absolute, _fragment = urldefrag(urljoin(base_url, raw))
        parsed = urlsplit(absolute)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        if _origin(absolute) != target_origin:
            return None
        if any(_SENSITIVE_QUERY_KEY.match(key) for key, _value in parse_qsl(parsed.query, keep_blank_values=True)):
            return None
        path = parsed.path or "/"
        if _NON_HTML_EXTENSION.search(path):
            return None
        if mode == "evidence_only" and _RISKY_GET_PATH.search(path):
            return None
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))
    except (TypeError, ValueError):
        return None


async def _is_cancelled(callback: CancellationCallback | None) -> bool:
    if callback is None:
        return False
    value = callback()
    return bool(await value) if isinstance(value, Awaitable) else bool(value)


async def _notify(callback: ProgressCallback | None, completed: int, discovered: int) -> None:
    if callback is None:
        return
    value = callback(completed, discovered)
    if isinstance(value, Awaitable):
        await value


def _safe_error(error: Exception, sensitive_values: tuple[str, ...]) -> str:
    return redact_observed_text(f"{type(error).__name__}: {error}", sensitive_values)[:1000]


def _aggregate_behavior(pages: list[SitePageAnalysis]) -> FrontendBehaviorReport:
    reports = [page.frontend_behavior for page in pages if page.frontend_behavior.status != "not_requested"]
    if not reports:
        return FrontendBehaviorReport()
    findings = []
    snapshots = []
    screenshots: list[str] = []
    warnings: list[str] = []
    network = []
    code = []
    script_hashes: dict[str, str] = {}
    style_hashes: dict[str, str] = {}
    storage_keys: list[str] = []
    cookie_names: list[str] = []
    for report in reports:
        findings.extend(report.findings)
        snapshots.extend(report.dom_snapshots)
        screenshots.extend(report.screenshots)
        warnings.extend(report.warnings)
        network.extend(report.artifacts.network_observations)
        code.extend(report.artifacts.code_evidence)
        script_hashes.update(report.artifacts.script_asset_hashes)
        style_hashes.update(report.artifacts.stylesheet_asset_hashes)
        storage_keys.extend(report.artifacts.storage_keys)
        cookie_names.extend(report.artifacts.cookie_names)
    artifacts = FrontendArtifactSummary(
        inline_script_count=sum(item.artifacts.inline_script_count for item in reports),
        script_asset_count=sum(item.artifacts.script_asset_count for item in reports),
        script_asset_hashes=script_hashes,
        stylesheet_asset_hashes=style_hashes,
        storage_keys=list(dict.fromkeys(storage_keys)),
        cookie_names=list(dict.fromkeys(cookie_names)),
        network_observations=network[:500],
        code_evidence=code[:250],
    )
    return FrontendBehaviorReport(
        status="completed_with_warnings" if warnings else "completed",
        observation_seconds=max((item.observation_seconds for item in reports), default=0),
        findings=findings,
        dom_snapshots=snapshots[:1000],
        artifacts=artifacts,
        screenshots=list(dict.fromkeys(screenshots)),
        warnings=list(dict.fromkeys(warnings)),
        note=(
            "Aggregated same-origin site evidence. Each finding records its page URL; "
            "runtime behavior and code clues remain distinct evidence sources."
        ),
    )


async def crawl_site(
    browser: Browser,
    request: AutonomousFlowRequest,
    context_factory: ContextFactory,
    run_directory: Path,
    *,
    cancellation_callback: CancellationCallback | None = None,
    progress_callback: ProgressCallback | None = None,
) -> SiteCrawlExecution:
    """Crawl bounded same-origin HTML pages and analyze each page independently."""

    start_url = str(request.url)
    target_origin = _origin(start_url)
    sensitive_values: tuple[str, ...] = ()
    if request.credentials:
        values = [
            request.credentials.username.get_secret_value(),
            request.credentials.password.get_secret_value(),
        ]
        if request.credentials.one_time_code:
            values.append(request.credentials.one_time_code.get_secret_value())
        sensitive_values = tuple(value for value in values if value)

    warnings: list[str] = []
    pages: list[SitePageAnalysis] = []
    goal_entry_urls: dict[GoalFamily, str] = {}
    goal_entry_scores: dict[GoalFamily, float] = {}
    category_counts: Counter[str] = Counter()
    queue = deque([(start_url, 0, None)])
    known = {start_url}
    visited: set[str] = set()
    max_depth_reached = False
    deadline = time.monotonic() + max(25.0, request.policy.max_runtime_seconds * 0.80)

    classifier = None
    visual_detector = None
    if request.analyse_models:
        try:
            classifier = await asyncio.to_thread(get_classifier)
            if classifier.validation_warning:
                warnings.append(classifier.validation_warning)
        except Exception as error:
            warnings.append(f"BERT site analysis unavailable: {type(error).__name__}.")
        try:
            visual_detector = await asyncio.to_thread(get_visual_detector)
        except VisualModelUnavailableError as error:
            warnings.append(str(error))
        except Exception as error:
            warnings.append(f"YOLO site analysis unavailable: {type(error).__name__}.")

    context = await context_factory()
    page = await context.new_page()
    try:
        while queue and len(visited) < request.policy.max_pages:
            if await _is_cancelled(cancellation_callback):
                warnings.append("Full-site crawl was cancelled before all discovered pages were processed.")
                break
            if time.monotonic() >= deadline:
                warnings.append("Full-site crawl stopped at its reserved runtime budget; remaining URLs are reported as uncovered.")
                break

            candidate, depth, parent = queue.popleft()
            if candidate in visited:
                continue
            visited.add(candidate)
            ordinal = len(visited)
            await _notify(progress_callback, ordinal - 1, len(known))
            try:
                response = await page.goto(candidate, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_timeout(500)
                if response is None:
                    raise RuntimeError("Navigation produced no HTTP response.")
                if response.status >= 400:
                    raise RuntimeError(f"Navigation returned HTTP {response.status}.")
                content_type = (response.headers.get("content-type") or "").lower()
                if content_type and "html" not in content_type and "xhtml" not in content_type:
                    raise RuntimeError(f"Skipped non-HTML content type {content_type[:120]}.")
                final_url = _canonical_link(page.url, candidate, target_origin, request.mode)
                if final_url is None:
                    raise RuntimeError("Navigation left the audited same-origin boundary.")

                title = redact_observed_text(await page.title(), sensitive_values)[:500]
                raw_blocks = await page.evaluate(DOM_EXTRACTION_SCRIPT)
                for block in raw_blocks:
                    block["text"] = redact_observed_text(str(block.get("text") or ""), sensitive_values)
                screenshot_file = run_directory / f"site-page-{ordinal:03d}.png"
                screenshot_path = await capture_redacted_screenshot(
                    page, screenshot_file, sensitive_values
                )

                ocr_blocks = []
                if request.analyse_models and screenshot_path:
                    try:
                        ocr_blocks = await asyncio.to_thread(extract_text_blocks, screenshot_file)
                    except OCRUnavailableError as error:
                        warnings.append(str(error))
                    except Exception as error:
                        warnings.append(f"OCR failed for {final_url}: {type(error).__name__}.")
                fused = fuse_text_blocks(raw_blocks, ocr_blocks)
                text_blocks = [
                    TextBlock.model_validate(item).model_copy(
                        update={
                            "text": redact_observed_text(
                                TextBlock.model_validate(item).text, sensitive_values
                            )
                        }
                    )
                    for item in fused
                ]
                text_findings = (
                    await asyncio.to_thread(_analyse_text_blocks, classifier, text_blocks)
                    if classifier is not None
                    else []
                )
                visual_cues: list[VisualCue] = []
                if visual_detector is not None and screenshot_path:
                    try:
                        predictions = await asyncio.to_thread(visual_detector.predict, screenshot_file)
                        visual_cues = [
                            VisualCue(
                                cue=item.cue,
                                model_confidence=round(item.confidence, 4),
                                threshold=visual_detector.confidence,
                                model_version=visual_detector.version,
                                bounding_box=item.bounding_box,
                                supports_categories=supported_categories(item.cue),
                            )
                            for item in predictions
                        ]
                    except Exception as error:
                        warnings.append(f"Visual analysis failed for {final_url}: {type(error).__name__}.")

                controls = await observe_controls(page, sensitive_values)
                context_evidence = [
                    *await page_headings(page, sensitive_values),
                    (await page_text(page, sensitive_values))[:4000],
                ]
                candidates = rank_intent_candidates(
                    controls,
                    context=context_evidence,
                    goal_families=["auto"],
                    minimum_score=0.36,
                )
                families: list[GoalFamily] = []
                for intent in candidates:
                    if intent.phase == "acquisition" and intent.family not in families:
                        families.append(intent.family)
                        if intent.score > goal_entry_scores.get(intent.family, -1):
                            goal_entry_scores[intent.family] = intent.score
                            goal_entry_urls[intent.family] = final_url

                behavior = FrontendBehaviorReport()
                if request.analyse_behavior:
                    remaining = deadline - time.monotonic()
                    required = request.policy.behavior_observation_seconds + 4
                    if remaining >= required:
                        behavior = await analyze_frontend_behavior(
                            browser,
                            final_url,
                            context_factory,
                            run_directory,
                            observation_seconds=request.policy.behavior_observation_seconds,
                            analyse_models=False,
                            sensitive_values=sensitive_values,
                            artifact_prefix=f"site-{ordinal:03d}",
                        )
                        behavior = behavior.model_copy(
                            update={
                                "findings": [
                                    item.model_copy(
                                        update={
                                            "page_url": final_url,
                                            "bert_categories": list(
                                                dict.fromkeys(
                                                    finding.category
                                                    for finding in text_findings
                                                    if finding.category == item.dark_pattern_category
                                                )
                                            ),
                                            "visual_cues": list(
                                                dict.fromkeys(
                                                    cue.cue
                                                    for cue in visual_cues
                                                    if item.dark_pattern_category in cue.supports_categories
                                                )
                                            ),
                                        }
                                    )
                                    for item in behavior.findings
                                ]
                            }
                        )
                        warnings.extend(behavior.warnings)
                    else:
                        warnings.append(
                            f"Dynamic observation skipped for {final_url}: the crawl runtime budget was nearly exhausted."
                        )

                page_result = SitePageAnalysis(
                    url=final_url,
                    title=title,
                    depth=depth,
                    discovered_from=parent,
                    status="scanned",
                    screenshot_path=screenshot_path,
                    text_blocks_analyzed=len(text_blocks),
                    text_findings=text_findings,
                    visual_cues=visual_cues,
                    fusion_links=fuse_evidence(text_findings, visual_cues),
                    frontend_behavior=behavior,
                    discovered_goal_families=families,
                )
                pages.append(page_result)
                category_counts.update(item.category for item in text_findings)
                category_counts.update(item.category for item in behavior.findings if item.status in {"detected", "suspicious"})
                category_counts.update(f"visual:{item.cue}" for item in visual_cues)

                raw_links = await page.eval_on_selector_all(
                    "a[href]", "elements => elements.map(element => element.href)"
                )
                links = list(
                    dict.fromkeys(
                        value
                        for raw in raw_links
                        if (value := _canonical_link(raw, final_url, target_origin, request.mode))
                    )
                )
                if depth >= request.policy.crawl_depth:
                    if any(link not in known for link in links):
                        max_depth_reached = True
                        known.update(links)
                else:
                    for link in links:
                        if link not in known:
                            known.add(link)
                            queue.append((link, depth + 1, final_url))
            except Exception as error:
                pages.append(
                    SitePageAnalysis(
                        url=candidate,
                        depth=depth,
                        discovered_from=parent,
                        status="failed",
                        error=_safe_error(error, sensitive_values),
                    )
                )
            await _notify(progress_callback, len(visited), len(known))
    finally:
        await context.close()

    max_pages_reached = bool(queue) and len(visited) >= request.policy.max_pages
    failed = sum(item.status == "failed" for item in pages)
    scanned = sum(item.status == "scanned" for item in pages)
    coverage_complete = not queue and not max_depth_reached and failed == 0
    if max_pages_reached:
        warnings.append(
            f"Page limit reached ({request.policy.max_pages}); increase Maximum pages to cover more discovered URLs."
        )
    if max_depth_reached:
        warnings.append(
            f"Crawl depth limit reached ({request.policy.crawl_depth}); deeper same-origin URLs remain uncovered."
        )
    report = SiteCrawlReport(
        status="completed_with_warnings" if warnings or failed else "completed",
        start_url=start_url,
        origin=target_origin,
        pages_discovered=len(known),
        pages_scanned=scanned,
        pages_failed=failed,
        max_pages_reached=max_pages_reached,
        max_depth_reached=max_depth_reached,
        coverage_complete=coverage_complete,
        category_counts=dict(sorted(category_counts.items())),
        pages=pages,
        warnings=list(dict.fromkeys(warnings)),
    )
    return SiteCrawlExecution(
        report=report,
        goal_entry_urls=goal_entry_urls,
        behavior=_aggregate_behavior(pages),
    )

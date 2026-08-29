from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
import re
from urllib.parse import urlparse
import uuid

from playwright.async_api import BrowserContext, Locator, Page, async_playwright

from app.core.config import RUNTIME_DATA_DIR, configure_runtime_environment
from app.core.security import validate_public_http_url
from app.flow_analysis.evidence import analyse_step_evidence
from app.flow_analysis.schemas import (
    FlowActionSpec,
    FlowDefinitionSpec,
    FlowPairRequest,
    FlowPairResult,
    FlowRunResult,
    FlowStepEvidence,
    FlowStepResult,
)
from app.flow_analysis.scoring import compare_flows, metrics_for_steps


CONTROLLED_ORIGINS = {
    "https://automationexercise.com",
    "http://automationexercise.com",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
}


class FlowExecutionError(RuntimeError):
    pass


def runtime_variables() -> dict[str, str]:
    suffix = f"{int(datetime.now(UTC).timestamp())}-{uuid.uuid4().hex[:8]}"
    return {
        "unique_email": f"ethical-ui-{suffix}@example.com",
        "unique_name": f"Ethical UI {uuid.uuid4().hex[:6]}",
        "test_password": f"FlowTest!9{uuid.uuid4().hex[:10]}",
    }


def render_template(value: str | None, variables: dict[str, str]) -> str | None:
    if value is None:
        return None
    rendered = value
    for key, replacement in variables.items():
        rendered = rendered.replace("{{" + key + "}}", replacement)
    unresolved = re.findall(r"{{[^{}]+}}", rendered)
    if unresolved:
        raise FlowExecutionError(f"Unresolved flow variables: {', '.join(unresolved)}")
    return rendered


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _allowed_origins(request: FlowPairRequest) -> set[str]:
    origins = {value.rstrip("/") for value in request.allowed_origins}
    for flow in (request.acquisition, request.exit):
        if flow.start_url:
            origins.add(_origin(flow.start_url))
        for action in flow.actions:
            if action.action == "goto" and action.value:
                origins.add(_origin(action.value))
    if request.mode == "controlled" and not origins.issubset(CONTROLLED_ORIGINS):
        unknown = sorted(origins - CONTROLLED_ORIGINS)
        raise FlowExecutionError(f"Controlled mode is restricted to approved test origins: {unknown}")
    return origins


async def _target_presentation(locator: Locator | None) -> dict | None:
    if locator is None:
        return None
    try:
        return await locator.evaluate(
            """element => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              const area = Math.max(0, rect.width * rect.height);
              const viewportArea = Math.max(1, window.innerWidth * window.innerHeight);
              return {
                visible: !!(rect.width && rect.height) && style.visibility !== 'hidden' && style.display !== 'none',
                viewport_area_ratio: area / viewportArea,
                opacity: Number(style.opacity || 1),
                font_size_px: parseFloat(style.fontSize || '0'),
                contrast_ratio: null
              };
            }"""
        )
    except Exception:
        return None


async def _visible_evidence_text(page: Page) -> str:
    try:
        texts = await page.locator("h1,h2,h3,p,label,button,a,[role=button],[role=dialog]").all_inner_texts()
    except Exception:
        return ""
    cleaned = [re.sub(r"\s+", " ", text).strip() for text in texts]
    return "\n".join(list(dict.fromkeys(text for text in cleaned if text))[:120])


async def _execute_action(page: Page, action: FlowActionSpec, variables: dict[str, str]) -> Locator | None:
    value = render_template(action.value, variables)
    locator = page.locator(action.selector).first if action.selector else None
    if action.action == "goto":
        await page.goto(value, wait_until="domcontentloaded", timeout=action.timeout_ms)
    elif action.action == "click":
        await locator.click(timeout=action.timeout_ms)
    elif action.action == "fill":
        await locator.fill(value, timeout=action.timeout_ms)
    elif action.action == "select":
        await locator.select_option(value, timeout=action.timeout_ms)
    elif action.action == "check":
        await locator.check(timeout=action.timeout_ms)
    elif action.action == "wait_for":
        await locator.wait_for(state="visible", timeout=action.timeout_ms)
    elif action.action == "assert_text":
        await page.get_by_text(value, exact=False).first.wait_for(state="visible", timeout=action.timeout_ms)
    else:  # pragma: no cover - Pydantic rejects unknown action types.
        raise FlowExecutionError(f"Unsupported flow action: {action.action}")
    return locator


async def _navigate_start(page: Page, definition: FlowDefinitionSpec) -> None:
    if definition.start_url:
        await page.goto(definition.start_url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(300)


async def _run_phase(
    page: Page,
    definition: FlowDefinitionSpec,
    phase: str,
    request: FlowPairRequest,
    variables: dict[str, str],
    run_directory: Path,
) -> FlowRunResult:
    await _navigate_start(page, definition)
    results: list[FlowStepResult] = []
    phase_status = "completed"
    for index, action in enumerate(definition.actions):
        before = page.url
        started = datetime.now(UTC)
        locator = page.locator(action.selector).first if action.selector else None
        presentation = await _target_presentation(locator)
        screenshot_path = run_directory / f"{phase}-{index:03d}.png"

        if action.commit and request.mode == "evidence_only":
            await page.screenshot(path=str(screenshot_path), full_page=False)
            text = await _visible_evidence_text(page)
            evidence = await asyncio.to_thread(
                analyse_step_evidence, text, presentation, screenshot_path, False, phase
            )
            results.append(
                FlowStepResult(
                    index=index,
                    phase=phase,
                    action=action.action,
                    description=action.description,
                    status="blocked_at_commit",
                    url_before=before,
                    url_after=page.url,
                    duration_ms=0,
                    page_transition=False,
                    screenshot_path=str(screenshot_path.relative_to(RUNTIME_DATA_DIR.parent)),
                    evidence=evidence,
                )
            )
            phase_status = "blocked_at_commit"
            break

        try:
            await _execute_action(page, action, variables)
            await page.wait_for_timeout(250)
            duration = int((datetime.now(UTC) - started).total_seconds() * 1000)
            await page.screenshot(path=str(screenshot_path), full_page=False)
            text = await _visible_evidence_text(page)
            use_models = request.analyse_models and action.action in {"click", "assert_text", "goto"}
            evidence = await asyncio.to_thread(
                analyse_step_evidence, text, presentation, screenshot_path, use_models, phase
            )
            results.append(
                FlowStepResult(
                    index=index,
                    phase=phase,
                    action=action.action,
                    description=action.description,
                    status="completed",
                    url_before=before,
                    url_after=page.url,
                    duration_ms=duration,
                    page_transition=before != page.url,
                    screenshot_path=str(screenshot_path.relative_to(RUNTIME_DATA_DIR.parent)),
                    evidence=evidence,
                )
            )
        except Exception as error:
            duration = int((datetime.now(UTC) - started).total_seconds() * 1000)
            try:
                await page.screenshot(path=str(screenshot_path), full_page=False)
                stored_screenshot = str(screenshot_path.relative_to(RUNTIME_DATA_DIR.parent))
            except Exception:
                stored_screenshot = None
            results.append(
                FlowStepResult(
                    index=index,
                    phase=phase,
                    action=action.action,
                    description=action.description,
                    status="failed",
                    url_before=before,
                    url_after=page.url,
                    duration_ms=duration,
                    page_transition=before != page.url,
                    screenshot_path=stored_screenshot,
                    evidence=FlowStepEvidence(target_presentation=presentation),
                    error=f"{type(error).__name__}: {error}",
                )
            )
            phase_status = "failed"
            break

    return FlowRunResult(
        name=definition.name,
        goal=definition.goal,
        status=phase_status,
        steps=results,
        metrics=metrics_for_steps(results),
    )


async def _cleanup(page: Page, actions: list[FlowActionSpec], variables: dict[str, str]) -> list[str]:
    warnings: list[str] = []
    for action in actions:
        try:
            await _execute_action(page, action, variables)
            await page.wait_for_timeout(150)
        except Exception as error:
            warnings.append(f"Cleanup action '{action.description}' failed: {type(error).__name__}: {error}")
    return warnings


async def perform_flow_analysis(request: FlowPairRequest, run_id: str | None = None) -> FlowPairResult:
    configure_runtime_environment()
    run_id = run_id or f"flow-{uuid.uuid4().hex[:12]}"
    run_directory = RUNTIME_DATA_DIR / "flow_runs" / run_id
    run_directory.mkdir(parents=True, exist_ok=True)
    allowed_origins = _allowed_origins(request)
    if not allowed_origins:
        raise FlowExecutionError("At least one allowed origin is required.")

    # Public evidence mode validates every navigation target before opening a browser.
    if request.mode == "evidence_only":
        for origin in allowed_origins:
            await asyncio.to_thread(validate_public_http_url, origin)

    variables = runtime_variables()
    warnings: list[str] = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context: BrowserContext = await browser.new_context(
            viewport={"width": 1440, "height": 1000},
            user_agent="EthicalUIAuditor-Flow/0.1 (research flow analysis)",
            accept_downloads=False,
            service_workers="block",
        )
        public_hosts: dict[str, bool] = {}

        async def network_policy(route):
            parsed = urlparse(route.request.url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                await route.abort()
                return
            request_origin = f"{parsed.scheme}://{parsed.netloc}"
            if route.request.is_navigation_request() and request_origin not in allowed_origins:
                await route.abort()
                return
            is_controlled_local = request_origin in CONTROLLED_ORIGINS and parsed.hostname in {"127.0.0.1", "localhost"}
            if not is_controlled_local:
                hostname = parsed.hostname.rstrip(".").lower()
                if hostname not in public_hosts:
                    try:
                        await asyncio.to_thread(validate_public_http_url, route.request.url)
                        public_hosts[hostname] = True
                    except Exception:
                        public_hosts[hostname] = False
                if not public_hosts[hostname]:
                    await route.abort()
                    return
            await route.continue_()

        await context.route("**/*", network_policy)
        page = await context.new_page()
        try:
            acquisition = await _run_phase(
                page, request.acquisition, "acquisition", request, variables, run_directory
            )
            if acquisition.status == "failed":
                exit_flow = FlowRunResult(
                    name=request.exit.name,
                    goal=request.exit.goal,
                    status="failed",
                    steps=[],
                    metrics=metrics_for_steps([]),
                )
                warnings.append("Exit flow was not attempted because acquisition failed.")
            else:
                exit_flow = await _run_phase(page, request.exit, "exit", request, variables, run_directory)
        finally:
            warnings.extend(await _cleanup(page, request.cleanup_actions, variables))
            await context.close()
            await browser.close()

    return FlowPairResult(
        run_id=run_id,
        name=request.name,
        source=request.source,
        mode=request.mode,
        acquisition=acquisition,
        exit=exit_flow,
        finding=compare_flows(acquisition, exit_flow),
        warnings=warnings,
    )

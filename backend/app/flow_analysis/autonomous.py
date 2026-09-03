from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlparse
import uuid

from playwright.async_api import BrowserContext, Locator, Page, Route, async_playwright

from app.core.config import RUNTIME_DATA_DIR, configure_runtime_environment
from app.core.security import validate_public_http_url
from app.frontend_analysis.engine import analyze_frontend_behavior
from app.frontend_analysis.schemas import FrontendBehaviorReport
from app.flow_analysis.autonomous_scoring import AUTONOMOUS_PIPELINE_VERSION, roach_motel_finding
from app.flow_analysis.autonomous_schemas import (
    AutomationLimitation,
    AutonomousFlowRequest,
    AutonomousFlowResult,
    AutonomousPathResult,
    AutonomousRunSummary,
    GoalFamily,
    GoalPairAnalysis,
    GoalTerminalEvidence,
    GraphEdge,
    GraphNode,
    ModelPipelineStatus,
    ObservedControl,
    SiteCrawlReport,
    StateGraph,
)
from app.flow_analysis.confidence import build_confidence_breakdown
from app.flow_analysis.engine import CONTROLLED_ORIGINS
from app.flow_analysis.evidence import analyse_step_evidence
from app.flow_analysis.intents import (
    GoalCandidatePair,
    RankedIntentCandidate,
    pair_goal_candidates,
    rank_intent_candidates,
)
from app.flow_analysis.limitations import detect_limitations
from app.flow_analysis.mechanisms import detect_mechanisms
from app.flow_analysis.observation import observe_state, page_text
from app.flow_analysis.risk import action_allowed, classify_action_risk, request_method_allowed
from app.flow_analysis.schemas import FlowMetrics, FlowStepEvidence, FlowStepResult
from app.flow_analysis.scoring import JUSTIFIED_WEIGHTS, OBSTRUCTION_WEIGHTS
from app.flow_analysis.selectors import build_selector_bundle, resolve_selector
from app.flow_analysis.site_crawler import crawl_site
from app.flow_analysis.state_graph import StateGraphBuilder, detect_dead_ends, detect_redirect_loops


ProgressCallback = Callable[[str, int], Awaitable[None]]
CancellationCallback = Callable[[], Awaitable[bool]]

AUTH_REQUIRED_FAMILIES: set[GoalFamily] = {
    "account_create_delete",
    "subscribe_cancel",
    "newsletter_subscribe_unsubscribe",
    "integration_connect_disconnect",
    "payment_method_add_remove",
    "loyalty_join_leave",
    "data_share_revoke",
    "purchase_return",
}
TERMINAL_PATTERNS: dict[tuple[GoalFamily, str], tuple[str, ...]] = {
    ("account_create_delete", "acquisition"): ("account created", "account ready", "welcome to your account", "logged in as"),
    ("account_create_delete", "exit"): ("account deleted", "account closed", "account has been removed", "deletion complete"),
    ("subscribe_cancel", "acquisition"): ("subscription active", "subscribed successfully", "trial started", "membership active"),
    ("subscribe_cancel", "exit"): ("subscription cancelled", "subscription canceled", "membership cancelled", "trial cancelled"),
    ("newsletter_subscribe_unsubscribe", "acquisition"): ("subscribed", "check your inbox", "thanks for signing up"),
    ("newsletter_subscribe_unsubscribe", "exit"): ("unsubscribed", "removed from", "will no longer receive"),
    ("consent_grant_withdraw", "acquisition"): ("preferences saved", "consent accepted", "cookies accepted"),
    ("consent_grant_withdraw", "exit"): ("consent withdrawn", "preferences saved", "cookies rejected"),
    ("notifications_enable_disable", "acquisition"): ("notifications enabled", "notifications are on"),
    ("notifications_enable_disable", "exit"): ("notifications disabled", "notifications are off"),
    ("integration_connect_disconnect", "acquisition"): ("integration connected", "successfully connected"),
    ("integration_connect_disconnect", "exit"): ("integration disconnected", "access revoked", "successfully disconnected"),
    ("payment_method_add_remove", "acquisition"): ("payment method added", "card added"),
    ("payment_method_add_remove", "exit"): ("payment method removed", "card removed"),
    ("loyalty_join_leave", "acquisition"): ("welcome to the rewards", "membership active", "successfully joined"),
    ("loyalty_join_leave", "exit"): ("left the program", "membership ended", "rewards membership cancelled"),
    ("data_share_revoke", "acquisition"): ("data sharing enabled", "permission granted"),
    ("data_share_revoke", "exit"): ("data sharing disabled", "permission revoked", "access revoked"),
    ("purchase_return", "acquisition"): ("order confirmed", "purchase complete"),
    ("purchase_return", "exit"): ("return started", "return requested", "refund requested"),
}
PROGRESS_RE = re.compile(
    r"\b(?:continue|next|proceed|confirm|finish|submit|yes|no,? continue|save preferences|done)\b",
    re.I,
)
HUB_RE: dict[str, re.Pattern[str]] = {
    "acquisition": re.compile(r"\b(?:menu|plans?|pricing|account|join|membership|newsletter|preferences|integrations?)\b", re.I),
    "exit": re.compile(
        r"\b(?:menu|my account|profile|settings|account controls?|manage|billing|subscriptions?|privacy|preferences|notifications?|integrations?|rewards?|returns?)\b",
        re.I,
    ),
}
RETENTION_ACCEPT_RE = re.compile(r"\b(?:stay|keep (?:my|your)|claim|accept offer|pause instead|go back)\b", re.I)
BLOCKING_LIMITATIONS = {
    "captcha_required",
    "mfa_required",
    "email_verification_required",
    "authentication_failed",
    "payment_required",
    "external_identity_provider",
    "bot_protection",
    "rate_limited",
    "native_app_required",
}
RESUMABLE_LIMITATIONS = {
    "credentials_required",
    "authentication_failed",
    "mfa_required",
    "email_verification_required",
}


class AutonomousFlowError(RuntimeError):
    pass


@dataclass
class SequenceCounter:
    value: int = 0

    def next(self) -> int:
        current = self.value
        self.value += 1
        return current


@dataclass
class JourneyExecution:
    path: AutonomousPathResult
    edges: list[GraphEdge] = field(default_factory=list)
    primary_candidate: RankedIntentCandidate | None = None
    limitations: list[AutomationLimitation] = field(default_factory=list)


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


async def _progress(callback: ProgressCallback | None, stage: str, value: int) -> None:
    if callback:
        await callback(stage, value)


async def _ensure_not_cancelled(callback: CancellationCallback | None) -> None:
    if callback and await callback():
        raise asyncio.CancelledError


async def _safe_goto(
    page: Page,
    url: str,
    *,
    phase: str,
    wait_until: str = "domcontentloaded",
) -> AutomationLimitation | None:
    try:
        response = await page.goto(url, wait_until=wait_until, timeout=30_000)
    except Exception as error:
        return AutomationLimitation(
            code="navigation_failed",
            phase=phase,
            message=f"Navigation could not be completed ({type(error).__name__}).",
        )
    if response is not None and response.status >= 400:
        return AutomationLimitation(
            code="navigation_failed",
            phase=phase,
            message=f"Navigation returned HTTP {response.status}.",
            evidence=[f"status:{response.status}"],
        )
    return None


def _request_redaction_values(request: AutonomousFlowRequest) -> tuple[str, ...]:
    if request.credentials is None:
        return ()
    values = [
        request.credentials.username.get_secret_value(),
        request.credentials.password.get_secret_value(),
    ]
    if request.credentials.one_time_code:
        values.append(request.credentials.one_time_code.get_secret_value())
    return tuple(value for value in values if value)


async def _redacted_page_html(page: Page, request: AutonomousFlowRequest) -> str:
    html = await page.content()
    for sensitive in _request_redaction_values(request):
        html = html.replace(sensitive, "[REDACTED]")
    return html


async def _approved_origins(request: AutonomousFlowRequest) -> set[str]:
    target = str(request.url)
    origins = {_origin(target), *(value.rstrip("/") for value in request.allowed_origins)}
    if request.credentials and request.credentials.login_url:
        origins.add(_origin(str(request.credentials.login_url)))
    if request.mode == "controlled":
        unknown = origins - CONTROLLED_ORIGINS
        if unknown:
            raise AutonomousFlowError(f"Controlled autonomous mode is restricted to test origins: {sorted(unknown)}")
    else:
        for origin in origins:
            await asyncio.to_thread(validate_public_http_url, origin)
    return origins


def _is_login_request(url: str) -> bool:
    return bool(re.search(r"/(?:log[-_]?in|sign[-_]?in|session|auth|token)(?:/|\?|$)", url, re.I))


async def _configure_context(browser, request: AutonomousFlowRequest, allowed_origins: set[str]) -> BrowserContext:
    context: BrowserContext = await browser.new_context(
        viewport={"width": 1440, "height": 1000},
        user_agent="EthicalUIAuditor-Autonomous/1.0 (research flow analysis)",
        service_workers="block",
        accept_downloads=False,
        permissions=[],
    )
    public_hosts: dict[str, bool] = {}

    async def network_policy(route: Route) -> None:
        request_url = route.request.url
        parsed = urlparse(request_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            await route.abort()
            return
        request_origin = f"{parsed.scheme}://{parsed.netloc}"
        if route.request.is_navigation_request() and request_origin not in allowed_origins:
            await route.abort()
            return
        if request.mode == "evidence_only":
            is_login = (
                bool(request.credentials)
                and request_origin in allowed_origins
                and _is_login_request(request_url)
            )
            if not request_method_allowed(route.request.method, request.mode, is_login=is_login):
                await route.abort()
                return
        controlled_local = (
            request.mode == "controlled"
            and request_origin in CONTROLLED_ORIGINS
            and parsed.hostname in {"127.0.0.1", "localhost"}
        )
        if not controlled_local:
            hostname = parsed.hostname.rstrip(".").lower()
            if hostname not in public_hosts:
                try:
                    await asyncio.to_thread(validate_public_http_url, request_url)
                    public_hosts[hostname] = True
                except Exception:
                    public_hosts[hostname] = False
            if not public_hosts[hostname]:
                await route.abort()
                return
        await route.continue_()

    await context.route("**/*", network_policy)
    return context


def _terminal_evidence(family: GoalFamily, phase: str, text: str, state_id: str) -> GoalTerminalEvidence:
    normalized = text.lower()
    matched = [phrase for phrase in TERMINAL_PATTERNS.get((family, phase), ()) if phrase in normalized]
    if matched:
        return GoalTerminalEvidence(
            verified=True,
            confidence=1.0,
            state_id=state_id,
            evidence=[f"visible-text:{phrase}" for phrase in matched],
        )
    return GoalTerminalEvidence()


def _metrics_for_autonomous_steps(steps: list[FlowStepResult]) -> FlowMetrics:
    usable = [step for step in steps if step.status in {"completed", "blocked_at_commit"}]
    meaningful = [step for step in usable if step.action in {"click", "fill", "select", "check"}]
    tag_keys = {(step.url_after, tag) for step in usable for tag in step.evidence.obstruction_tags}
    justified_keys = {(step.url_after, tag) for step in usable for tag in step.evidence.justified_tags}
    tags = Counter(tag for _url, tag in tag_keys)
    justified = Counter(tag for _url, tag in justified_keys)
    obstruction_weight = sum(OBSTRUCTION_WEIGHTS.get(tag, 1.0) * count for tag, count in tags.items())
    justified_weight = sum(JUSTIFIED_WEIGHTS.get(tag, 1.0) * count for tag, count in justified.items())
    clicks = sum(step.action == "click" for step in meaningful)
    fields = sum(step.action in {"fill", "select", "check"} for step in meaningful)
    transitions = sum(step.page_transition for step in usable)
    active_ms = sum(step.duration_ms for step in meaningful if step.status == "completed")
    effort = (
        len(meaningful)
        + 0.5 * transitions
        + 0.5 * fields
        + max(0.0, obstruction_weight - justified_weight)
        + min(active_ms / 30_000.0, 3.0)
    )
    return FlowMetrics(
        meaningful_actions=len(meaningful),
        clicks=clicks,
        form_fields=fields,
        page_transitions=transitions,
        active_time_ms=active_ms,
        obstruction_weight=round(obstruction_weight, 2),
        justified_weight=round(justified_weight, 2),
        effort_score=round(effort, 2),
        completed=bool(steps) and all(step.status == "completed" for step in steps),
    )


def _empty_path(phase: str, status: str = "not_found") -> AutonomousPathResult:
    return AutonomousPathResult(
        phase=phase,
        status=status,
        metrics=_metrics_for_autonomous_steps([]),
    )


def _screenshot_absolute(relative: str | None) -> Path | None:
    return None if not relative else RUNTIME_DATA_DIR.parent / relative


async def _step_evidence(
    text: str,
    control: ObservedControl,
    screenshot_path: str | None,
    analyse_models: bool,
    phase: str,
) -> FlowStepEvidence:
    screenshot = _screenshot_absolute(screenshot_path)
    target = control.presentation.model_dump() if control.presentation else None
    # Evidence excerpts are persisted and returned by the API.  Remove common
    # account identifiers before they reach either the models or PostgreSQL.
    text = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[REDACTED_EMAIL]", text, flags=re.I)
    text = re.sub(r"(?<!\d)(?:\+?\d[\s().-]?){9,15}(?!\d)", "[REDACTED_PHONE]", text)
    text = re.sub(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)", "[REDACTED_NUMBER]", text)
    return await asyncio.to_thread(
        analyse_step_evidence,
        text,
        target,
        screenshot,
        analyse_models,
        phase,
    )


async def _generic_value(locator: Locator, control: ObservedControl) -> str:
    descriptor = f"{control.name} {control.input_type or ''}".lower()
    suffix = uuid.uuid4().hex[:8]
    if control.input_type == "email" or "email" in descriptor:
        return f"ethical-ui-{suffix}@example.com"
    if control.input_type == "password" or "password" in descriptor:
        return f"FlowTest!9{suffix}Aa"
    if control.input_type == "tel" or re.search(r"\b(phone|mobile)\b", descriptor):
        return "9999999999"
    if "first name" in descriptor:
        return "Ethical"
    if "last name" in descriptor:
        return "Auditor"
    if re.search(r"\b(reason|why)\b", descriptor):
        return "Testing user autonomy and exit accessibility"
    if re.search(r"\b(address)\b", descriptor):
        return "1 Test Street"
    if "city" in descriptor:
        return "New Delhi"
    if re.search(r"\b(zip|postal)\b", descriptor):
        return "110001"
    if "state" in descriptor:
        return "Delhi"
    if "name" in descriptor:
        return "Ethical UI Researcher"
    return "Research test"


async def _fill_required_fields(
    page: Page,
    node: GraphNode,
    phase: str,
    builder: StateGraphBuilder,
    steps: list[FlowStepResult],
    edges: list[GraphEdge],
    visited_fields: set[str],
) -> int:
    filled = 0
    for control in node.controls:
        if not control.required or control.control_id in visited_fields or control.disabled:
            continue
        if control.input_type in {"file", "hidden"}:
            continue
        descriptor = f"{control.name} {control.input_type or ''}".lower()
        if re.search(r"\b(card|cvc|cvv|government|passport|tax|health|ssn)\b", descriptor):
            continue
        resolved = await resolve_selector(page, control.selectors)
        if resolved is None:
            continue
        locator, strategy = resolved
        before = page.url
        started = datetime.now(UTC)
        try:
            if control.role in {"checkbox", "radio"} or control.input_type in {"checkbox", "radio"}:
                await locator.check(timeout=5_000)
                action = "check"
            elif control.role == "combobox" or await locator.evaluate("el => el.tagName === 'SELECT'"):
                options = await locator.locator("option:not([disabled])").count()
                await locator.select_option(index=1 if options > 1 else 0, timeout=5_000)
                action = "select"
            else:
                await locator.fill(await _generic_value(locator, control), timeout=5_000)
                action = "fill"
        except Exception:
            continue
        duration = int((datetime.now(UTC) - started).total_seconds() * 1000)
        visited_fields.add(control.control_id)
        filled += 1
        step_index = len(steps)
        steps.append(
            FlowStepResult(
                index=step_index,
                phase=phase,
                action=action,
                description=f"Complete required field: {control.name}",
                status="completed",
                url_before=before,
                url_after=page.url,
                duration_ms=duration,
                page_transition=False,
                screenshot_path=node.screenshot_path,
                evidence=FlowStepEvidence(target_presentation=control.presentation),
            )
        )
        edge = GraphEdge(
            edge_id=f"edge-{uuid.uuid4().hex[:12]}",
            phase=phase,
            source_state_id=node.state_id,
            target_state_id=node.state_id,
            action=action,
            accessible_name=control.name,
            selectors=[strategy],
            risk="reversible",
            status="completed",
            duration_ms=duration,
        )
        edges.append(builder.add_edge(edge).model_copy(deep=True))
    return filled


def _choose_control(
    node: GraphNode,
    text: str,
    family: GoalFamily,
    phase: str,
    journey_started: bool,
    visited_controls: set[tuple[str, str]],
) -> tuple[ObservedControl | None, RankedIntentCandidate | None, str]:
    candidates = rank_intent_candidates(
        node.controls,
        context=[*node.headings, node.dialog_text, text[:4000]],
        goal_families=[family],
        minimum_score=0.34,
    )
    for candidate in candidates:
        if candidate.phase != phase or (node.state_id, candidate.control.control_id) in visited_controls:
            continue
        return candidate.control, candidate, "goal"

    if journey_started:
        progress_controls = [
            control
            for control in node.controls
            if not control.disabled
            and (node.state_id, control.control_id) not in visited_controls
            and PROGRESS_RE.search(control.name)
            and not RETENTION_ACCEPT_RE.search(control.name)
        ]
        if progress_controls:
            progress_controls.sort(key=lambda control: (control.document_index, control.name.lower()))
            return progress_controls[0], None, "progress"

    hub_controls = [
        control
        for control in node.controls
        if not control.disabled
        and (node.state_id, control.control_id) not in visited_controls
        and HUB_RE[phase].search(f"{control.name} {control.href or ''}")
    ]
    if hub_controls:
        hub_controls.sort(key=lambda control: (control.document_index, control.name.lower()))
        return hub_controls[0], None, "hub"
    return None, None, "none"


async def _execute_journey(
    page: Page,
    request: AutonomousFlowRequest,
    family: GoalFamily,
    phase: str,
    builder: StateGraphBuilder,
    run_directory: Path,
    sequence: SequenceCounter,
    allowed_origins: set[str],
    *,
    start_from_current: bool = False,
    cancellation_callback: CancellationCallback | None = None,
) -> JourneyExecution:
    if not start_from_current:
        navigation_failure = await _safe_goto(page, str(request.url), phase=phase)
        if navigation_failure:
            return JourneyExecution(
                path=_empty_path(phase, "failed"),
                limitations=[navigation_failure],
            )
        await page.wait_for_timeout(250)
    steps: list[FlowStepResult] = []
    edges: list[GraphEdge] = []
    limitations: list[AutomationLimitation] = []
    visited_controls: set[tuple[str, str]] = set()
    visited_fields: set[str] = set()
    visited_states: Counter[str] = Counter()
    state_ids: list[str] = []
    required_fields = 0
    first_candidate: RankedIntentCandidate | None = None
    journey_started = False
    began = time.monotonic()
    root_added = False

    for depth in range(request.policy.max_depth + 1):
        await _ensure_not_cancelled(cancellation_callback)
        if len(builder.build().nodes) >= request.policy.max_states:
            limitations.append(
                AutomationLimitation(
                    code="state_budget_exhausted",
                    phase=phase,
                    message="The autonomous run reached its global state budget.",
                )
            )
            break
        if time.monotonic() - began > request.policy.max_runtime_seconds:
            limitations.append(
                AutomationLimitation(
                    code="runtime_budget_exhausted",
                    phase=phase,
                    message="The autonomous journey reached its runtime budget.",
                )
            )
            break
        node, text = await observe_state(
            page,
            phase=phase,
            depth=depth,
            run_directory=run_directory,
            sequence=sequence.next(),
            has_credentials=request.credentials is not None,
            redaction_values=_request_redaction_values(request),
        )
        canonical = builder.add_node(node)
        node = canonical.model_copy(deep=True)
        if not root_added:
            builder.add_root(node.state_id)
            root_added = True
        state_ids.append(node.state_id)
        visited_states[node.state_id] += 1
        terminal = _terminal_evidence(family, phase, text, node.state_id)
        if terminal.verified:
            return JourneyExecution(
                path=AutonomousPathResult(
                    phase=phase,
                    status="completed",
                    steps=steps,
                    metrics=_metrics_for_autonomous_steps(steps),
                    state_ids=list(dict.fromkeys(state_ids)),
                    terminal=terminal,
                    required_fields=required_fields,
                    control_rank=first_candidate.control.document_index + 1 if first_candidate else None,
                ),
                edges=edges,
                primary_candidate=first_candidate,
                limitations=limitations,
            )

        detected = detect_limitations(
            text=text,
            html=await _redacted_page_html(page, request),
            url=page.url,
            has_credentials=request.credentials is not None,
            phase=phase,
        )
        for limitation in detected:
            if limitation.code not in {item.code for item in limitations}:
                limitation.state_id = node.state_id
                limitations.append(limitation)
        hard_block = next((item for item in detected if item.code in BLOCKING_LIMITATIONS), None)
        if hard_block and not (hard_block.code == "payment_required" and phase == "acquisition"):
            return JourneyExecution(
                path=AutonomousPathResult(
                    phase=phase,
                    status="needs_input" if hard_block.recoverable else "failed",
                    steps=steps,
                    metrics=_metrics_for_autonomous_steps(steps),
                    state_ids=list(dict.fromkeys(state_ids)),
                    terminal=GoalTerminalEvidence(confidence=0.2, state_id=node.state_id),
                    required_fields=required_fields,
                ),
                edges=edges,
                primary_candidate=first_candidate,
                limitations=limitations,
            )

        if journey_started and request.mode == "controlled":
            required_fields += await _fill_required_fields(
                page, node, phase, builder, steps, edges, visited_fields
            )

        control, candidate, control_kind = _choose_control(
            node, text, family, phase, journey_started, visited_controls
        )
        if control is None:
            if any(item.code == "channel_switch" for item in detected):
                terminal = GoalTerminalEvidence(
                    commit_frontier=True,
                    confidence=0.8,
                    state_id=node.state_id,
                    evidence=["channel-switch-frontier"],
                )
                status = "frontier"
            else:
                terminal = GoalTerminalEvidence(confidence=0.25, state_id=node.state_id)
                status = "not_found"
            return JourneyExecution(
                path=AutonomousPathResult(
                    phase=phase,
                    status=status,
                    steps=steps,
                    metrics=_metrics_for_autonomous_steps(steps),
                    state_ids=list(dict.fromkeys(state_ids)),
                    terminal=terminal,
                    required_fields=required_fields,
                ),
                edges=edges,
                primary_candidate=first_candidate,
                limitations=limitations,
            )
        if candidate and first_candidate is None:
            first_candidate = candidate
        visited_controls.add((node.state_id, control.control_id))
        decision = action_allowed(control, request.mode, _origin(page.url), allowed_origins)
        if not decision.allowed:
            edge = builder.add_edge(
                GraphEdge(
                    edge_id=f"edge-{uuid.uuid4().hex[:12]}",
                    phase=phase,
                    source_state_id=node.state_id,
                    action="click",
                    accessible_name=control.name,
                    selectors=control.selectors,
                    risk=decision.risk,
                    status="frontier",
                    evidence_tags=["commit_frontier", control_kind],
                    error=decision.reason,
                )
            ).model_copy(deep=True)
            edges.append(edge)
            evidence = await _step_evidence(
                text,
                control,
                node.screenshot_path,
                request.analyse_models,
                phase,
            )
            steps.append(
                FlowStepResult(
                    index=len(steps),
                    phase=phase,
                    action="click",
                    description=f"Commit frontier: {control.name}",
                    status="blocked_at_commit",
                    url_before=page.url,
                    url_after=page.url,
                    duration_ms=0,
                    page_transition=False,
                    screenshot_path=node.screenshot_path,
                    evidence=evidence,
                )
            )
            limitations.append(
                AutomationLimitation(
                    code="commit_blocked",
                    phase=phase,
                    message=decision.reason,
                    recoverable=request.mode == "controlled",
                    state_id=node.state_id,
                    evidence=[f"control:{control.name}"],
                )
            )
            terminal = GoalTerminalEvidence(
                commit_frontier=True,
                confidence=0.85,
                state_id=node.state_id,
                evidence=[f"control:{control.name}", f"risk:{decision.risk}"],
            )
            return JourneyExecution(
                path=AutonomousPathResult(
                    phase=phase,
                    status="frontier",
                    steps=steps,
                    metrics=_metrics_for_autonomous_steps(steps),
                    state_ids=list(dict.fromkeys(state_ids)),
                    terminal=terminal,
                    required_fields=required_fields,
                    control_rank=control.document_index + 1,
                ),
                edges=edges,
                primary_candidate=first_candidate,
                limitations=limitations,
            )

        resolved = await resolve_selector(page, control.selectors)
        if resolved is None:
            limitations.append(
                AutomationLimitation(
                    code="selector_drift",
                    phase=phase,
                    message=f"No selector could resolve the control '{control.name}'.",
                    recoverable=False,
                    state_id=node.state_id,
                )
            )
            break
        locator, used_strategy = resolved
        before_url = page.url
        started = datetime.now(UTC)
        try:
            await locator.click(timeout=10_000)
            await page.wait_for_timeout(350)
        except Exception as error:
            limitations.append(
                AutomationLimitation(
                    code="selector_drift",
                    phase=phase,
                    message=f"The selected control could not be executed: {type(error).__name__}.",
                    recoverable=False,
                    state_id=node.state_id,
                )
            )
            break
        duration = int((datetime.now(UTC) - started).total_seconds() * 1000)
        next_node, next_text = await observe_state(
            page,
            phase=phase,
            depth=depth + 1,
            run_directory=run_directory,
            sequence=sequence.next(),
            has_credentials=request.credentials is not None,
            redaction_values=_request_redaction_values(request),
        )
        next_node = builder.add_node(next_node).model_copy(deep=True)
        edge = builder.add_edge(
            GraphEdge(
                edge_id=f"edge-{uuid.uuid4().hex[:12]}",
                phase=phase,
                source_state_id=node.state_id,
                target_state_id=next_node.state_id,
                action="click",
                accessible_name=control.name,
                selectors=[used_strategy, *[item for item in control.selectors if item != used_strategy]],
                risk=decision.risk,
                status="completed",
                duration_ms=duration,
                page_transition=node.fingerprint != next_node.fingerprint,
                evidence_tags=[control_kind],
            )
        ).model_copy(deep=True)
        edges.append(edge)
        evidence = await _step_evidence(
            next_text,
            control,
            next_node.screenshot_path,
            request.analyse_models,
            phase,
        )
        steps.append(
            FlowStepResult(
                index=len(steps),
                phase=phase,
                action="click",
                description=f"{control_kind.title()}: {control.name}",
                status="completed",
                url_before=before_url,
                url_after=page.url,
                duration_ms=duration,
                page_transition=node.fingerprint != next_node.fingerprint,
                screenshot_path=next_node.screenshot_path,
                evidence=evidence,
            )
        )
        journey_started = journey_started or control_kind == "goal"
        terminal_after_action = _terminal_evidence(family, phase, next_text, next_node.state_id)
        if terminal_after_action.verified:
            terminal_state_ids = list(dict.fromkeys([*state_ids, next_node.state_id]))
            return JourneyExecution(
                path=AutonomousPathResult(
                    phase=phase,
                    status="completed",
                    steps=steps,
                    metrics=_metrics_for_autonomous_steps(steps),
                    state_ids=terminal_state_ids,
                    terminal=terminal_after_action,
                    required_fields=required_fields,
                    control_rank=first_candidate.control.document_index + 1 if first_candidate else None,
                ),
                edges=edges,
                primary_candidate=first_candidate,
                limitations=limitations,
            )
        if visited_states[next_node.state_id] >= 2:
            break
        if len(steps) >= request.policy.max_actions:
            limitations.append(
                AutomationLimitation(
                    code="state_budget_exhausted",
                    phase=phase,
                    message="The journey reached its action budget.",
                    state_id=next_node.state_id,
                )
            )
            break

    return JourneyExecution(
        path=AutonomousPathResult(
            phase=phase,
            status="not_found",
            steps=steps,
            metrics=_metrics_for_autonomous_steps(steps),
            state_ids=list(dict.fromkeys(state_ids)),
            terminal=GoalTerminalEvidence(confidence=0.2, state_id=state_ids[-1] if state_ids else None),
            required_fields=required_fields,
        ),
        edges=edges,
        primary_candidate=first_candidate,
        limitations=limitations,
    )


async def _establish_session(
    page: Page,
    request: AutonomousFlowRequest,
    builder: StateGraphBuilder,
    run_directory: Path,
    sequence: SequenceCounter,
) -> tuple[bool, list[AutomationLimitation]]:
    credentials = request.credentials
    if credentials is None:
        return False, [
            AutomationLimitation(
                code="credentials_required",
                phase="session",
                message="An authorized test account is required to inspect the authenticated exit journey.",
                recoverable=True,
            )
        ]
    target = str(credentials.login_url or request.url)
    navigation_failure = await _safe_goto(page, target, phase="session")
    if navigation_failure:
        return False, [navigation_failure]
    await page.wait_for_timeout(250)
    node, text = await observe_state(
        page,
        phase="session",
        depth=0,
        run_directory=run_directory,
        sequence=sequence.next(),
        has_credentials=True,
        redaction_values=_request_redaction_values(request),
    )
    node = builder.add_node(node).model_copy(deep=True)
    builder.add_root(node.state_id)
    if not await page.locator('input[type="password"]').count():
        login_controls = [
            control for control in node.controls if re.search(r"\b(log ?in|sign ?in)\b", control.name, re.I)
        ]
        if login_controls:
            resolved = await resolve_selector(page, login_controls[0].selectors)
            if resolved:
                locator, strategy = resolved
                before = node.state_id
                await locator.click(timeout=10_000)
                await page.wait_for_timeout(300)
                next_node, text = await observe_state(
                    page,
                    phase="session",
                    depth=1,
                    run_directory=run_directory,
                    sequence=sequence.next(),
                    has_credentials=True,
                    redaction_values=_request_redaction_values(request),
                )
                next_node = builder.add_node(next_node).model_copy(deep=True)
                builder.add_edge(
                    GraphEdge(
                        edge_id=f"edge-{uuid.uuid4().hex[:12]}",
                        phase="session",
                        source_state_id=before,
                        target_state_id=next_node.state_id,
                        action="click",
                        accessible_name=login_controls[0].name,
                        selectors=[strategy],
                        risk="authentication",
                        status="completed",
                        page_transition=before != next_node.state_id,
                    )
                )
                node = next_node

    password = page.locator('input[type="password"]').first
    if not await password.count():
        limitations = detect_limitations(
            text,
            await _redacted_page_html(page, request),
            page.url,
            True,
            "session",
        )
        return node.authentication_state == "authenticated", limitations or [
            AutomationLimitation(
                code="credentials_required",
                phase="session",
                message="The automatic login form could not be located.",
                recoverable=True,
                state_id=node.state_id,
            )
        ]
    username = page.locator(
        'input[type="email"],input[autocomplete="username"],input[name*="email" i],input[name*="user" i],input[type="text"]'
    ).first
    if not await username.count():
        return False, [
            AutomationLimitation(
                code="credentials_required",
                phase="session",
                message="The automatic username field could not be located.",
                recoverable=True,
                state_id=node.state_id,
            )
        ]
    await username.fill(credentials.username.get_secret_value())
    await password.fill(credentials.password.get_secret_value())
    submit = page.locator('button[type="submit"],input[type="submit"]').first
    if not await submit.count():
        submit = page.get_by_role("button", name=re.compile(r"log ?in|sign ?in|continue", re.I)).first
    if not await submit.count():
        return False, [
            AutomationLimitation(
                code="credentials_required",
                phase="session",
                message="The automatic login submit control could not be located.",
                recoverable=True,
                state_id=node.state_id,
            )
        ]
    try:
        await submit.click(timeout=10_000)
        await page.wait_for_timeout(600)
    except Exception:
        return False, [
            AutomationLimitation(
                code="authentication_failed",
                phase="session",
                message="The authorized login attempt could not be completed.",
                recoverable=True,
                state_id=node.state_id,
            )
        ]

    if credentials.one_time_code and await page.locator('[autocomplete="one-time-code"]').count():
        await page.locator('[autocomplete="one-time-code"]').first.fill(credentials.one_time_code.get_secret_value())
        otp_submit = page.locator('button[type="submit"],input[type="submit"]').first
        if await otp_submit.count():
            await otp_submit.click(timeout=10_000)
            await page.wait_for_timeout(500)

    final_node, final_text = await observe_state(
        page,
        phase="session",
        depth=2,
        run_directory=run_directory,
        sequence=sequence.next(),
        has_credentials=True,
        redaction_values=_request_redaction_values(request),
    )
    final_node = builder.add_node(final_node).model_copy(deep=True)
    limitations = detect_limitations(
        final_text,
        await _redacted_page_html(page, request),
        page.url,
        True,
        "session",
    )
    failure = any(item.code in {"authentication_failed", "captcha_required", "mfa_required", "email_verification_required"} for item in limitations)
    password_still_visible = bool(await page.locator('input[type="password"]').count())
    authenticated = not failure and (final_node.authentication_state == "authenticated" or not password_still_visible)
    if not authenticated and not limitations:
        limitations.append(
            AutomationLimitation(
                code="authentication_failed",
                phase="session",
                message="The supplied test credentials did not establish a verifiable session.",
                recoverable=True,
                state_id=final_node.state_id,
            )
        )
    return authenticated, limitations


async def _discover_families(
    page: Page,
    request: AutonomousFlowRequest,
    builder: StateGraphBuilder,
    run_directory: Path,
    sequence: SequenceCounter,
    allowed_origins: set[str],
    limitations: list[AutomationLimitation],
) -> list[GoalFamily]:
    explicit = [value for value in request.goal_families if value != "auto"]
    if explicit:
        return explicit  # type: ignore[return-value]
    navigation_failure = await _safe_goto(page, str(request.url), phase="acquisition")
    if navigation_failure:
        limitations.append(navigation_failure)
        return []
    await page.wait_for_timeout(250)
    node, text = await observe_state(
        page,
        phase="acquisition",
        depth=0,
        run_directory=run_directory,
        sequence=sequence.next(),
        has_credentials=request.credentials is not None,
        redaction_values=_request_redaction_values(request),
    )
    node = builder.add_node(node).model_copy(deep=True)
    builder.add_root(node.state_id)
    candidates = rank_intent_candidates(
        node.controls,
        context=[*node.headings, node.dialog_text, text[:4000]],
        goal_families=["auto"],
        minimum_score=0.36,
    )
    families: list[GoalFamily] = []
    for candidate in candidates:
        if candidate.phase == "acquisition" and candidate.family not in families:
            families.append(candidate.family)
    if families:
        return families[:4]

    # One-hop safe expansion catches menus and pricing/account hubs without
    # turning discovery into an unrestricted crawler.
    hubs = [control for control in node.controls if HUB_RE["acquisition"].search(f"{control.name} {control.href or ''}")]
    for control in hubs[: request.policy.max_candidates_per_state]:
        decision = action_allowed(control, request.mode, _origin(page.url), allowed_origins)
        if not decision.allowed or decision.risk not in {"read_only", "reversible", "authentication"}:
            continue
        resolved = await resolve_selector(page, control.selectors)
        if resolved is None:
            continue
        locator, strategy = resolved
        try:
            await locator.click(timeout=5_000)
            await page.wait_for_timeout(250)
            next_node, next_text = await observe_state(
                page,
                phase="acquisition",
                depth=1,
                run_directory=run_directory,
                sequence=sequence.next(),
                has_credentials=request.credentials is not None,
                redaction_values=_request_redaction_values(request),
            )
            next_node = builder.add_node(next_node).model_copy(deep=True)
            builder.add_edge(
                GraphEdge(
                    edge_id=f"edge-{uuid.uuid4().hex[:12]}",
                    phase="acquisition",
                    source_state_id=node.state_id,
                    target_state_id=next_node.state_id,
                    action="click",
                    accessible_name=control.name,
                    selectors=[strategy],
                    risk=decision.risk,
                    status="completed",
                    page_transition=node.state_id != next_node.state_id,
                    evidence_tags=["discovery"],
                )
            )
            expanded = rank_intent_candidates(
                next_node.controls,
                context=[*next_node.headings, next_node.dialog_text, next_text[:4000]],
                goal_families=["auto"],
                minimum_score=0.36,
            )
            for candidate in expanded:
                if candidate.phase == "acquisition" and candidate.family not in families:
                    families.append(candidate.family)
        finally:
            navigation_failure = await _safe_goto(page, str(request.url), phase="acquisition")
            if navigation_failure:
                limitations.append(navigation_failure)
                break
            await page.wait_for_timeout(150)
    return families[:4]


def _pairing(acquisition: JourneyExecution, exit_flow: JourneyExecution, family: GoalFamily) -> tuple[float, str]:
    if acquisition.primary_candidate and exit_flow.primary_candidate:
        pairs = pair_goal_candidates([acquisition.primary_candidate, exit_flow.primary_candidate], minimum_confidence=0.0)
        if pairs:
            return pairs[0].confidence, pairs[0].signature
        return min(acquisition.primary_candidate.score, exit_flow.primary_candidate.score) * 0.75, f"{family}:default"
    if acquisition.primary_candidate:
        return acquisition.primary_candidate.score * 0.6, f"{family}:default"
    return 0.0, f"{family}:default"


def _selector_stability(edges: Sequence[GraphEdge]) -> float:
    actionable = [edge for edge in edges if edge.selectors]
    if not actionable:
        return 0.4
    stable = sum(any(selector.stable and selector.kind != "css" for selector in edge.selectors) for edge in actionable)
    return min(1.0, 0.55 + 0.45 * stable / len(actionable))


async def _replay_edges(
    page: Page,
    request: AutonomousFlowRequest,
    edges: Sequence[GraphEdge],
    allowed_origins: set[str],
) -> bool:
    for edge in edges:
        if edge.status == "frontier":
            return await resolve_selector(page, edge.selectors) is not None
        resolved = await resolve_selector(page, edge.selectors)
        if resolved is None:
            return False
        locator, _strategy = resolved
        try:
            if edge.action == "fill":
                input_type = await locator.get_attribute("type") or "text"
                dummy = ObservedControl(
                    control_id="replay",
                    role="textbox",
                    name=edge.accessible_name,
                    input_type=input_type,
                )
                await locator.fill(await _generic_value(locator, dummy))
            elif edge.action == "select":
                options = await locator.locator("option:not([disabled])").count()
                await locator.select_option(index=1 if options > 1 else 0)
            elif edge.action == "check":
                await locator.check()
            else:
                await locator.click(timeout=8_000)
                await page.wait_for_timeout(250)
        except Exception:
            return False
    return True


async def _measure_replay_stability(
    browser,
    request: AutonomousFlowRequest,
    allowed_origins: set[str],
    acquisition: JourneyExecution,
    exit_flow: JourneyExecution,
    builder: StateGraphBuilder,
    run_directory: Path,
    sequence: SequenceCounter,
) -> tuple[int, int]:
    attempts = request.policy.replay_attempts
    successes = 1
    for _attempt in range(1, attempts):
        context = await _configure_context(browser, request, allowed_origins)
        page = await context.new_page()
        try:
            if await _safe_goto(page, str(request.url), phase="acquisition"):
                continue
            acquisition_ok = await _replay_edges(page, request, acquisition.edges, allowed_origins)
            if not acquisition_ok:
                continue
            if request.credentials and acquisition.path.status == "frontier":
                authenticated, _limitations = await _establish_session(
                    page, request, builder, run_directory, sequence
                )
                if not authenticated:
                    continue
            exit_ok = await _replay_edges(page, request, exit_flow.edges, allowed_origins)
            if exit_ok:
                successes += 1
        finally:
            await context.close()
    return attempts, successes


async def _model_status(analyse_models: bool) -> tuple[ModelPipelineStatus, list[str]]:
    if not analyse_models:
        return ModelPipelineStatus(bert="not_requested", yolo="not_requested"), []
    warnings: list[str] = []

    def probe() -> tuple[str, str]:
        bert, yolo = "available", "available"
        try:
            from app.scans.service import get_classifier

            get_classifier()
        except Exception as error:
            bert = "unavailable"
            warnings.append(f"BERT supporting evidence unavailable: {type(error).__name__}.")
        try:
            from app.scans.service import get_visual_detector

            get_visual_detector()
        except Exception as error:
            yolo = "unavailable"
            warnings.append(f"YOLO supporting evidence unavailable: {type(error).__name__}.")
        return bert, yolo

    bert, yolo = await asyncio.to_thread(probe)
    return ModelPipelineStatus(bert=bert, yolo=yolo), warnings


async def perform_autonomous_analysis(
    request: AutonomousFlowRequest,
    *,
    run_id: str | None = None,
    progress_callback: ProgressCallback | None = None,
    cancellation_callback: CancellationCallback | None = None,
) -> AutonomousFlowResult:
    configure_runtime_environment()
    run_id = run_id or f"auto-{uuid.uuid4().hex[:12]}"
    run_directory = RUNTIME_DATA_DIR / "autonomous_flow_runs" / run_id
    run_directory.mkdir(parents=True, exist_ok=True)
    sequence = SequenceCounter()
    await _progress(progress_callback, "validating", 5)
    allowed_origins = await _approved_origins(request)
    await _ensure_not_cancelled(cancellation_callback)
    await _progress(progress_callback, "static_scan", 12)
    model_status, warnings = await _model_status(request.analyse_models)
    builder = StateGraphBuilder()
    all_limitations: list[AutomationLimitation] = []
    goals: list[GoalPairAnalysis] = []
    site_audit = SiteCrawlReport()
    goal_entry_urls: dict[GoalFamily, str] = {}

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        frontend_behavior = FrontendBehaviorReport()
        if request.scope == "full_site":
            await _progress(progress_callback, "site_crawl", 14)
            await _ensure_not_cancelled(cancellation_callback)

            async def site_context_factory() -> BrowserContext:
                return await _configure_context(browser, request, allowed_origins)

            async def site_progress(completed: int, discovered: int) -> None:
                denominator = max(request.policy.max_pages, discovered, 1)
                value = 14 + min(31, int(completed / denominator * 31))
                await _progress(progress_callback, "site_crawl", value)

            try:
                crawl = await crawl_site(
                    browser,
                    request,
                    site_context_factory,
                    run_directory,
                    cancellation_callback=cancellation_callback,
                    progress_callback=site_progress,
                )
                site_audit = crawl.report
                goal_entry_urls = crawl.goal_entry_urls
                frontend_behavior = crawl.behavior
                warnings.extend(site_audit.warnings)
            except Exception as error:
                warnings.append(
                    f"Full-site crawl could not complete: {type(error).__name__}. "
                    "The paired-flow analyzer continued from the supplied URL."
                )
                site_audit = SiteCrawlReport(
                    status="completed_with_warnings",
                    start_url=str(request.url),
                    origin=_origin(str(request.url)),
                    pages_failed=1,
                    warnings=[warnings[-1]],
                )
        elif request.analyse_behavior:
            await _progress(progress_callback, "runtime_analysis", 15)
            await _ensure_not_cancelled(cancellation_callback)

            async def behavior_context_factory() -> BrowserContext:
                return await _configure_context(browser, request, allowed_origins)

            frontend_behavior = await analyze_frontend_behavior(
                browser,
                str(request.url),
                behavior_context_factory,
                run_directory,
                observation_seconds=request.policy.behavior_observation_seconds,
                analyse_models=request.analyse_models,
                sensitive_values=_request_redaction_values(request),
            )
            warnings.extend(frontend_behavior.warnings)
        explicit_families = [value for value in request.goal_families if value != "auto"]
        if request.scope == "full_site" and (goal_entry_urls or explicit_families):
            families = explicit_families or list(goal_entry_urls)
        else:
            discovery_context = await _configure_context(browser, request, allowed_origins)
            discovery_page = await discovery_context.new_page()
            try:
                await _progress(progress_callback, "discovering_acquisition", 47 if request.scope == "full_site" else 20)
                families = await _discover_families(
                    discovery_page,
                    request,
                    builder,
                    run_directory,
                    sequence,
                    allowed_origins,
                    all_limitations,
                )
            finally:
                await discovery_context.close()

        if not families:
            all_limitations.append(
                AutomationLimitation(
                    code="goal_not_found",
                    phase="acquisition",
                    message="No supported acquisition goal was discovered within the safe exploration budget.",
                )
            )
        for index, family in enumerate(families):
            await _ensure_not_cancelled(cancellation_callback)
            progress_start = 48 if request.scope == "full_site" else 25
            progress_span = 15 if request.scope == "full_site" else 55
            base_progress = progress_start + int(index / max(1, len(families)) * progress_span)
            end_progress = progress_start + int((index + 1) / max(1, len(families)) * progress_span)
            progress_width = max(1, end_progress - base_progress)
            session_progress = min(end_progress, base_progress + max(1, progress_width // 3))
            exit_progress = min(end_progress, base_progress + max(1, progress_width * 2 // 3))
            family_request = request.model_copy(update={"url": goal_entry_urls.get(family, request.url)})
            goal_builder = StateGraphBuilder() if request.scope == "full_site" else builder
            context = await _configure_context(browser, family_request, allowed_origins)
            page = await context.new_page()
            try:
                await _progress(progress_callback, "discovering_acquisition", base_progress)
                acquisition = await _execute_journey(
                    page,
                    family_request,
                    family,
                    "acquisition",
                    goal_builder,
                    run_directory,
                    sequence,
                    allowed_origins,
                    cancellation_callback=cancellation_callback,
                )
                all_limitations.extend(acquisition.limitations)
                if not acquisition.primary_candidate:
                    continue

                exit_ready = family_request.mode == "controlled" and acquisition.path.status == "completed"
                session_limitations: list[AutomationLimitation] = []
                if not exit_ready and family in AUTH_REQUIRED_FAMILIES:
                    await _progress(progress_callback, "establishing_session", session_progress)
                    exit_ready, session_limitations = await _establish_session(
                        page, family_request, goal_builder, run_directory, sequence
                    )
                    all_limitations.extend(session_limitations)
                elif not exit_ready:
                    navigation_failure = await _safe_goto(page, str(family_request.url), phase="exit")
                    if navigation_failure:
                        session_limitations.append(navigation_failure)
                        all_limitations.append(navigation_failure)
                    else:
                        exit_ready = True

                await _progress(progress_callback, "discovering_exit", exit_progress)
                if exit_ready:
                    exit_flow = await _execute_journey(
                        page,
                        family_request,
                        family,
                        "exit",
                        goal_builder,
                        run_directory,
                        sequence,
                        allowed_origins,
                        start_from_current=True,
                        cancellation_callback=cancellation_callback,
                    )
                else:
                    exit_flow = JourneyExecution(
                        path=_empty_path("exit", "needs_input"),
                        limitations=session_limitations,
                    )
                all_limitations.extend(exit_flow.limitations)

                pairing_confidence, signature = _pairing(acquisition, exit_flow, family)
                await _progress(progress_callback, "replaying", end_progress)
                replay_attempts, replay_successes = await _measure_replay_stability(
                    browser,
                    family_request,
                    allowed_origins,
                    acquisition,
                    exit_flow,
                    goal_builder,
                    run_directory,
                    sequence,
                )
                graph = goal_builder.build()
                # Field fills are represented as same-state graph edges.  They
                # are not redirect loops; require a cycle to traverse at least
                # two distinct observed states before scoring this mechanism.
                loop_states = [
                    state
                    for cycle in detect_redirect_loops(graph, phase="exit")
                    if len(set(cycle[:-1])) >= 2
                    for state in cycle[:-1]
                ]
                terminal_states = {
                    value
                    for value in (acquisition.path.terminal.state_id, exit_flow.path.terminal.state_id)
                    if value
                }
                dead_ends = detect_dead_ends(graph, phase="exit", terminal_state_ids=terminal_states)
                mechanisms = detect_mechanisms(
                    acquisition.path,
                    exit_flow.path,
                    graph.nodes,
                    graph.edges,
                    loop_state_ids=loop_states,
                    dead_end_state_ids=dead_ends if exit_flow.path.status == "not_found" else [],
                )
                combined_limitations = [*acquisition.limitations, *session_limitations, *exit_flow.limitations]
                confidence = build_confidence_breakdown(
                    goal_equivalence=pairing_confidence,
                    acquisition_terminal=acquisition.path.terminal,
                    exit_terminal=exit_flow.path.terminal,
                    replay_attempts=replay_attempts,
                    replay_successes=replay_successes,
                    selector_stability=_selector_stability([*acquisition.edges, *exit_flow.edges]),
                    evidence_quality=0.9 if mechanisms else 0.7 if exit_flow.path.steps else 0.4,
                    limitations=combined_limitations,
                    missing_credentials=(
                        family in AUTH_REQUIRED_FAMILIES
                        and family_request.credentials is None
                        and family_request.mode != "controlled"
                    ),
                    calibrated=False,
                )
                overall = roach_motel_finding(
                    acquisition.path,
                    exit_flow.path,
                    mechanisms,
                    confidence,
                    pairing_confidence,
                )
                goals.append(
                    GoalPairAnalysis(
                        goal_id=str(uuid.uuid4()),
                        family=family,
                        signature=signature,
                        label=family.replace("_", " ").title(),
                        pairing_confidence=round(pairing_confidence, 3),
                        acquisition=acquisition.path,
                        exit=exit_flow.path,
                        overall_finding=overall,
                        mechanism_findings=mechanisms,
                        confidence_gate=confidence,
                        limitations=combined_limitations,
                    )
                )
            finally:
                if goal_builder is not builder:
                    goal_graph = goal_builder.build()
                    for node in goal_graph.nodes:
                        builder.add_node(node)
                    for root in goal_graph.root_state_ids:
                        builder.add_root(root)
                    for edge in goal_graph.edges:
                        builder.add_edge(edge)
                await context.close()
        await browser.close()

    await _progress(progress_callback, "scoring", 90)
    unique_limitations: list[AutomationLimitation] = []
    seen_limitations: set[tuple[str, str | None, str | None]] = set()
    for limitation in all_limitations:
        key = (limitation.code, limitation.phase, limitation.state_id)
        if key not in seen_limitations:
            seen_limitations.add(key)
            unique_limitations.append(limitation)
    candidates = sum(goal.overall_finding.status == "detected" for goal in goals)
    clean = sum(goal.overall_finding.status == "not_detected" for goal in goals)
    inconclusive = sum(goal.overall_finding.status == "inconclusive" for goal in goals)
    behavior_detected = sum(item.status == "detected" for item in frontend_behavior.findings)
    behavior_suspicious = sum(item.status == "suspicious" for item in frontend_behavior.findings)
    behavior_inconclusive = sum(item.status == "inconclusive" for item in frontend_behavior.findings)
    input_resolvable = any(item.code in RESUMABLE_LIMITATIONS for item in unique_limitations)
    if candidates or behavior_detected:
        outcome = "candidate"
    elif (goals and not inconclusive and not behavior_suspicious) or (
        not goals and frontend_behavior.findings and not behavior_suspicious and not behavior_inconclusive
    ):
        outcome = "not_detected"
    elif input_resolvable:
        outcome = "needs_assistance"
    else:
        outcome = "inconclusive"
    flow_confidences = [goal.confidence_gate.overall for goal in goals]
    behavior_confidences = [
        item.confidence for item in frontend_behavior.findings if item.status in {"detected", "suspicious", "not_detected"}
    ]
    if candidates:
        confidence_value = max((goal.confidence_gate.overall for goal in goals if goal.overall_finding.status == "detected"), default=0.0)
    elif behavior_detected:
        confidence_value = max((item.confidence for item in frontend_behavior.findings if item.status == "detected"), default=0.0)
    elif flow_confidences:
        confidence_value = min(flow_confidences)
    else:
        confidence_value = max(behavior_confidences, default=0.0)
    if confidence_value < 0.65:
        gate = "inconclusive"
    elif confidence_value < 0.85 or any(goal.confidence_gate.gate == "report_with_caution" for goal in goals):
        gate = "report_with_caution"
    else:
        gate = "auto_report"
    summary = AutonomousRunSummary(
        goals_discovered=len(goals),
        goals_completed=sum(
            goal.acquisition.terminal.verified and goal.exit.terminal.verified for goal in goals
        ),
        roach_motel_candidates=candidates,
        clean_goals=clean,
        inconclusive_goals=inconclusive,
        outcome=outcome,
        confidence=round(confidence_value, 3),
        gate=gate,
        requires_assistance=outcome == "needs_assistance",
        behavioral_detected=behavior_detected,
        behavioral_suspicious=behavior_suspicious,
        pages_discovered=site_audit.pages_discovered,
        pages_scanned=site_audit.pages_scanned,
        pages_failed=site_audit.pages_failed,
    )
    await _progress(progress_callback, "persisting", 97)
    return AutonomousFlowResult(
        run_id=run_id,
        url=str(request.url),
        pipeline_version=AUTONOMOUS_PIPELINE_VERSION,
        summary=summary,
        goals=goals,
        graph=builder.build(),
        limitations=unique_limitations,
        model_status=model_status,
        frontend_behavior=frontend_behavior,
        site_audit=site_audit,
        warnings=warnings,
    )

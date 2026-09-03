from __future__ import annotations

import base64
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from playwright.async_api import async_playwright

from app.core.config import MAX_SCREENSHOT_BYTES, RUNTIME_DATA_DIR, configure_runtime_environment
from app.flow_analysis.autonomous_schemas import AutonomousFlowResult


def _text(value: object) -> str:
    return escape(str(value), quote=True)


def _title(value: object) -> str:
    return _text(str(value).replace("_", " ").title())


def _percent(value: float) -> str:
    return f"{round(value * 100)}%"


def _metric(label: str, value: object) -> str:
    return f'<div class="metric"><span>{_text(label)}</span><b>{_text(value)}</b></div>'


def _evidence_image(path_value: str, run_id: str) -> str:
    """Embed only a bounded PNG that belongs to this exact run directory."""

    root = (RUNTIME_DATA_DIR / "autonomous_flow_runs" / run_id).resolve()
    name = Path(path_value).name
    if not name.endswith(".png"):
        return ""
    target = (root / name).resolve()
    if target.parent != root or not target.is_file():
        return ""
    payload = target.read_bytes()
    if not payload or len(payload) > MAX_SCREENSHOT_BYTES:
        return ""
    encoded = base64.b64encode(payload).decode("ascii")
    return (
        '<figure><img class="shot" src="data:image/png;base64,'
        + encoded
        + f'" alt="Redacted evidence screenshot"><figcaption>{_text(name)}</figcaption></figure>'
    )


def _screenshot_section(result: AutonomousFlowResult) -> str:
    paths = list(result.frontend_behavior.screenshots)
    paths.extend(path for finding in result.frontend_behavior.findings for path in finding.screenshot_paths)
    for goal in result.goals:
        for path_result in (goal.acquisition, goal.exit):
            paths.extend(step.screenshot_path for step in path_result.steps if step.screenshot_path)
    paths.extend(node.screenshot_path for node in result.graph.nodes if node.screenshot_path)
    paths.extend(page.screenshot_path for page in result.site_audit.pages if page.screenshot_path)
    unique_paths = list(dict.fromkeys(path for path in paths if path))[:24]
    images = ''.join(_evidence_image(path, result.run_id) for path in unique_paths)
    return (
        f'<section class="card"><h2>Redacted screenshots</h2><div class="shots">{images}</div></section>'
        if images
        else ""
    )


def _finding_row(finding) -> str:
    return (
        '<div class="finding">'
        f'<div><b>{_title(finding.category)}</b> '
        f'<span class="pill {finding.status}">{_title(finding.status)}</span> '
        f'<span class="pill {finding.severity}">{_title(finding.severity)}</span></div>'
        f'<p>{_text(finding.rationale)}</p>'
        f'<small>Score {_text(f"{finding.score:.1f}/100")} · confidence {_text(_percent(finding.confidence))}</small>'
        + ''.join(f'<div class="evidence">{_text(item)}</div>' for item in finding.evidence_refs)
        + '</div>'
    )


def _path_table(path) -> str:
    metrics = path.metrics
    rows = ''.join(
        '<tr>'
        f'<td>{step.index + 1}</td><td>{_title(step.action)}</td><td>{_text(step.description)}</td>'
        f'<td>{_title(step.status)}</td><td>{step.duration_ms} ms</td>'
        '</tr>'
        for step in path.steps
    )
    terminal = path.terminal
    terminal_state = "verified" if terminal.verified else "safe commit frontier" if terminal.commit_frontier else "not verified"
    return (
        f'<section class="path"><h4>{_title(path.phase)} <span class="pill">{_title(path.status)}</span></h4>'
        '<div class="metrics">'
        + _metric("Effort", f"{metrics.effort_score:.2f}")
        + _metric("Actions", metrics.meaningful_actions)
        + _metric("Fields", metrics.form_fields)
        + _metric("Transitions", metrics.page_transitions)
        + '</div>'
        f'<p class="muted">Terminal: {_text(terminal_state)} · confidence {_text(_percent(terminal.confidence))}</p>'
        + (f'<table><thead><tr><th>#</th><th>Action</th><th>Description</th><th>Status</th><th>Time</th></tr></thead><tbody>{rows}</tbody></table>' if rows else '<p class="muted">No executable steps were recorded.</p>')
        + '</section>'
    )


def _goal_section(goal) -> str:
    mechanisms = ''.join(_finding_row(item) for item in goal.mechanism_findings)
    limitations = ''.join(
        f'<div class="warning"><b>{_title(item.code)}</b><br>{_text(item.message)}</div>'
        for item in goal.limitations
    )
    confidence = goal.confidence_gate
    return (
        '<article class="card break-avoid">'
        f'<h3>{_text(goal.label)}</h3><p class="muted">{_title(goal.family)} · {_text(goal.signature)}</p>'
        + _finding_row(goal.overall_finding)
        + '<div class="two">' + _path_table(goal.acquisition) + _path_table(goal.exit) + '</div>'
        + '<h4>Confidence gate</h4><div class="metrics">'
        + _metric("Overall", _percent(confidence.overall))
        + _metric("Pairing", _percent(goal.pairing_confidence))
        + _metric("Replay", _percent(confidence.replay_stability))
        + _metric("Evidence", _percent(confidence.evidence_quality))
        + _metric("Gate", _title(confidence.gate))
        + _metric("Review", _title(confidence.review))
        + '</div>'
        + (f'<h4>Obstruction mechanisms</h4>{mechanisms}' if mechanisms else '<p class="ok">No obstruction mechanism was detected.</p>')
        + limitations
        + '</article>'
    )


def _behavior_finding(item) -> str:
    values = ''.join(
        _metric(label, value if value is not None else "—")
        for label, value in (
            ("Initial", item.initial_value),
            ("Observed", item.observed_value),
            ("After reload", item.after_reload),
            ("Clean session", item.clean_session_value),
        )
    )
    timeline_rows = ''.join(
        f'<tr><td>{sample.elapsed_ms / 1000:.1f}s</td><td>{_title(sample.event)}</td>'
        f'<td>{_text(sample.value)}</td></tr>'
        for sample in item.timeline
    )
    code = ''.join(
        '<div class="code">'
        f'<small>{_title(value.source)} · {_text(value.asset_url or "inline/rendered source")} · SHA-256 {_text(value.sha256 or "unavailable")}</small>'
        f'<pre>{_text(value.excerpt)}</pre></div>'
        for value in item.code_evidence
    )
    tags = ''.join(
        f'<span class="pill">{_text(prefix)}: {_title(value)}</span>'
        for prefix, values_list in (("BERT", item.bert_categories), ("YOLO", item.visual_cues))
        for value in values_list
    )
    return (
        '<div class="finding">'
        f'<div><b>{_title(item.category)}</b> <span class="pill {item.status}">{_title(item.status)}</span> '
        f'<span class="pill {item.severity}">{_title(item.severity)}</span></div>'
        f'<p>{_text(item.rationale)}</p>'
        + (f'<p class="muted">Affected page: {_text(item.page_url)}</p>' if item.page_url else "")
        + f'<small>Parent taxonomy: {_text(item.dark_pattern_category)} · score {_text(f"{item.score:.1f}/100")} · confidence {_text(_percent(item.confidence))}</small>'
        f'<div class="metrics">{values}</div>{tags}'
        + ''.join(f'<div class="evidence">{_text(value)}</div>' for value in item.evidence)
        + ''.join(f'<div class="counter">Counter-evidence: {_text(value)}</div>' for value in item.counter_evidence)
        + (f'<h4>Behavior timeline</h4><table><thead><tr><th>Elapsed</th><th>Event</th><th>Value</th></tr></thead><tbody>{timeline_rows}</tbody></table>' if timeline_rows else "")
        + (f'<h4>Relevant public code evidence</h4>{code}' if code else "")
        + '</div>'
    )


def _site_audit_section(result: AutonomousFlowResult) -> str:
    report = result.site_audit
    if report.status == "not_requested":
        return ""
    coverage = "Complete within discovered same-origin links" if report.coverage_complete else "Bounded or partial"
    categories = "".join(
        f'<tr><td>{_title(category)}</td><td>{count}</td></tr>'
        for category, count in report.category_counts.items()
    )
    page_rows = []
    for page in report.pages:
        text_categories = ", ".join(
            f"{item.category} ({_percent(item.model_confidence)})" for item in page.text_findings
        ) or "None"
        visual_categories = ", ".join(
            f"{item.cue} ({_percent(item.model_confidence)})" for item in page.visual_cues
        ) or "None"
        behavior_categories = ", ".join(
            f"{item.category} ({item.status})" for item in page.frontend_behavior.findings
        ) or "None"
        text_evidence = "".join(
            '<div class="evidence">'
            f'<b>{_title(item.category)}</b> · confidence {_text(_percent(item.model_confidence))} '
            f'· source {_title(item.source)}<br>{_text(item.phrase)}'
            + (
                f'<br>Box x={item.bounding_box.x:.1f}, y={item.bounding_box.y:.1f}, '
                f'w={item.bounding_box.width:.1f}, h={item.bounding_box.height:.1f}'
                if item.bounding_box else ""
            )
            + '</div>'
            for item in page.text_findings
        )
        visual_evidence = "".join(
            '<div class="evidence">'
            f'<b>YOLO: {_title(item.cue)}</b> · confidence {_text(_percent(item.model_confidence))}<br>'
            f'Box x={item.bounding_box.x:.1f}, y={item.bounding_box.y:.1f}, '
            f'w={item.bounding_box.width:.1f}, h={item.bounding_box.height:.1f}'
            + '</div>'
            for item in page.visual_cues
        )
        page_rows.append(
            '<article class="finding break-avoid">'
            f'<div><b>{_text(page.title or "Untitled page")}</b> '
            f'<span class="pill {page.status}">{_title(page.status)}</span></div>'
            f'<p class="muted">{_text(page.url)} · depth {page.depth}</p>'
            f'<p><b>BERT:</b> {_text(text_categories)}<br>'
            f'<b>YOLO:</b> {_text(visual_categories)}<br>'
            f'<b>Dynamic:</b> {_text(behavior_categories)}</p>'
            f'<small>Text blocks analyzed: {page.text_blocks_analyzed} · '
            f'fusion links: {len(page.fusion_links)} · '
            f'goal families: {_text(", ".join(page.discovered_goal_families) or "none")}</small>'
            + text_evidence
            + visual_evidence
            + (f'<div class="warning">{_text(page.error)}</div>' if page.error else "")
            + '</article>'
        )
    warnings = "".join(f'<div class="warning">{_text(value)}</div>' for value in report.warnings)
    return (
        '<section class="card"><h2>Whole-site crawl coverage</h2>'
        '<div class="metrics">'
        + _metric("Coverage", coverage)
        + _metric("Discovered URLs", report.pages_discovered)
        + _metric("Pages scanned", report.pages_scanned)
        + _metric("Pages failed", report.pages_failed)
        + _metric("Page limit reached", "Yes" if report.max_pages_reached else "No")
        + _metric("Depth limit reached", "Yes" if report.max_depth_reached else "No")
        + '</div>'
        + (f'<h3>Aggregated categories</h3><table><thead><tr><th>Category or visual cue</th><th>Occurrences</th></tr></thead><tbody>{categories}</tbody></table>' if categories else '<p class="ok">No static or behavioral candidate category was detected.</p>')
        + warnings
        + '<h3>Per-page results</h3>'
        + ''.join(page_rows)
        + '</section>'
    )


def _behavior_section(result: AutonomousFlowResult) -> str:
    report = result.frontend_behavior
    if report.status == "not_requested":
        return '<section class="card"><h2>Dynamic frontend behaviour</h2><p class="muted">Not requested for this run.</p></section>'
    artifacts = report.artifacts
    findings = ''.join(_behavior_finding(item) for item in report.findings)
    snapshot_rows = ''.join(
        f'<tr><td>{snapshot.elapsed_ms / 1000:.1f}s</td><td>{_title(snapshot.phase)}</td>'
        f'<td>{len(snapshot.timers)}</td><td>{len(snapshot.claims)}</td>'
        f'<td>{len(snapshot.choices)}</td><td>{len(snapshot.dialogs)}</td></tr>'
        for snapshot in report.dom_snapshots
    )
    network_rows = ''.join(
        f'<tr><td>{_text(item.method)}</td><td>{_title(item.resource_type)}</td>'
        f'<td>{_text(item.status if item.status is not None else "—")}</td><td>{_text(item.url)}</td></tr>'
        for item in artifacts.network_observations[:30]
    )
    artifact_details = (
        f'<p class="muted">Original HTML SHA-256: {_text(artifacts.original_html_sha256 or "unavailable")}<br>'
        f'Rendered DOM SHA-256: {_text(artifacts.rendered_dom_sha256 or "unavailable")}</p>'
    )
    return (
        '<section class="card"><h2>Dynamic frontend behaviour</h2>'
        f'<p class="muted">{_title(report.status)} · observed {report.observation_seconds} seconds. {_text(report.note)}</p>'
        '<div class="metrics">'
        + _metric("Findings", len(report.findings))
        + _metric("DOM snapshots", len(report.dom_snapshots))
        + _metric("Network events", len(artifacts.network_observations))
        + _metric("Code excerpts", len(artifacts.code_evidence))
        + _metric("Screenshots", len(report.screenshots))
        + '</div>'
        + artifact_details
        + (findings or '<p class="ok">No dynamic frontend candidate was found.</p>')
        + (f'<h3>DOM observation timeline</h3><table><thead><tr><th>Elapsed</th><th>Phase</th><th>Timers</th><th>Claims</th><th>Choices</th><th>Dialogs</th></tr></thead><tbody>{snapshot_rows}</tbody></table>' if snapshot_rows else "")
        + (f'<h3>Redacted network observations</h3><table><thead><tr><th>Method</th><th>Type</th><th>Status</th><th>URL</th></tr></thead><tbody>{network_rows}</tbody></table>' if network_rows else "")
        + ''.join(f'<div class="warning">{_text(value)}</div>' for value in report.warnings)
        + '</section>'
    )


def build_report_html(result: AutonomousFlowResult) -> str:
    summary = result.summary
    created = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    warnings = ''.join(f'<div class="warning">{_text(item)}</div>' for item in result.warnings)
    limitations = ''.join(
        f'<div class="warning"><b>{_title(item.code)}</b>{" · " + _title(item.phase) if item.phase else ""}<br>{_text(item.message)}</div>'
        for item in result.limitations
    )
    goals = ''.join(_goal_section(goal) for goal in result.goals)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>
@page{{size:A4;margin:13mm}}*{{box-sizing:border-box}}body{{font:10px/1.45 Arial,sans-serif;color:#182230;margin:0}}h1{{font-size:25px;margin:0 0 4px}}h2{{font-size:17px;margin:0 0 8px}}h3{{font-size:14px;margin:0 0 3px}}h4{{font-size:11px;margin:10px 0 5px}}p{{margin:5px 0}}.header{{padding:18px;background:#101828;color:#fff;border-radius:10px;margin-bottom:11px}}.header p{{color:#d0d5dd}}.card{{border:1px solid #d0d5dd;border-radius:9px;padding:12px;margin:9px 0}}.metrics{{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}}.metric{{background:#f2f4f7;border-radius:6px;padding:7px;min-width:90px;flex:1}}.metric span{{display:block;color:#667085;font-size:8px;text-transform:uppercase}}.metric b{{display:block;font-size:13px}}.two{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}.path{{background:#f8fafc;border-radius:7px;padding:8px;min-width:0}}table{{width:100%;border-collapse:collapse;font-size:8px;table-layout:fixed}}th,td{{border-bottom:1px solid #e4e7ec;text-align:left;padding:4px;overflow-wrap:anywhere}}th{{background:#eef2f6}}.finding{{border-left:3px solid #6172f3;background:#f8f9fc;padding:7px;margin:6px 0}}.evidence{{border-left:2px solid #98a2b3;padding-left:6px;margin-top:4px}}.counter{{border-left:2px solid #12b76a;padding-left:6px;margin-top:4px}}.warning{{border-left:3px solid #f79009;background:#fffaeb;padding:7px;margin:6px 0}}.pill{{display:inline-block;border-radius:20px;padding:1px 5px;background:#e4e7ec;font-size:8px}}.detected,.high{{background:#fee4e2;color:#912018}}.suspicious,.medium,.inconclusive{{background:#fef0c7;color:#93370d}}.not_detected,.none{{background:#d1fadf;color:#05603a}}.muted{{color:#667085}}.ok{{color:#067647}}.code{{margin-top:6px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#101828;color:#e4e7ec;padding:7px;border-radius:5px;font:7px/1.35 Consolas,monospace}}.shots{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}figure{{margin:0;break-inside:avoid-page}}.shot{{display:block;width:100%;max-height:220px;object-fit:cover;object-position:top;border:1px solid #d0d5dd;border-radius:6px}}figcaption{{font-size:7px;color:#667085;margin-top:2px}}.break-avoid{{break-inside:avoid-page}}footer{{color:#667085;margin-top:12px;border-top:1px solid #d0d5dd;padding-top:6px}}@media print{{.card{{break-inside:auto}}}}
</style></head><body>
<header class="header"><h1>FlowLens evidence report</h1><p>{_text(result.url)}<br>Run {_text(result.run_id)} · pipeline {_text(result.pipeline_version)} · generated {_text(created)}</p></header>
<section class="card"><h2>Executive summary</h2><div class="metrics">{_metric("Outcome", _title(summary.outcome))}{_metric("Confidence", _percent(summary.confidence))}{_metric("Gate", _title(summary.gate))}{_metric("Goals", summary.goals_discovered)}{_metric("Roach-motel candidates", summary.roach_motel_candidates)}{_metric("Behaviour detected", summary.behavioral_detected)}{_metric("Pages scanned", summary.pages_scanned)}{_metric("Pages failed", summary.pages_failed)}</div><p class="muted">BERT: {_title(result.model_status.bert)} · YOLO: {_title(result.model_status.yolo)}. {_text(result.model_status.note)}</p>{warnings}</section>
{_site_audit_section(result)}
{_behavior_section(result)}
{_screenshot_section(result)}
<section><h2>Paired-flow analysis</h2>{goals or '<div class="card"><p>No comparable paired flow was discovered.</p></div>'}</section>
<section class="card"><h2>Execution limitations</h2>{limitations or '<p class="ok">No run-level limitation was recorded.</p>'}</section>
<section class="card"><h2>Exploration graph</h2><div class="metrics">{_metric("States", len(result.graph.nodes))}{_metric("Transitions", len(result.graph.edges))}{_metric("Roots", len(result.graph.root_state_ids))}</div></section>
<footer>This report records bounded automated evidence. A candidate finding is not a legal conclusion; confidence gates and limitations should be considered during interpretation.</footer>
</body></html>'''


async def render_report_pdf(result: AutonomousFlowResult) -> bytes:
    """Render a self-contained report with the same bundled Chromium used by scans."""

    configure_runtime_environment()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 900})
            await page.set_content(build_report_html(result), wait_until="load")
            return await page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "10mm", "right": "10mm", "bottom": "10mm", "left": "10mm"},
                display_header_footer=True,
                header_template="<span></span>",
                footer_template='<div style="width:100%;text-align:center;font-size:8px;color:#667085">FlowLens · <span class="pageNumber"></span> / <span class="totalPages"></span></div>',
            )
        finally:
            await browser.close()

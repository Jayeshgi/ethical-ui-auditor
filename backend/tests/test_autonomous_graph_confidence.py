from __future__ import annotations

from app.flow_analysis.autonomous_schemas import (
    AutomationLimitation,
    GoalTerminalEvidence,
    GraphEdge,
    GraphNode,
    ObservedControl,
    SelectorStrategy,
)
from app.flow_analysis.confidence import build_confidence_breakdown
from app.flow_analysis.state_graph import (
    StateGraphBuilder,
    detect_dead_ends,
    detect_redirect_loops,
    normalize_url,
    shortest_path,
    state_fingerprint,
)


def _node(
    state_id: str,
    *,
    fingerprint: str | None = None,
    dialog: str = "",
    depth: int = 0,
) -> GraphNode:
    return GraphNode(
        state_id=state_id,
        fingerprint=fingerprint or state_id,
        phase="exit",
        url=f"https://Example.com/settings/{state_id}?utm_source=test&ts=1720000000",
        title="Settings",
        headings=["Account"],
        dialog_text=dialog,
        depth=depth,
    )


def _edge(
    edge_id: str,
    source: str,
    target: str | None,
    *,
    status: str = "completed",
    name: str | None = None,
) -> GraphEdge:
    return GraphEdge(
        edge_id=edge_id,
        phase="exit",
        source_state_id=source,
        target_state_id=target,
        action="click",
        accessible_name=name or edge_id,
        risk="read_only",
        status=status,
        page_transition=True,
    )


def test_url_normalization_ignores_tracking_timestamps_and_generated_ids() -> None:
    first = normalize_url(
        "HTTPS://Example.COM:443/a/550e8400-e29b-41d4-a716-446655440000/"
        "?b=2&utm_source=email&ts=1720000000&a=1#anchor"
    )
    second = normalize_url(
        "https://example.com/a/123e4567-e89b-42d3-a456-426614174000"
        "?a=1&b=2&utm_source=other&ts=1730000000"
    )

    assert first == second
    assert first == "https://example.com/a/{uuid}?a=1&b=2"


def test_state_fingerprint_is_stable_but_distinguishes_dialog_states() -> None:
    control = ObservedControl(
        control_id="generated-1",
        role="button",
        name="Delete account",
        selectors=[SelectorStrategy(kind="role", value="Delete account")],
    )
    common = {
        "title": " Account   Settings ",
        "headings": ["Profile"],
        "controls": [control],
        "phase": "exit",
    }
    first = state_fingerprint(
        "https://example.com/settings?utm_campaign=a&t=1720000000",
        dialog_text="Confirm delete request 550e8400-e29b-41d4-a716-446655440000",
        **common,
    )
    second = state_fingerprint(
        "https://EXAMPLE.com/settings/?utm_campaign=b&t=1730000000",
        dialog_text="Confirm delete request 123e4567-e89b-42d3-a456-426614174000",
        **common,
    )
    changed_dialog = state_fingerprint(
        "https://example.com/settings",
        dialog_text="Keep your account and receive 20% off",
        **common,
    )

    assert first == second
    assert changed_dialog != first


def test_builder_deduplicates_nodes_edges_and_canonicalizes_aliases() -> None:
    builder = StateGraphBuilder()
    root = builder.add_node(_node("root", fingerprint="stable-root", depth=2))
    duplicate = builder.add_node(_node("root-copy", fingerprint="stable-root", depth=1))
    target = builder.add_node(_node("target"))
    builder.add_root("root-copy")

    first = builder.add_edge(_edge("edge-1", "root-copy", target.state_id, name="Continue"))
    repeated = _edge("edge-2", "root", target.state_id, name="Continue")
    repeated.selectors = [SelectorStrategy(kind="role", value="Continue")]
    second = builder.add_edge(repeated)
    graph = builder.build()

    assert duplicate.state_id == root.state_id
    assert root.depth == 1
    assert first.edge_id == second.edge_id
    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1
    assert len(graph.edges[0].selectors) == 1
    assert graph.root_state_ids == ["root"]
    assert graph.edges[0].source_state_id == "root"


def test_graph_diagnostics_and_shortest_path_ignore_failed_blocked_detours() -> None:
    builder = StateGraphBuilder()
    for state_id in ("a", "b", "c", "d", "blocked-leaf"):
        builder.add_node(_node(state_id))
    builder.add_root("a")
    builder.add_edge(_edge("ab", "a", "b"))
    builder.add_edge(_edge("ba", "b", "a"))
    builder.add_edge(_edge("ac-failed", "a", "c", status="failed"))
    builder.add_edge(_edge("ad", "a", "d"))
    builder.add_edge(_edge("dc", "d", "c"))
    builder.add_edge(_edge("db", "d", "blocked-leaf", status="blocked"))
    graph = builder.build()

    assert detect_redirect_loops(graph) == [["a", "b", "a"]]
    assert [edge.edge_id for edge in shortest_path(graph, "a", "c")] == ["ad", "dc"]
    assert detect_dead_ends(graph, terminal_state_ids={"c"}) == []
    assert detect_dead_ends(graph) == ["c"]


def _confidence(**overrides):
    values = {
        "goal_equivalence": 1.0,
        "acquisition_terminal": 1.0,
        "exit_terminal": 1.0,
        "replay_stability": 1.0,
        "selector_stability": 1.0,
        "evidence_quality": 1.0,
    }
    values.update(overrides)
    return build_confidence_breakdown(**values)


def test_confidence_uses_schema_dimensions_and_exact_gate_thresholds() -> None:
    assert _confidence().gate == "auto_report"
    assert _confidence(
        goal_equivalence=0.85,
        acquisition_terminal=0.85,
        exit_terminal=0.85,
        replay_stability=0.85,
        selector_stability=0.85,
        evidence_quality=0.85,
    ).gate == "auto_report"
    assert _confidence(
        goal_equivalence=0.849,
        acquisition_terminal=0.849,
        exit_terminal=0.849,
        replay_stability=0.849,
        selector_stability=0.849,
        evidence_quality=0.849,
    ).gate == "report_with_caution"
    assert _confidence(
        goal_equivalence=0.649,
        acquisition_terminal=0.649,
        exit_terminal=0.649,
        replay_stability=0.649,
        selector_stability=0.649,
        evidence_quality=0.649,
    ).gate == "inconclusive"


def test_unresolved_barriers_and_unverified_terminal_cap_confidence() -> None:
    for code in ("credentials_required", "captcha_required", "mfa_required", "payment_required"):
        limitation = AutomationLimitation(code=code, phase="exit", message="blocked")
        result = _confidence(limitations=[limitation])
        assert result.overall == 0.64
        assert result.gate == "inconclusive"
        assert any(code in cap for cap in result.caps)

    unverified = _confidence(exit_terminal=GoalTerminalEvidence(confidence=1.0, verified=False))
    assert unverified.overall == 0.64
    assert unverified.gate == "inconclusive"
    assert any("exit_terminal_unverified" in cap for cap in unverified.caps)


def test_replay_attempts_can_supply_replay_stability() -> None:
    result = build_confidence_breakdown(
        goal_equivalence=1,
        acquisition_terminal=1,
        exit_terminal=1,
        selector_stability=1,
        evidence_quality=1,
        replay_attempts=2,
        replay_successes=1,
    )

    assert result.replay_stability == 0.5
    assert result.overall == 0.925
    assert result.gate == "auto_report"

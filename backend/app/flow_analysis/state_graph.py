"""Deterministic state-graph utilities for autonomous flow exploration.

The browser frequently adds values which identify a *visit* rather than a UI
state (analytics parameters, cache-busting timestamps, and generated UUIDs).
This module removes or masks those values before state identity is calculated.
Dialog text and the stable interaction surface remain part of the fingerprint,
so two modal states at the same URL are not collapsed into one node.
"""

from __future__ import annotations

from collections import deque
import hashlib
import json
import posixpath
import re
import unicodedata
from collections.abc import Iterable, Sequence
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from app.flow_analysis.autonomous_schemas import GraphEdge, GraphNode, ObservedControl, StateGraph


_TRACKING_KEYS = {
    "_ga",
    "_gl",
    "campaign",
    "campaignid",
    "dclid",
    "fbclid",
    "gbraid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "referrer",
    "s_cid",
    "vero_conv",
    "vero_id",
    "wbraid",
}
_TRACKING_PREFIXES = ("utm_", "pk_", "matomo_", "mtm_")
_VOLATILE_QUERY_KEYS = {
    "_",
    "cache_bust",
    "cachebuster",
    "cb",
    "expires",
    "request_time",
    "request_timestamp",
    "t",
    "time",
    "timestamp",
    "ts",
}

_UUID_RE = re.compile(
    r"(?i)(?<![0-9a-f])(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32})(?![0-9a-f])"
)
_ISO_TIMESTAMP_RE = re.compile(
    r"(?i)\b\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:z|[+-]\d{2}:?\d{2})?\b"
)
_EPOCH_TIMESTAMP_RE = re.compile(r"(?<!\d)(?:1[0-9]{9}|[1-9][0-9]{12})(?!\d)")
_WHITESPACE_RE = re.compile(r"\s+")


def _mask_volatile_tokens(value: str) -> str:
    """Mask generated values without erasing the surrounding semantic text."""

    value = _UUID_RE.sub("{uuid}", value)
    value = _ISO_TIMESTAMP_RE.sub("{timestamp}", value)
    return _EPOCH_TIMESTAMP_RE.sub("{timestamp}", value)


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    normalized = _mask_volatile_tokens(normalized)
    return _WHITESPACE_RE.sub(" ", normalized).strip().casefold()


def _is_tracking_key(key: str) -> bool:
    lowered = key.casefold()
    return lowered in _TRACKING_KEYS or lowered.startswith(_TRACKING_PREFIXES)


def _is_volatile_query_key(key: str) -> bool:
    lowered = key.casefold()
    return (
        lowered in _VOLATILE_QUERY_KEYS
        or lowered.endswith("_timestamp")
        or lowered.endswith("_ts")
        or lowered.startswith("cache_bust")
    )


def _normalize_path(path: str) -> str:
    decoded = unquote(path or "/")
    decoded = re.sub(r"/{2,}", "/", decoded)
    normalized = posixpath.normpath(decoded)
    if decoded.startswith("/") and not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if normalized in {"", "."}:
        normalized = "/"
    normalized = _mask_volatile_tokens(normalized)
    if normalized != "/":
        normalized = normalized.rstrip("/")
    # Keep placeholders readable. All other unsafe characters remain encoded.
    return quote(normalized, safe="/%:@!$&'()*+,;=-._~{}")


def normalize_url(url: str) -> str:
    """Return a canonical URL suitable for comparing observed browser states.

    The function deliberately drops fragments: ordinary anchors do not change
    the fetched document, while SPA/modal differences are represented by the
    title, headings, controls, and dialog text in :func:`state_fingerprint`.
    """

    raw = str(url).strip()
    if not raw:
        return ""

    parts = urlsplit(raw)
    scheme = parts.scheme.casefold()
    hostname = (parts.hostname or "").casefold()
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        pass

    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    try:
        port = parts.port
    except ValueError:
        # Preserve malformed authority text rather than making normalization
        # unexpectedly fatal during evidence collection.
        port = None
        hostname = parts.netloc.casefold()
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        hostname = f"{hostname}:{port}"

    query: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if _is_tracking_key(key) or _is_volatile_query_key(key):
            continue
        query.append((key, _mask_volatile_tokens(value)))
    query.sort(key=lambda item: (item[0].casefold(), item[0], item[1]))

    return urlunsplit(
        (
            scheme,
            hostname,
            _normalize_path(parts.path),
            urlencode(query, doseq=True, safe="{}"),
            "",
        )
    )


def _control_signature(control: ObservedControl) -> tuple[str, ...]:
    return (
        _normalize_text(control.role),
        _normalize_text(control.name),
        normalize_url(control.href) if control.href else "",
        _normalize_text(control.input_type),
        _normalize_text(control.form_method),
        "required" if control.required else "optional",
        "disabled" if control.disabled else "enabled",
    )


def state_fingerprint(
    url: str | GraphNode,
    title: str = "",
    headings: Sequence[str] | None = None,
    dialog_text: str = "",
    authentication_state: str = "unknown",
    phase: str | None = None,
    controls: Sequence[ObservedControl] | None = None,
) -> str:
    """Calculate a stable SHA-256 fingerprint for an observable UI state.

    A :class:`GraphNode` can be supplied directly, or its relevant state fields
    can be passed separately. Traversal depth, screenshots, and presentation
    measurements are intentionally excluded because they describe an
    observation of a state rather than the state itself.
    """

    if isinstance(url, GraphNode):
        node = url
        url = node.url
        title = node.title
        headings = node.headings
        dialog_text = node.dialog_text
        authentication_state = node.authentication_state
        phase = node.phase
        controls = node.controls

    heading_values = sorted({_normalize_text(value) for value in headings or () if _normalize_text(value)})
    control_values = sorted({_control_signature(control) for control in controls or ()})
    payload = {
        "authentication_state": authentication_state,
        "controls": control_values,
        "dialog_text": _normalize_text(dialog_text),
        "headings": heading_values,
        "phase": phase or "",
        "title": _normalize_text(title),
        "url": normalize_url(str(url)),
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class StateGraphBuilder:
    """In-memory graph accumulator with stable node and edge deduplication."""

    def __init__(self, graph: StateGraph | None = None) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._fingerprints: dict[str, str] = {}
        self._node_aliases: dict[str, str] = {}
        self._edges: dict[str, GraphEdge] = {}
        self._edge_keys: dict[tuple[object, ...], str] = {}
        self._roots: list[str] = []
        if graph is not None:
            for node in graph.nodes:
                self.add_node(node)
            for root in graph.root_state_ids:
                self.add_root(root)
            for edge in graph.edges:
                self.add_edge(edge)

    def _canonical_state_id(self, state_id: str) -> str:
        seen: set[str] = set()
        while state_id in self._node_aliases and state_id not in seen:
            seen.add(state_id)
            state_id = self._node_aliases[state_id]
        return state_id

    @staticmethod
    def _merge_node(existing: GraphNode, incoming: GraphNode) -> None:
        existing.depth = min(existing.depth, incoming.depth)
        existing.headings = list(dict.fromkeys([*existing.headings, *incoming.headings]))
        existing.limitation_codes = list(
            dict.fromkeys([*existing.limitation_codes, *incoming.limitation_codes])
        )
        controls = {control.control_id: control for control in existing.controls}
        for control in incoming.controls:
            controls.setdefault(control.control_id, control)
        existing.controls = list(controls.values())
        if existing.screenshot_path is None:
            existing.screenshot_path = incoming.screenshot_path
        if existing.authentication_state == "unknown" and incoming.authentication_state != "unknown":
            existing.authentication_state = incoming.authentication_state

    def add_node(self, node: GraphNode) -> GraphNode:
        """Add a node and return the canonical stored node.

        When a fingerprint was already observed, the incoming state id becomes
        an alias for the first node. Supplementary evidence is merged without
        duplicating the state.
        """

        candidate = node.model_copy(deep=True)
        candidate.fingerprint = candidate.fingerprint.strip() or state_fingerprint(candidate)
        existing_by_id = self._nodes.get(candidate.state_id)
        if existing_by_id is not None:
            if existing_by_id.fingerprint != candidate.fingerprint:
                raise ValueError(f"State id {candidate.state_id!r} was reused for a different fingerprint")
            self._merge_node(existing_by_id, candidate)
            return existing_by_id

        canonical_id = self._fingerprints.get(candidate.fingerprint)
        if canonical_id is not None:
            existing = self._nodes[canonical_id]
            self._node_aliases[candidate.state_id] = canonical_id
            self._merge_node(existing, candidate)
            return existing

        self._nodes[candidate.state_id] = candidate
        self._fingerprints[candidate.fingerprint] = candidate.state_id
        return candidate

    @staticmethod
    def _edge_key(edge: GraphEdge) -> tuple[object, ...]:
        return (
            edge.phase,
            edge.source_state_id,
            edge.target_state_id,
            _normalize_text(edge.action),
            _normalize_text(edge.accessible_name),
            edge.risk,
            edge.status,
            edge.page_transition,
        )

    @staticmethod
    def _merge_edge(existing: GraphEdge, incoming: GraphEdge) -> None:
        existing.evidence_tags = list(dict.fromkeys([*existing.evidence_tags, *incoming.evidence_tags]))
        selector_keys = {
            (
                selector.kind,
                selector.value,
                selector.role,
                selector.accessible_name,
            )
            for selector in existing.selectors
        }
        for selector in incoming.selectors:
            key = (selector.kind, selector.value, selector.role, selector.accessible_name)
            if key not in selector_keys:
                existing.selectors.append(selector)
                selector_keys.add(key)
        if existing.error is None:
            existing.error = incoming.error
        if incoming.duration_ms and (not existing.duration_ms or incoming.duration_ms < existing.duration_ms):
            existing.duration_ms = incoming.duration_ms

    def add_edge(self, edge: GraphEdge) -> GraphEdge:
        """Add an edge and return the canonical stored transition."""

        candidate = edge.model_copy(deep=True)
        candidate.source_state_id = self._canonical_state_id(candidate.source_state_id)
        if candidate.target_state_id is not None:
            candidate.target_state_id = self._canonical_state_id(candidate.target_state_id)

        if candidate.source_state_id not in self._nodes:
            raise ValueError(f"Unknown source state {candidate.source_state_id!r}")
        if candidate.target_state_id is not None and candidate.target_state_id not in self._nodes:
            raise ValueError(f"Unknown target state {candidate.target_state_id!r}")

        existing_by_id = self._edges.get(candidate.edge_id)
        key = self._edge_key(candidate)
        if existing_by_id is not None:
            if self._edge_key(existing_by_id) != key:
                raise ValueError(f"Edge id {candidate.edge_id!r} was reused for a different transition")
            self._merge_edge(existing_by_id, candidate)
            return existing_by_id

        canonical_edge_id = self._edge_keys.get(key)
        if canonical_edge_id is not None:
            existing = self._edges[canonical_edge_id]
            self._merge_edge(existing, candidate)
            return existing

        self._edges[candidate.edge_id] = candidate
        self._edge_keys[key] = candidate.edge_id
        return candidate

    def add_root(self, state_id: str) -> str:
        canonical_id = self._canonical_state_id(state_id)
        if canonical_id not in self._nodes:
            raise ValueError(f"Unknown root state {state_id!r}")
        if canonical_id not in self._roots:
            self._roots.append(canonical_id)
        return canonical_id

    def build(self) -> StateGraph:
        return StateGraph(
            nodes=[node.model_copy(deep=True) for node in self._nodes.values()],
            edges=[edge.model_copy(deep=True) for edge in self._edges.values()],
            root_state_ids=list(self._roots),
        )

    def detect_redirect_loops(self, phase: str | None = None) -> list[list[str]]:
        return detect_redirect_loops(self.build(), phase=phase)

    def detect_dead_ends(
        self,
        phase: str | None = None,
        terminal_state_ids: Iterable[str] = (),
    ) -> list[str]:
        return detect_dead_ends(self.build(), phase=phase, terminal_state_ids=terminal_state_ids)

    def shortest_path(
        self,
        source_state_id: str,
        target_state_id: str | Iterable[str],
        phase: str | None = None,
    ) -> list[GraphEdge]:
        return shortest_path(self.build(), source_state_id, target_state_id, phase=phase)


def _completed_adjacency(graph: StateGraph, phase: str | None = None) -> dict[str, list[GraphEdge]]:
    adjacency: dict[str, list[GraphEdge]] = {node.state_id: [] for node in graph.nodes}
    for edge in graph.edges:
        if edge.status != "completed" or edge.target_state_id is None:
            continue
        if phase is not None and edge.phase != phase:
            continue
        adjacency.setdefault(edge.source_state_id, []).append(edge)
    for edges in adjacency.values():
        edges.sort(key=lambda edge: (edge.target_state_id or "", edge.edge_id))
    return adjacency


def shortest_path(
    graph: StateGraph,
    source_state_id: str,
    target_state_id: str | Iterable[str],
    phase: str | None = None,
) -> list[GraphEdge]:
    """Return the fewest completed transitions between states.

    Failed, blocked, and unexplored frontier transitions are never considered;
    they cannot make an observed journey appear shorter than it really was.
    An empty list means either the source already is a target or no completed
    route exists.
    """

    targets = {target_state_id} if isinstance(target_state_id, str) else set(target_state_id)
    if source_state_id in targets:
        return []
    node_ids = {node.state_id for node in graph.nodes}
    if source_state_id not in node_ids or not targets.intersection(node_ids):
        return []

    adjacency = _completed_adjacency(graph, phase)
    queue: deque[str] = deque([source_state_id])
    visited = {source_state_id}
    previous: dict[str, tuple[str, GraphEdge]] = {}
    reached: str | None = None
    while queue:
        current = queue.popleft()
        for edge in adjacency.get(current, []):
            target = edge.target_state_id
            if target is None or target in visited:
                continue
            visited.add(target)
            previous[target] = (current, edge)
            if target in targets:
                reached = target
                queue.clear()
                break
            queue.append(target)

    if reached is None:
        return []
    path: list[GraphEdge] = []
    cursor = reached
    while cursor != source_state_id:
        predecessor, edge = previous[cursor]
        path.append(edge.model_copy(deep=True))
        cursor = predecessor
    path.reverse()
    return path


def shortest_state_path(
    graph: StateGraph,
    source_state_id: str,
    target_state_id: str | Iterable[str],
    phase: str | None = None,
) -> list[str]:
    """State-id companion to :func:`shortest_path`."""

    targets = {target_state_id} if isinstance(target_state_id, str) else set(target_state_id)
    if source_state_id in targets:
        return [source_state_id]
    edges = shortest_path(graph, source_state_id, targets, phase=phase)
    if not edges:
        return []
    return [source_state_id, *(edge.target_state_id for edge in edges if edge.target_state_id is not None)]


def detect_redirect_loops(graph: StateGraph, phase: str | None = None) -> list[list[str]]:
    """Return deterministic closed cycles made only of completed transitions."""

    adjacency = {
        node_id: [edge.target_state_id for edge in edges if edge.target_state_id is not None]
        for node_id, edges in _completed_adjacency(graph, phase).items()
    }
    cycles: set[tuple[str, ...]] = set()
    for start in sorted(adjacency):
        path = [start]
        in_path = {start}

        def visit(current: str) -> None:
            for target in adjacency.get(current, []):
                # Every cycle is emitted from its lexicographically smallest
                # state, preventing rotations of the same directed cycle.
                if target < start:
                    continue
                if target == start:
                    cycles.add(tuple([*path, start]))
                    continue
                if target in in_path:
                    continue
                in_path.add(target)
                path.append(target)
                visit(target)
                path.pop()
                in_path.remove(target)

        visit(start)
    return [list(cycle) for cycle in sorted(cycles, key=lambda cycle: (len(cycle), cycle))]


def detect_dead_ends(
    graph: StateGraph,
    phase: str | None = None,
    terminal_state_ids: Iterable[str] = (),
    *,
    include_unreachable: bool = False,
) -> list[str]:
    """Find explored states with no successful or still-open way forward.

    Known goal terminals can be excluded explicitly. A state whose only
    outgoing transitions failed or were blocked is a dead end; a state with a
    frontier transition remains explorable and is therefore not one.
    """

    terminals = set(terminal_state_ids)
    nodes = {node.state_id: node for node in graph.nodes if phase is None or node.phase == phase}
    outgoing: dict[str, list[GraphEdge]] = {state_id: [] for state_id in nodes}
    for edge in graph.edges:
        if phase is not None and edge.phase != phase:
            continue
        if edge.source_state_id in outgoing:
            outgoing[edge.source_state_id].append(edge)

    if include_unreachable or not graph.root_state_ids:
        considered = set(nodes)
    else:
        considered: set[str] = set()
        queue: deque[str] = deque(root for root in graph.root_state_ids if root in nodes)
        while queue:
            state_id = queue.popleft()
            if state_id in considered:
                continue
            considered.add(state_id)
            for edge in outgoing.get(state_id, []):
                if edge.status == "completed" and edge.target_state_id in nodes:
                    queue.append(edge.target_state_id)

    dead_ends: list[str] = []
    for state_id in sorted(considered):
        if state_id in terminals:
            continue
        viable = any(
            edge.status == "frontier"
            or (edge.status == "completed" and edge.target_state_id is not None)
            for edge in outgoing.get(state_id, [])
        )
        if not viable:
            dead_ends.append(state_id)
    return dead_ends


__all__ = [
    "StateGraphBuilder",
    "detect_dead_ends",
    "detect_redirect_loops",
    "normalize_url",
    "shortest_path",
    "shortest_state_path",
    "state_fingerprint",
]

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import unquote, urlsplit

from app.flow_analysis.autonomous_schemas import ObservedControl, RiskLevel
from app.flow_analysis.schemas import FlowMode


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_CONTROLLED_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"})

_DESTRUCTIVE = re.compile(
    r"\b(?:"
    r"delete(?:\s+(?:my\s+)?(?:account|profile|data|payment\s+method|card|subscription))?"
    r"|erase(?:\s+(?:my\s+)?(?:account|profile|data))?"
    r"|remove(?:\s+(?:my\s+)?(?:account|profile|payment\s+method|card|integration|data))?"
    r"|unsubscribe|deactivate|disconnect|revoke(?:\s+(?:access|consent|permission))?"
    r"|terminate(?:\s+(?:account|membership|subscription|plan|service))?"
    r"|close\s+(?:my\s+)?(?:account|profile|membership)"
    r"|cancel\s+(?:my\s+)?(?:account|membership|subscription|plan|trial|service|order|booking)"
    r"|withdraw\s+(?:my\s+)?(?:consent|permission)"
    r"|opt[\s-]*out|leave\s+(?:the\s+)?(?:program|programme|membership)"
    r")\b",
    re.IGNORECASE,
)
_FINANCIAL = re.compile(
    r"\b(?:"
    r"buy\s+now|purchase|pay(?:\s+(?:now|today|\$|€|£))?|place\s+(?:the\s+)?order"
    r"|complete\s+(?:the\s+)?(?:order|purchase|payment)|confirm\s+(?:the\s+)?(?:order|purchase|payment)"
    r"|checkout|donate|make\s+(?:a\s+)?payment|start\s+(?:a\s+)?(?:free\s+|paid\s+)?trial"
    r"|request\s+(?:a\s+)?refund"
    r"|subscribe\s+(?:now|to|for)|upgrade\s+(?:my\s+)?(?:plan|subscription|account)"
    r"|add\s+(?:a\s+)?(?:payment\s+method|credit\s+card|debit\s+card)"
    r")\b",
    re.IGNORECASE,
)
_AUTHENTICATION = re.compile(
    r"\b(?:log[\s-]*in|sign[\s-]*in|authenticate|authentication|verify\s+identity"
    r"|continue\s+with\s+(?:google|microsoft|apple|facebook|github|sso|okta)"
    r"|password|passcode|one[\s-]*time\s+(?:password|code)|mfa|2fa)\b",
    re.IGNORECASE,
)
_MUTATING = re.compile(
    r"\b(?:"
    r"sign[\s-]*up|register|create\s+(?:an?\s+)?(?:account|profile)"
    r"|submit|save|update|change|confirm|apply|accept|agree|consent|allow"
    r"|reject(?:\s+all)?|decline|deny|necessary\s+only|subscribe|disable|turn\s+off"
    r"|(?:start|initiate|request)\s+(?:a\s+)?return|return\s+(?:item|order|purchase)|get\s+(?:a\s+)?refund"
    r"|enable|join|connect|link\s+(?:account|integration)|add|send|upload|publish|post|share|follow"
    r"|book|reserve|enrol|enroll|activate|log[\s-]*out|sign[\s-]*out"
    r")\b",
    re.IGNORECASE,
)
_READ_ONLY = re.compile(
    r"\b(?:view|read|learn|how\s+to|details?|more\s+information|help|support|documentation"
    r"|privacy|terms|about|faq|search|find|browse|home|back|previous)\b",
    re.IGNORECASE,
)
_REVERSIBLE = re.compile(
    r"\b(?:open|close|dismiss|expand|collapse|show|hide|menu|filter|sort"
    r"|next|continue|select|choose|tab|retry|refresh|reset|cancel)\b",
    re.IGNORECASE,
)

_TEXT_INPUT_TYPES = frozenset(
    {
        "text",
        "email",
        "tel",
        "url",
        "number",
        "date",
        "datetime-local",
        "month",
        "week",
        "time",
        "search",
        "checkbox",
        "radio",
        "range",
        "color",
    }
)


@dataclass(frozen=True, slots=True)
class ActionPolicyDecision:
    """A deterministic safety decision, with a reason suitable for an audit log."""

    allowed: bool
    reason: str
    risk: RiskLevel

    def __bool__(self) -> bool:
        return self.allowed

    def __iter__(self):
        # Retain convenient ``allowed, reason = action_allowed(...)`` usage.
        yield self.allowed
        yield self.reason


def _field(control: ObservedControl | Mapping[str, Any] | object, name: str) -> str:
    if isinstance(control, Mapping):
        value = control.get(name)
    else:
        value = getattr(control, name, None)
    return "" if value is None else str(value).strip()


def _semantic_text(control: ObservedControl | Mapping[str, Any] | object) -> str:
    href = unquote(_field(control, "href"))
    try:
        parsed = urlsplit(href)
        if parsed.scheme.lower() in {"http", "https"}:
            href = " ".join((parsed.path, parsed.query, parsed.fragment))
    except ValueError:
        pass
    parts = (
        _field(control, "role"),
        _field(control, "name"),
        href,
    )
    return re.sub(r"[_/\-?#=&:.]+", " ", " ".join(part for part in parts if part))


def _submits_form(control: ObservedControl | Mapping[str, Any] | object) -> bool:
    input_type = _field(control, "input_type").lower()
    role = _field(control, "role").lower()
    method_was_observed = bool(_field(control, "form_method"))
    return input_type in {"submit", "image"} or (
        role == "button" and not input_type and method_was_observed
    )


def classify_action_risk(control: ObservedControl | Mapping[str, Any] | object) -> RiskLevel:
    """Classify an observed control without executing it.

    The ordering is intentionally conservative: explicit destructive and payment
    semantics override element roles, while a non-GET form is at least mutating.
    Filling an ordinary field is reversible until its form is submitted.
    """

    role = _field(control, "role").lower()
    name = _field(control, "name")
    href = _field(control, "href")
    input_type = _field(control, "input_type").lower()
    method = (_field(control, "form_method") or "GET").upper()
    semantic = _semantic_text(control)

    # Help articles often mention a dangerous action without performing it.
    # Require both an informational label and an informational destination so a
    # deceptively named mutation endpoint cannot gain read-only status.
    if role in {"link", "navigation"} and href and _READ_ONLY.search(name):
        try:
            informational_path = urlsplit(href).path
        except ValueError:
            informational_path = ""
        if re.search(r"/(?:help|support|docs?|documentation|articles?|faq|polic(?:y|ies))(?:/|$)", informational_path, re.I):
            return "read_only"

    if _DESTRUCTIVE.search(semantic):
        return "destructive"
    if _FINANCIAL.search(semantic) or input_type in {"credit-card", "payment"}:
        return "financial"
    if _AUTHENTICATION.search(semantic) or input_type == "password":
        return "authentication"
    if input_type == "search" or (
        input_type in {"submit", "button"} and method in _SAFE_METHODS and re.search(r"\b(?:search|find)\b", name, re.I)
    ):
        return "read_only"
    if _MUTATING.search(semantic):
        return "mutating"

    if input_type == "file":
        return "mutating"
    if input_type in {"submit", "button"} and _READ_ONLY.search(name):
        return "read_only"
    if input_type in _TEXT_INPUT_TYPES:
        return "reversible"
    if input_type in {"reset", "button"}:
        return "reversible"
    if input_type in {"submit", "image"}:
        # A semantically neutral GET form is observational; action words such as
        # delete, save, or sign in have already been classified above.
        return "read_only" if method in _SAFE_METHODS else "mutating"

    # HTML forms default to GET. An explicitly unsafe method raises a submit
    # control's classification floor, but does not make merely filling a field
    # mutating.
    if _submits_form(control) and method not in _SAFE_METHODS:
        return "mutating"

    parsed = urlsplit(href) if href else None
    if parsed and parsed.scheme.lower() in {"mailto", "tel", "sms", "intent", "market"}:
        return "mutating"
    if parsed and parsed.scheme.lower() == "javascript":
        return "mutating"

    if role in {"link", "navigation"} and href:
        return "read_only"
    if _READ_ONLY.search(semantic):
        return "read_only"
    if role in {"textbox", "searchbox", "combobox", "checkbox", "radio", "slider", "spinbutton"}:
        return "reversible"
    if role in {"tab", "menuitem", "option", "switch", "button"} or _REVERSIBLE.search(semantic):
        return "reversible"

    # Unknown actionable controls are not assumed safe in evidence-only mode.
    return "mutating"


def request_method_allowed(method: str | None, mode: FlowMode, is_login: bool = False) -> bool:
    """Guard a prospective browser request by method and execution mode.

    An absent HTML form method means GET. Evidence-only exploration permits the
    safe methods and a narrowly-scoped POST login exception; controlled mode may
    use ordinary HTTP methods after its separate origin allow-list check.
    """

    normalized = (method or "GET").strip().upper()
    if mode == "controlled":
        return normalized in _CONTROLLED_METHODS
    if mode != "evidence_only":
        return False
    if normalized in _SAFE_METHODS:
        return True
    return bool(is_login and normalized == "POST")


def _normalized_origin(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = urlsplit(value.strip())
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
    except (TypeError, ValueError):
        return ""
    if scheme not in {"http", "https"} or not hostname:
        return ""
    host = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    return f"{scheme}://{host}"


def _approved_origins(values: Iterable[str] | None) -> set[str]:
    return {origin for value in (values or ()) if (origin := _normalized_origin(value))}


def action_allowed(
    control: ObservedControl | Mapping[str, Any] | object,
    mode: FlowMode,
    origin: str,
    approved_controlled_origins: Iterable[str] | None = None,
) -> ActionPolicyDecision:
    """Return whether the control may be executed under the autonomous policy."""

    risk = classify_action_risk(control)
    method = (_field(control, "form_method") or "GET").upper()

    if mode == "controlled":
        approved = _approved_origins(approved_controlled_origins)
        current_origin = _normalized_origin(origin)
        if not current_origin or current_origin not in approved:
            return ActionPolicyDecision(
                allowed=False,
                reason="Controlled execution is restricted to an explicitly approved origin.",
                risk=risk,
            )

        href = _field(control, "href")
        if href:
            parsed_href = urlsplit(href)
            if parsed_href.scheme.lower() in {"http", "https"}:
                destination = _normalized_origin(href)
                if not destination or destination not in approved:
                    return ActionPolicyDecision(
                        allowed=False,
                        reason="The control targets an origin that is not approved for controlled execution.",
                        risk=risk,
                    )
            elif parsed_href.scheme and parsed_href.scheme.lower() not in {"javascript"}:
                return ActionPolicyDecision(
                    allowed=False,
                    reason="Controlled browser execution does not launch external protocols or native applications.",
                    risk=risk,
                )

        if _submits_form(control) and not request_method_allowed(
            method, mode, is_login=risk == "authentication"
        ):
            return ActionPolicyDecision(False, "The request method is not supported by controlled execution.", risk)
        return ActionPolicyDecision(True, "The action is on an explicitly approved controlled origin.", risk)

    if mode != "evidence_only":
        return ActionPolicyDecision(False, "Unknown execution mode; the action was denied safely.", risk)

    if risk in {"mutating", "financial", "destructive"}:
        return ActionPolicyDecision(
            False,
            f"Evidence-only execution stops before {risk} actions.",
            risk,
        )
    if _submits_form(control) and not request_method_allowed(
        method, mode, is_login=risk == "authentication"
    ):
        return ActionPolicyDecision(
            False,
            "Evidence-only execution blocks non-GET form submissions except an explicit POST login.",
            risk,
        )
    return ActionPolicyDecision(
        True,
        f"Evidence-only execution permits this {risk.replace('_', '-')} action.",
        risk,
    )


def is_action_allowed(
    control: ObservedControl | Mapping[str, Any] | object,
    mode: FlowMode,
    origin: str,
    approved_controlled_origins: Iterable[str] | None = None,
) -> bool:
    """Boolean convenience wrapper around :func:`action_allowed`."""

    return action_allowed(control, mode, origin, approved_controlled_origins).allowed


classify_control_risk = classify_action_risk
decide_action = action_allowed


__all__ = [
    "ActionPolicyDecision",
    "action_allowed",
    "classify_action_risk",
    "classify_control_risk",
    "decide_action",
    "is_action_allowed",
    "request_method_allowed",
]

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from html import unescape
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.flow_analysis.autonomous_schemas import AutomationLimitation, GraphPhase, LimitationCode


@dataclass(frozen=True, slots=True)
class PageObservation:
    """Serializable page facts consumed by the limitation detector."""

    text: str = ""
    html: str = ""
    url: str = ""
    status_code: int | None = None


# A limitation is operational evidence, not a dark-pattern classification. Only
# channel switching is eligible for later, separate paired-flow mechanism scoring.
MECHANISM_ELIGIBLE_LIMITATIONS = frozenset({"channel_switch"})

_SCRIPT_BLOCKS = re.compile(
    r"<(?:script|style|noscript|svg)\b[^>]*>.*?</(?:script|style|noscript|svg)>",
    re.IGNORECASE | re.DOTALL,
)
_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\s().-]?){9,15}(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")

_CAPTCHA_TEXT = (
    r"\b(?:please\s+)?(?:complete|solve|enter)\s+(?:the\s+)?captcha\b",
    r"\bverify\s+(?:that\s+)?you(?:'re|\s+are)\s+(?:a\s+)?human\b",
    r"\bi\s+am\s+not\s+a\s+robot\b",
    r"\bcomplete\s+(?:the\s+)?security\s+challenge\b",
)
_CAPTCHA_HTML = (
    r"class\s*=\s*[\"'][^\"']*\b(?:g-recaptcha|h-captcha|cf-turnstile)\b",
    r"<iframe\b[^>]+(?:recaptcha|hcaptcha)[^>]*>",
    r"<(?:div|input)\b[^>]+data-sitekey\s*=",
)
_EMAIL_TEXT = (
    r"\b(?:verify|confirm)\s+(?:your\s+)?e-?mail(?:\s+address)?\b",
    r"\be-?mail\s+verification\s+(?:is\s+)?required\b",
    r"\bcheck\s+(?:your\s+)?(?:e-?mail|inbox)(?:\s+to\s+(?:verify|confirm|continue))?\b",
    r"\b(?:verification\s+)?(?:link|code)\s+(?:was\s+|has\s+been\s+)?sent\s+to\s+(?:your\s+)?e-?mail\b",
)
_MFA_TEXT = (
    r"\b(?:two|multi)[\s-]*factor\s+authentication\b",
    r"\b(?:mfa|2fa)\s+(?:is\s+)?required\b",
    r"\benter\s+(?:the\s+)?(?:authentication|authenticator|security|one[\s-]*time)\s+code\b",
    r"\bcode\s+(?:was\s+|has\s+been\s+)?sent\s+to\s+(?:your\s+)?(?:phone|mobile|device)\b",
    r"\b(?:sms|text\s+message)\s+(?:verification\s+)?code\b",
    r"\bapprove\s+(?:the\s+)?(?:sign[\s-]*in|login)\s+(?:on|from)\s+(?:your\s+)?(?:phone|device)\b",
)
_AUTH_FAILURE_TEXT = (
    r"\b(?:invalid|incorrect)\s+(?:username|e-?mail|password|credentials)(?:\s+or\s+(?:username|e-?mail|password))?\b",
    r"\bauthentication\s+failed\b",
    r"\bunable\s+to\s+(?:log|sign)[\s-]*in\b",
    r"\baccount\s+(?:is\s+)?(?:temporarily\s+)?locked\b",
)
_CREDENTIAL_TEXT = (
    r"\b(?:login|log[\s-]*in|sign[\s-]*in|authentication)\s+(?:is\s+)?required\b",
    r"\b(?:please|you\s+must)\s+(?:log|sign)[\s-]*in\s+(?:to\s+continue|first|before)\b",
    r"\b(?:log|sign)[\s-]*in\s+to\s+(?:continue|access|manage|view|proceed)\b",
    r"\bsession\s+(?:has\s+)?expired.{0,40}\b(?:log|sign)[\s-]*in\b",
    r"\benter\s+(?:your\s+)?(?:username|e-?mail).{0,50}\bpassword\b",
)
_CREDENTIAL_HTML = (
    r"<form\b[^>]+action\s*=\s*[\"'][^\"']*(?:log[\s_-]*in|sign[\s_-]*in|session)[^\"']*[\"'][^>]*>.*?<input\b[^>]+type\s*=\s*[\"']password[\"']",
    r"<input\b(?=[^>]*type\s*=\s*[\"']password[\"'])(?=[^>]*autocomplete\s*=\s*[\"']current-password[\"'])[^>]*>",
)
_PAYMENT_TEXT = (
    r"\bpayment\s+(?:is\s+)?required\b",
    r"\b(?:credit|debit)\s+card\s+(?:is\s+)?required\b",
    r"\b(?:enter|provide|confirm)\s+(?:your\s+)?(?:card|payment|billing)\s+(?:details|information)\b",
    r"\badd\s+(?:a\s+)?payment\s+method\s+to\s+continue\b",
    r"\bcomplete\s+(?:your|the)\s+(?:purchase|payment)\s+to\s+continue\b",
)
_PAYMENT_HTML = (
    r"<(?:input|iframe)\b[^>]+(?:autocomplete\s*=\s*[\"']cc-(?:number|exp|csc)|name\s*=\s*[\"'](?:cardnumber|card_number|cc-number)|stripe-card-element)",
    r"<[^>]+(?:data-elements-stable-field-name|data-payment-element)[^>]*>",
)
_EXTERNAL_IDP_TEXT = (
    r"\b(?:continue|log[\s-]*in|sign[\s-]*in)\s+with\s+(?:google|microsoft|apple|facebook|github|okta|sso)\b",
    r"\buse\s+(?:your\s+)?(?:company|organisation|organization)\s+(?:login|single\s+sign[\s-]*on|sso)\b",
)
_EXTERNAL_IDP_HTML = (
    r"<(?:a|form)\b[^>]+(?:href|action)\s*=\s*[\"'][^\"']*(?:oauth2?|openid|saml|sso)/(?:authorize|login|signin)",
)
_BOT_TEXT = (
    r"\bchecking\s+(?:your\s+)?browser\s+before\s+(?:accessing|continuing)\b",
    r"\bunusual\s+traffic\s+from\s+(?:your\s+)?(?:computer|network)\b",
    r"\bautomated\s+(?:access|requests|traffic)\s+(?:has\s+been\s+)?detected\b",
    r"\baccess\s+denied.{0,80}\b(?:cloudflare|akamai|imperva|perimeterx|bot)\b",
    r"\bbot\s+(?:protection|detection)\s+(?:challenge|triggered|enabled)\b",
)
_BOT_HTML = (
    r"(?:cdn-cgi/challenge-platform|cf-chl-|px-captcha|perimeterx|akamai-bot)",
)
_RATE_TEXT = (
    r"\btoo\s+many\s+requests\b",
    r"\brate\s+limit(?:ed|\s+(?:was\s+)?exceeded|\s+reached)\b",
    r"\brequest\s+(?:rate|limit)\s+(?:was\s+)?exceeded\b",
    r"\bhttp\s*429\b",
    r"\btemporarily\s+blocked\s+(?:because|due\s+to)\s+(?:of\s+)?(?:too\s+many|repeated)\s+requests\b",
)
_CHANNEL_TEXT = (
    r"\b(?:cancel|delete|close|unsubscribe|opt[\s-]*out|leave|disconnect|return)\b.{0,90}\b(?:call|phone|e-?mail|live\s+chat|visit\s+(?:a|our|the)\s+(?:store|branch|office))\b",
    r"\b(?:call|phone|e-?mail|live\s+chat|visit\s+(?:a|our|the)\s+(?:store|branch|office))\b.{0,90}\b(?:to|for)\s+(?:cancel|delete|close|unsubscribe|opt[\s-]*out|leave|disconnect|return)\b",
    r"\b(?:must|required\s+to|can\s+only)\s+(?:call|phone|e-?mail|contact\s+(?:support|an?\s+agent)|visit\s+(?:a|our|the)\s+(?:store|branch|office))\b",
    r"\b(?:cancellation|account\s+closure|deletion|unsubscribe)\s+(?:is\s+)?(?:only\s+)?(?:available|possible|handled)\s+(?:by|over|through)\s+(?:phone|e-?mail|live\s+chat)\b",
)
_NATIVE_APP_TEXT = (
    r"\b(?:must|required\s+to|can\s+only)\s+(?:use|open|continue\s+in)\s+(?:the|our|this)\s+(?:mobile\s+)?app\b",
    r"\b(?:open|continue)\s+in\s+(?:the|our|this)\s+app\s+to\s+(?:continue|proceed|complete|manage)\b",
    r"\bscan\s+(?:this\s+)?qr\s+code\s+with\s+(?:the|our|your)\s+app\b",
    r"\b(?:this\s+)?(?:action|feature|setting)\s+is\s+only\s+available\s+in\s+(?:the|our|this)\s+(?:mobile\s+)?app\b",
)
_NATIVE_APP_HTML = (
    r"(?:href\s*=\s*[\"'](?:intent|market|itms-apps|android-app)://|data-deep-?link\s*=)",
)


def _value(source: object, *names: str) -> Any:
    if isinstance(source, Mapping):
        for name in names:
            if name in source:
                return source[name]
        return None
    for name in names:
        if hasattr(source, name):
            return getattr(source, name)
    return None


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set, frozenset)):
        return "\n".join(_as_text(item) for item in value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _coerce_observation(text: object, html: str, url: str) -> PageObservation:
    if isinstance(text, str):
        return PageObservation(text=text, html=html or "", url=url or "")
    observed_text = _value(text, "text", "visible_text", "dialog_text", "body_text")
    headings = _value(text, "headings")
    if headings:
        observed_text = f"{_as_text(observed_text)}\n{_as_text(headings)}"
    return PageObservation(
        text=_as_text(observed_text),
        html=html or _as_text(_value(text, "html", "content", "dom")),
        url=url or _as_text(_value(text, "url")),
        status_code=_value(text, "status_code", "status"),
    )


def _visible_html(raw_html: str) -> str:
    without_blocks = _SCRIPT_BLOCKS.sub(" ", raw_html)
    return _SPACE.sub(" ", unescape(_TAGS.sub(" ", without_blocks))).strip()


def _clean_excerpt(value: str, limit: int = 180) -> str:
    cleaned = _SPACE.sub(" ", unescape(_TAGS.sub(" ", value))).strip()
    cleaned = _EMAIL.sub("[REDACTED_EMAIL]", cleaned)
    cleaned = _CARD.sub("[REDACTED_NUMBER]", cleaned)
    cleaned = _PHONE.sub("[REDACTED_PHONE]", cleaned)
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}…"


def _pattern_evidence(source: str, patterns: tuple[str, ...], label: str) -> list[str]:
    evidence: list[str] = []
    for pattern in patterns:
        match = re.search(pattern, source, re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        excerpt = _clean_excerpt(match.group(0))
        item = f"{label}: {excerpt}" if excerpt else label
        if item not in evidence:
            evidence.append(item)
        if len(evidence) == 2:
            break
    return evidence


def _safe_url_evidence(url: str) -> str:
    try:
        parsed = urlsplit(url)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except (TypeError, ValueError):
        return "page URL"


def _url_matches(url: str, pattern: str) -> bool:
    try:
        return bool(re.search(pattern, urlsplit(url).path, re.IGNORECASE))
    except (TypeError, ValueError):
        return False


def _external_idp_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").rstrip(".").lower()
        if hostname in {"accounts.google.com", "login.microsoftonline.com", "appleid.apple.com"}:
            return True
        if hostname == "github.com" and re.search(r"^/(?:login|session|login/oauth/authorize)(?:/|$)", parsed.path, re.I):
            return True
        if (hostname.endswith(".okta.com") or hostname.endswith(".auth0.com")) and re.search(
            r"/(?:authorize|login|signin|oauth|saml|sso)(?:/|$)", parsed.path, re.I
        ):
            return True
        return bool(re.search(r"/(?:oauth2?|openid|saml|sso)/(?:authorize|login|signin)\b", parsed.path, re.I))
    except (TypeError, ValueError):
        return False


def _message(base: str, *, channel_switch: bool = False) -> str:
    if channel_switch:
        return (
            f"{base} This is not a finding by itself; paired-flow analysis may later "
            "evaluate it as a channel-switch mechanism."
        )
    return f"{base} This is an execution limitation, not a dark-pattern finding."


def detect_limitations(
    text: object = "",
    html: str = "",
    url: str = "",
    has_credentials: bool = False,
    phase: GraphPhase | None = None,
) -> list[AutomationLimitation]:
    """Detect explicit automation blockers from a page observation.

    Detection is deterministic and intentionally uses high-signal phrases and
    DOM markers. It never converts a blocker into a dark-pattern finding.
    """

    observation = _coerce_observation(text, html, url)
    combined_text = _SPACE.sub(
        " ", f"{observation.text}\n{_visible_html(observation.html)}"
    ).strip()
    raw_html = observation.html
    page_url = observation.url
    limitations: dict[str, AutomationLimitation] = {}

    def add(
        code: LimitationCode,
        base_message: str,
        recoverable: bool,
        evidence: list[str],
        *,
        channel_switch: bool = False,
    ) -> None:
        if code in limitations:
            return
        limitations[code] = AutomationLimitation(
            code=code,
            phase=phase,
            message=_message(base_message, channel_switch=channel_switch),
            recoverable=recoverable,
            evidence=list(dict.fromkeys(item for item in evidence if item))[:4],
        )

    captcha_evidence = _pattern_evidence(combined_text, _CAPTCHA_TEXT, "visible text")
    captcha_evidence += _pattern_evidence(raw_html, _CAPTCHA_HTML, "DOM")
    if captcha_evidence:
        add("captcha_required", "A CAPTCHA or human-verification challenge blocks browser automation.", True, captcha_evidence)

    email_evidence = _pattern_evidence(combined_text, _EMAIL_TEXT, "visible text")
    if _url_matches(page_url, r"/(?:verify|confirm)[-_]?(?:e-?mail)\b|/e-?mail[-_]?verification\b"):
        email_evidence.append(f"URL: {_safe_url_evidence(page_url)}")

    mfa_evidence = _pattern_evidence(combined_text, _MFA_TEXT, "visible text")
    if _url_matches(page_url, r"/(?:mfa|2fa|two[-_]?factor|authenticator)(?:/|$)"):
        mfa_evidence.append(f"URL: {_safe_url_evidence(page_url)}")
    if mfa_evidence:
        add("mfa_required", "Multi-factor authentication requires an out-of-band code or approval.", True, mfa_evidence)
    if email_evidence:
        add("email_verification_required", "The journey requires verification through an e-mail inbox.", True, email_evidence)

    auth_failure_evidence = _pattern_evidence(combined_text, _AUTH_FAILURE_TEXT, "visible text")
    if auth_failure_evidence:
        add("authentication_failed", "The page reports that authentication did not succeed.", True, auth_failure_evidence)

    credential_evidence: list[str] = []
    if not has_credentials:
        credential_evidence = _pattern_evidence(combined_text, _CREDENTIAL_TEXT, "visible text")
        credential_evidence += _pattern_evidence(raw_html, _CREDENTIAL_HTML, "DOM")
        if _url_matches(page_url, r"/(?:log[\s_-]*in|sign[\s_-]*in|session/new)(?:/|$)"):
            credential_evidence.append(f"URL: {_safe_url_evidence(page_url)}")
    if credential_evidence:
        add("credentials_required", "The requested journey cannot continue without account credentials.", True, credential_evidence)

    payment_evidence = _pattern_evidence(combined_text, _PAYMENT_TEXT, "visible text")
    payment_evidence += _pattern_evidence(raw_html, _PAYMENT_HTML, "DOM")
    if payment_evidence:
        add("payment_required", "The next state requires payment details or a financial commitment.", False, payment_evidence)

    idp_evidence = _pattern_evidence(combined_text, _EXTERNAL_IDP_TEXT, "visible text")
    idp_evidence += _pattern_evidence(raw_html, _EXTERNAL_IDP_HTML, "DOM")
    if _external_idp_url(page_url):
        idp_evidence.append(f"URL: {_safe_url_evidence(page_url)}")
    if idp_evidence:
        add("external_identity_provider", "Authentication has moved to an external identity provider.", True, idp_evidence)

    bot_evidence = _pattern_evidence(combined_text, _BOT_TEXT, "visible text")
    bot_evidence += _pattern_evidence(raw_html, _BOT_HTML, "DOM")
    if bot_evidence:
        add("bot_protection", "The site has presented an automated-access protection challenge.", True, bot_evidence)

    rate_evidence = _pattern_evidence(combined_text, _RATE_TEXT, "visible text")
    if observation.status_code == 429:
        rate_evidence.append("HTTP status: 429")
    if rate_evidence:
        add("rate_limited", "The site is refusing requests because its request limit was reached.", True, rate_evidence)

    channel_evidence = _pattern_evidence(combined_text, _CHANNEL_TEXT, "visible text")
    if channel_evidence:
        add(
            "channel_switch",
            "The browser journey explicitly directs the user to a phone, e-mail, chat, or physical channel.",
            False,
            channel_evidence,
            channel_switch=True,
        )

    native_evidence = _pattern_evidence(combined_text, _NATIVE_APP_TEXT, "visible text")
    native_evidence += _pattern_evidence(raw_html, _NATIVE_APP_HTML, "DOM")
    try:
        if urlsplit(page_url).scheme.lower() in {"intent", "market", "itms-apps", "android-app"}:
            native_evidence.append(f"URL: {_safe_url_evidence(page_url)}")
    except (TypeError, ValueError):
        pass
    if native_evidence:
        add("native_app_required", "The journey requires a native or mobile application.", False, native_evidence)

    order = (
        "captcha_required",
        "mfa_required",
        "email_verification_required",
        "credentials_required",
        "authentication_failed",
        "payment_required",
        "external_identity_provider",
        "bot_protection",
        "rate_limited",
        "channel_switch",
        "native_app_required",
    )
    return [limitations[code] for code in order if code in limitations]


def is_mechanism_eligible(limitation: AutomationLimitation | LimitationCode | str) -> bool:
    """Whether a limitation may be evaluated later with paired-flow evidence."""

    code = limitation.code if isinstance(limitation, AutomationLimitation) else str(limitation)
    return code in MECHANISM_ELIGIBLE_LIMITATIONS


detect_page_limitations = detect_limitations


__all__ = [
    "MECHANISM_ELIGIBLE_LIMITATIONS",
    "PageObservation",
    "detect_limitations",
    "detect_page_limitations",
    "is_mechanism_eligible",
]

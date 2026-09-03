from __future__ import annotations

"""Deterministic intent discovery and acquisition/exit goal pairing.

The autonomous explorer intentionally keeps this layer rule based.  A control is
ranked from evidence that can be reproduced in a report: its accessible name,
href, and the surrounding page/dialog context.  The taxonomy is English-first,
but it is kept in one data structure so additional locales can be added without
changing the ranking algorithm.
"""

from dataclasses import dataclass
from math import sqrt
import re
from typing import Iterable, Literal, Sequence
from urllib.parse import unquote, urlsplit

from app.flow_analysis.autonomous_schemas import GoalFamily, GoalFamilyRequest, ObservedControl


IntentPhase = Literal["acquisition", "exit"]


@dataclass(frozen=True, slots=True)
class GoalIntentTaxonomy:
    """Opposite actions and the context that identifies one goal family.

    Terms listed in ``contextual_*`` are deliberately too broad to classify on
    their own.  For example, ``Remove`` is useful for a payment method only when
    the label, URL, or surrounding context also mentions a card, wallet, or
    payment method.
    """

    family: GoalFamily
    opposites: tuple[tuple[str, str], ...]
    context_terms: tuple[str, ...]
    contextual_acquisition_terms: tuple[str, ...] = ()
    contextual_exit_terms: tuple[str, ...] = ()
    object_noise: tuple[str, ...] = ()

    @property
    def acquisition_terms(self) -> tuple[str, ...]:
        return _unique(pair[0] for pair in self.opposites)

    @property
    def exit_terms(self) -> tuple[str, ...]:
        return _unique(pair[1] for pair in self.opposites)


@dataclass(frozen=True, slots=True)
class RankedIntentCandidate:
    """One reproducible family/phase interpretation of an observed control."""

    control: ObservedControl
    family: GoalFamily
    phase: IntentPhase
    score: float
    object_tokens: tuple[str, ...]
    contextual: bool


@dataclass(frozen=True, slots=True)
class GoalCandidatePair:
    """A compatible acquisition/exit pair for the same user object."""

    family: GoalFamily
    acquisition: RankedIntentCandidate
    exit: RankedIntentCandidate
    confidence: float
    object_tokens: tuple[str, ...]
    signature: str


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


# Every GoalFamily from autonomous_schemas.py has opposite actions and context.
# Phrase ordering is significant only for reporting; matching always prefers the
# longest phrase and final candidate sorting has explicit deterministic keys.
GOAL_TAXONOMY: dict[GoalFamily, GoalIntentTaxonomy] = {
    "account_create_delete": GoalIntentTaxonomy(
        family="account_create_delete",
        opposites=(
            ("create account", "delete account"),
            ("sign up", "close account"),
            ("signup", "deactivate account"),
            ("register", "remove account"),
            ("open account", "terminate account"),
            ("create", "delete"),
            ("open", "close"),
        ),
        context_terms=("account", "profile", "user account", "account settings", "personal account"),
        contextual_acquisition_terms=("create", "open"),
        contextual_exit_terms=("delete", "close"),
        object_noise=("new", "my", "your", "personal", "user"),
    ),
    "subscribe_cancel": GoalIntentTaxonomy(
        family="subscribe_cancel",
        opposites=(
            ("subscribe", "cancel subscription"),
            ("start trial", "cancel trial"),
            ("activate subscription", "end subscription"),
            ("upgrade plan", "cancel plan"),
            ("start membership", "cancel membership"),
            ("activate", "cancel"),
            ("start", "end"),
        ),
        context_terms=(
            "subscription",
            "billing plan",
            "pricing plan",
            "membership",
            "paid plan",
            "free trial",
            "trial plan",
        ),
        contextual_acquisition_terms=("activate", "start"),
        contextual_exit_terms=("cancel", "end"),
        object_noise=("current", "paid", "free", "billing", "pricing"),
    ),
    "newsletter_subscribe_unsubscribe": GoalIntentTaxonomy(
        family="newsletter_subscribe_unsubscribe",
        opposites=(
            ("subscribe to newsletter", "unsubscribe"),
            ("join newsletter", "leave newsletter"),
            ("get email updates", "stop email updates"),
            ("join mailing list", "leave mailing list"),
            ("sign up for emails", "opt out of emails"),
            ("subscribe", "opt out"),
            ("sign up", "stop"),
        ),
        context_terms=(
            "newsletter",
            "mailing list",
            "email updates",
            "marketing email",
            "marketing emails",
            "promotional email",
            "email preferences",
            "communications preferences",
        ),
        contextual_acquisition_terms=("subscribe", "sign up", "join"),
        contextual_exit_terms=("opt out", "stop"),
        object_noise=("marketing", "promotional", "communication", "communications"),
    ),
    "consent_grant_withdraw": GoalIntentTaxonomy(
        family="consent_grant_withdraw",
        opposites=(
            ("give consent", "withdraw consent"),
            ("grant consent", "revoke consent"),
            ("accept all", "reject all"),
            ("allow all", "deny all"),
            ("opt in", "opt out"),
            ("accept", "reject"),
            ("allow", "withdraw"),
        ),
        context_terms=(
            "consent",
            "cookie consent",
            "cookies",
            "tracking",
            "privacy choices",
            "personalized ads",
            "personalised ads",
            "privacy settings",
        ),
        contextual_acquisition_terms=("opt in", "accept", "allow"),
        contextual_exit_terms=("opt out", "reject", "withdraw"),
        object_noise=("all", "optional", "privacy", "choice", "choices"),
    ),
    "notifications_enable_disable": GoalIntentTaxonomy(
        family="notifications_enable_disable",
        opposites=(
            ("enable notifications", "disable notifications"),
            ("turn on notifications", "turn off notifications"),
            ("allow notifications", "mute notifications"),
            ("enable alerts", "disable alerts"),
            ("turn on", "turn off"),
            ("enable", "disable"),
            ("allow", "mute"),
        ),
        context_terms=(
            "notification",
            "notifications",
            "push notification",
            "email notification",
            "alerts",
            "notification settings",
        ),
        contextual_acquisition_terms=("turn on", "enable", "allow"),
        contextual_exit_terms=("turn off", "disable", "mute"),
        object_noise=("push", "email", "browser", "mobile"),
    ),
    "integration_connect_disconnect": GoalIntentTaxonomy(
        family="integration_connect_disconnect",
        opposites=(
            ("connect integration", "disconnect integration"),
            ("connect app", "disconnect app"),
            ("authorize app", "revoke app access"),
            ("link service", "unlink service"),
            ("install integration", "uninstall integration"),
            ("connect", "disconnect"),
            ("link", "unlink"),
            ("authorize", "revoke"),
            ("install", "uninstall"),
        ),
        context_terms=(
            "integration",
            "integrations",
            "connected app",
            "connected apps",
            "app connection",
            "third party app",
            "authorized app",
            "extension",
            "plugin",
        ),
        contextual_acquisition_terms=("connect", "link", "authorize", "install"),
        contextual_exit_terms=("disconnect", "unlink", "revoke", "uninstall"),
        object_noise=("third", "party", "connected", "authorized", "service"),
    ),
    "payment_method_add_remove": GoalIntentTaxonomy(
        family="payment_method_add_remove",
        opposites=(
            ("add payment method", "remove payment method"),
            ("add card", "delete card"),
            ("save card", "remove card"),
            ("link bank", "unlink bank"),
            ("add", "remove"),
            ("save", "delete"),
            ("link", "unlink"),
        ),
        context_terms=(
            "payment method",
            "payment methods",
            "credit card",
            "debit card",
            "saved card",
            "billing",
            "wallet",
            "bank account",
        ),
        contextual_acquisition_terms=("add", "save", "link"),
        contextual_exit_terms=("remove", "delete", "unlink"),
        object_noise=("ending", "expires", "default", "saved", "credit", "debit", "bank"),
    ),
    "loyalty_join_leave": GoalIntentTaxonomy(
        family="loyalty_join_leave",
        opposites=(
            ("join loyalty program", "leave loyalty program"),
            ("join rewards", "leave rewards"),
            ("enroll in rewards", "unenroll from rewards"),
            ("enrol in rewards", "unenrol from rewards"),
            ("activate rewards", "close rewards account"),
            ("join", "leave"),
            ("enroll", "unenroll"),
            ("enrol", "unenrol"),
        ),
        context_terms=(
            "loyalty",
            "loyalty program",
            "loyalty programme",
            "rewards",
            "rewards program",
            "rewards membership",
            "points program",
        ),
        contextual_acquisition_terms=("join", "enroll", "enrol"),
        contextual_exit_terms=("leave", "unenroll", "unenrol"),
        object_noise=("point", "points", "program", "programme", "membership"),
    ),
    "data_share_revoke": GoalIntentTaxonomy(
        family="data_share_revoke",
        opposites=(
            ("enable data sharing", "disable data sharing"),
            ("share data", "stop sharing data"),
            ("grant data access", "revoke data access"),
            ("allow third party access", "withdraw third party access"),
            ("share", "stop sharing"),
            ("grant", "revoke"),
            ("enable", "disable"),
        ),
        context_terms=(
            "data sharing",
            "share my data",
            "data access",
            "third party access",
            "third party data",
            "personal data",
            "data permissions",
        ),
        contextual_acquisition_terms=("share", "grant", "enable"),
        contextual_exit_terms=("stop sharing", "revoke", "disable"),
        object_noise=("my", "personal", "third", "party", "permission", "permissions"),
    ),
    "purchase_return": GoalIntentTaxonomy(
        family="purchase_return",
        opposites=(
            ("buy now", "return item"),
            ("purchase", "request refund"),
            ("place order", "return order"),
            ("checkout", "refund order"),
            ("complete purchase", "exchange item"),
            ("buy", "return"),
            ("order", "cancel order"),
        ),
        context_terms=(
            "shopping cart",
            "checkout",
            "product",
            "item",
            "order",
            "purchase",
            "refund",
            "returns",
            "receipt",
        ),
        contextual_acquisition_terms=("buy", "order"),
        contextual_exit_terms=("return",),
        object_noise=("shopping", "cart", "current", "purchased"),
    ),
}

FAMILY_ORDER: tuple[GoalFamily, ...] = tuple(GOAL_TAXONOMY)

# Convenient public view used by explainers and tests without knowing the
# GoalIntentTaxonomy implementation.
OPPOSITE_TERMS: dict[GoalFamily, tuple[tuple[str, str], ...]] = {
    family: taxonomy.opposites for family, taxonomy in GOAL_TAXONOMY.items()
}
GOAL_CONTEXT_TERMS: dict[GoalFamily, tuple[str, ...]] = {
    family: taxonomy.context_terms for family, taxonomy in GOAL_TAXONOMY.items()
}


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SPACE_RE = re.compile(r"\s+")
_PUNCTUATION_RE = re.compile(r"[^a-z0-9]+")
_OBJECT_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "for",
    "from",
    "in",
    "into",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "please",
    "settings",
    "the",
    "this",
    "to",
    "with",
    "your",
    "manage",
    "management",
    "preferences",
    "setting",
    "action",
    "button",
    "link",
}
_ACTIONABLE_ROLES = {
    "button",
    "link",
    "menuitem",
    "option",
    "checkbox",
    "radio",
    "switch",
    "tab",
}


def normalize_intent_text(value: str | None) -> str:
    """Normalize labels, URLs, and headings for reproducible phrase matching."""

    if not value:
        return ""
    decoded = unquote(str(value)).casefold().replace("&", " and ")
    return _SPACE_RE.sub(" ", _PUNCTUATION_RE.sub(" ", decoded)).strip()


def _href_text(href: str | None) -> str:
    if not href:
        return ""
    try:
        parsed = urlsplit(href)
        # Query values commonly contain credentials, opaque state, or tracking
        # identifiers, none of which should influence semantic goal discovery.
        return normalize_intent_text(f"{parsed.path} {parsed.fragment}")
    except ValueError:
        return normalize_intent_text(href)


def _coerce_context(context: str | Sequence[str] | None) -> str:
    if context is None:
        return ""
    if isinstance(context, str):
        return normalize_intent_text(context)
    return normalize_intent_text(" ".join(str(item) for item in context if item))


def _contains(text: str, phrase: str) -> bool:
    normalized_phrase = normalize_intent_text(phrase)
    return bool(normalized_phrase) and f" {normalized_phrase} " in f" {text} "


def _hits(text: str, terms: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            (term for term in terms if _contains(text, term)),
            key=lambda term: (-len(normalize_intent_text(term).split()), -len(term), term),
        )
    )


def _requested_families(
    goal_families: Sequence[GoalFamily | GoalFamilyRequest] | None,
) -> tuple[GoalFamily, ...]:
    if not goal_families or "auto" in goal_families:
        return FAMILY_ORDER
    unknown = set(goal_families).difference(FAMILY_ORDER)
    if unknown:
        raise ValueError(f"Unknown goal families: {', '.join(sorted(unknown))}")
    requested = set(goal_families)
    return tuple(family for family in FAMILY_ORDER if family in requested)


def _canonical_object_token(token: str) -> str:
    aliases = {
        "apps": "app",
        "cards": "card",
        "emails": "email",
        "items": "item",
        "methods": "method",
        "notifications": "notification",
        "orders": "order",
        "plans": "plan",
        "products": "product",
        "services": "service",
        "subscriptions": "subscription",
    }
    return aliases.get(token, token)


def object_tokens_for_control(control: ObservedControl, family: GoalFamily) -> tuple[str, ...]:
    """Extract a stable object signature (for example ``slack`` or ``basic``).

    Page-wide context is deliberately excluded because every control on a page
    shares it.  Only the accessible name and the URL path/fragment can identify
    the particular account, plan, integration, or product being acted upon.
    """

    taxonomy = GOAL_TAXONOMY[family]
    surface = normalize_intent_text(f"{control.name} {_href_text(control.href)}")
    noise_phrases = (
        taxonomy.acquisition_terms
        + taxonomy.exit_terms
        + taxonomy.context_terms
        + taxonomy.object_noise
    )
    noise = set(_OBJECT_STOPWORDS)
    for phrase in noise_phrases:
        noise.update(_TOKEN_RE.findall(normalize_intent_text(phrase)))

    result: list[str] = []
    for raw_token in _TOKEN_RE.findall(surface):
        token = _canonical_object_token(raw_token)
        if token in noise or len(token) < 2 or token.isdigit():
            continue
        # Opaque hashes and cache-busting URL fragments are not object identity.
        if len(token) >= 12 and any(char.isdigit() for char in token):
            continue
        if token not in result:
            result.append(token)
    return tuple(result)


def _phase_score(
    *,
    control: ObservedControl,
    taxonomy: GoalIntentTaxonomy,
    phase: IntentPhase,
    name_text: str,
    href_text: str,
    context_text: str,
    foreign_context_present: bool,
) -> float | None:
    terms = taxonomy.acquisition_terms if phase == "acquisition" else taxonomy.exit_terms
    contextual_terms = set(
        taxonomy.contextual_acquisition_terms
        if phase == "acquisition"
        else taxonomy.contextual_exit_terms
    )
    opposite_terms = taxonomy.exit_terms if phase == "acquisition" else taxonomy.acquisition_terms

    name_hits = _hits(name_text, terms)
    href_hits = _hits(href_text, terms)
    label_context_hits = _hits(name_text, taxonomy.context_terms)
    href_context_hits = _hits(href_text, taxonomy.context_terms)
    page_context_hits = _hits(context_text, taxonomy.context_terms)
    has_family_context = bool(label_context_hits or href_context_hits or page_context_hits)

    standalone_name = tuple(term for term in name_hits if term not in contextual_terms)
    contextual_name = tuple(term for term in name_hits if term in contextual_terms)
    standalone_href = tuple(term for term in href_hits if term not in contextual_terms)
    contextual_href = tuple(term for term in href_hits if term in contextual_terms)

    permitted_contextual_name = contextual_name if has_family_context else ()
    permitted_contextual_href = contextual_href if has_family_context else ()
    if not (standalone_name or standalone_href or permitted_contextual_name or permitted_contextual_href):
        return None

    score = 0.0
    primary_term = ""
    if standalone_name:
        primary_term = standalone_name[0]
        score += 0.56
    elif permitted_contextual_name:
        primary_term = permitted_contextual_name[0]
        score += 0.38

    if standalone_href:
        primary_term = primary_term or standalone_href[0]
        score += 0.32 if not name_hits else 0.12
    elif permitted_contextual_href:
        primary_term = primary_term or permitted_contextual_href[0]
        score += 0.24 if not name_hits else 0.08

    if label_context_hits:
        score += 0.18
    elif href_context_hits:
        score += 0.14
    elif page_context_hits:
        score += 0.11

    if primary_term:
        term_length = len(normalize_intent_text(primary_term).split())
        score += min(0.09, max(0, term_length - 1) * 0.03)
        if name_text == normalize_intent_text(primary_term):
            score += 0.10

    if control.role.casefold() in _ACTIONABLE_ROLES:
        score += 0.03
    if control.disabled:
        score -= 0.10

    # Strong page context for another family disambiguates overloaded words such
    # as subscribe, disable, remove, and revoke.
    if foreign_context_present and not has_family_context:
        score -= 0.24

    opposite_name_hits = _hits(name_text, opposite_terms)
    if opposite_name_hits:
        # Mixed controls like "Create or delete account" are weak traversal
        # choices for either direction, but remain visible to the explorer.
        score -= 0.18

    return max(0.0, min(1.0, score))


def classify_control(
    control: ObservedControl,
    context: str | Sequence[str] | None = None,
    goal_families: Sequence[GoalFamily | GoalFamilyRequest] | None = None,
    *,
    minimum_score: float = 0.46,
) -> list[RankedIntentCandidate]:
    """Return all credible family/phase interpretations for one control."""

    if not 0 <= minimum_score <= 1:
        raise ValueError("minimum_score must be between 0 and 1")
    families = _requested_families(goal_families)
    name_text = normalize_intent_text(control.name)
    href_text = _href_text(control.href)
    context_text = _coerce_context(context)

    context_matches = {
        family: bool(
            _hits(name_text, GOAL_TAXONOMY[family].context_terms)
            or _hits(href_text, GOAL_TAXONOMY[family].context_terms)
            or _hits(context_text, GOAL_TAXONOMY[family].context_terms)
        )
        for family in families
    }
    candidates: list[RankedIntentCandidate] = []
    for family in families:
        taxonomy = GOAL_TAXONOMY[family]
        foreign_context_present = any(
            matched for other_family, matched in context_matches.items() if other_family != family
        )
        for phase in ("acquisition", "exit"):
            score = _phase_score(
                control=control,
                taxonomy=taxonomy,
                phase=phase,
                name_text=name_text,
                href_text=href_text,
                context_text=context_text,
                foreign_context_present=foreign_context_present,
            )
            if score is None or score < minimum_score:
                continue
            candidates.append(
                RankedIntentCandidate(
                    control=control,
                    family=family,
                    phase=phase,
                    score=round(score, 6),
                    object_tokens=object_tokens_for_control(control, family),
                    # This flag records actual surrounding context evidence, not
                    # merely a family noun embedded in the control itself.
                    contextual=bool(_hits(context_text, taxonomy.context_terms)),
                )
            )

    return sorted(candidates, key=_candidate_sort_key)


def _candidate_sort_key(candidate: RankedIntentCandidate) -> tuple[object, ...]:
    return (
        -candidate.score,
        FAMILY_ORDER.index(candidate.family),
        0 if candidate.phase == "acquisition" else 1,
        candidate.control.document_index,
        candidate.control.control_id,
        normalize_intent_text(candidate.control.name),
    )


def rank_intent_candidates(
    controls: Sequence[ObservedControl],
    context: str | Sequence[str] | None = None,
    goal_families: Sequence[GoalFamily | GoalFamilyRequest] | None = None,
    *,
    minimum_score: float = 0.46,
    limit: int | None = None,
) -> list[RankedIntentCandidate]:
    """Rank controls deterministically by family and acquisition/exit phase."""

    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    candidates = [
        candidate
        for control in controls
        for candidate in classify_control(
            control,
            context,
            goal_families,
            minimum_score=minimum_score,
        )
    ]
    ranked = sorted(candidates, key=_candidate_sort_key)
    return ranked[:limit] if limit is not None else ranked


def _object_equivalence(
    acquisition_tokens: tuple[str, ...],
    exit_tokens: tuple[str, ...],
) -> tuple[float, tuple[str, ...]] | None:
    acquisition_set = set(acquisition_tokens)
    exit_set = set(exit_tokens)
    if acquisition_set and exit_set:
        shared = acquisition_set.intersection(exit_set)
        if not shared:
            return None
        union = acquisition_set.union(exit_set)
        coverage = len(shared) / min(len(acquisition_set), len(exit_set))
        jaccard = len(shared) / len(union)
        equivalence = 0.65 * coverage + 0.35 * jaccard
        ordered_shared = tuple(token for token in acquisition_tokens if token in shared)
        return equivalence, ordered_shared
    if not acquisition_set and not exit_set:
        return 0.75, ()
    # One side may use a generic label such as "Cancel" while the other names
    # the Basic plan.  Family agreement keeps it eligible, at lower confidence.
    known = acquisition_tokens or exit_tokens
    return 0.52, known


def pair_goal_candidates(
    candidates: Sequence[RankedIntentCandidate],
    *,
    minimum_confidence: float = 0.45,
) -> list[GoalCandidatePair]:
    """Pair equivalent acquisition and exit candidates.

    Pairs must share a family.  If both controls identify an object, at least one
    canonical object token must overlap.  Results include every compatible pair
    and are sorted deterministically, allowing an explorer to apply its own
    state/depth constraints afterward.
    """

    if not 0 <= minimum_confidence <= 1:
        raise ValueError("minimum_confidence must be between 0 and 1")
    acquisitions = [candidate for candidate in candidates if candidate.phase == "acquisition"]
    exits = [candidate for candidate in candidates if candidate.phase == "exit"]
    pairs: list[GoalCandidatePair] = []
    seen: set[tuple[GoalFamily, str, str]] = set()

    for acquisition in acquisitions:
        for exit_candidate in exits:
            if acquisition.family != exit_candidate.family:
                continue
            if acquisition.control.control_id == exit_candidate.control.control_id:
                continue
            equivalence_result = _object_equivalence(
                acquisition.object_tokens,
                exit_candidate.object_tokens,
            )
            if equivalence_result is None:
                continue
            object_equivalence, object_tokens = equivalence_result
            candidate_quality = sqrt(acquisition.score * exit_candidate.score)
            confidence = round(0.68 * candidate_quality + 0.32 * object_equivalence, 6)
            if confidence < minimum_confidence:
                continue
            key = (acquisition.family, acquisition.control.control_id, exit_candidate.control.control_id)
            if key in seen:
                continue
            seen.add(key)
            signature_suffix = "-".join(object_tokens) if object_tokens else "default"
            pairs.append(
                GoalCandidatePair(
                    family=acquisition.family,
                    acquisition=acquisition,
                    exit=exit_candidate,
                    confidence=confidence,
                    object_tokens=object_tokens,
                    signature=f"{acquisition.family}:{signature_suffix}",
                )
            )

    return sorted(
        pairs,
        key=lambda pair: (
            -pair.confidence,
            FAMILY_ORDER.index(pair.family),
            pair.signature,
            pair.acquisition.control.document_index,
            pair.exit.control.document_index,
            pair.acquisition.control.control_id,
            pair.exit.control.control_id,
        ),
    )

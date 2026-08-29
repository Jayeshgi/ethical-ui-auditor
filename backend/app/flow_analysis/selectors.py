from __future__ import annotations

"""Resilient selector construction and Playwright resolution helpers."""

import re
from typing import Any, Mapping, Sequence

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page

from app.flow_analysis.autonomous_schemas import SelectorStrategy


SELECTOR_KIND_PRIORITY = {
    "role": 0,
    "label": 1,
    "data_attribute": 2,
    "id": 3,
    "name": 4,
    "css": 5,
}
DATA_ATTRIBUTE_PRIORITY = (
    "data-testid",
    "data-test-id",
    "data-test",
    "data-qa",
    "data-cy",
    "data-flow",
    "data-action",
    "data-control",
)

_UUID_RE = re.compile(
    r"^[{(]?[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}[)}]?$",
    re.IGNORECASE,
)
_LONG_HEX_SEGMENT_RE = re.compile(r"(?:^|[-_:])[0-9a-f]{8,}(?:$|[-_:])", re.IGNORECASE)
_LONG_NUMBER_RE = re.compile(r"\d{6,}")
_GENERATED_PREFIX_RE = re.compile(
    r"^(?:ember|react(?:-select)?|radix|headlessui|mui|mantine|chakra|generated|auto)[-_:]*[a-z]*[-_:]*\d+",
    re.IGNORECASE,
)
_REACT_ARIA_ID_RE = re.compile(r"^:r[0-9a-z]+:$", re.IGNORECASE)
_FRAMEWORK_ARIA_ID_RE = re.compile(
    r"^(?:radix|headlessui|mui|mantine|chakra).*(?::r[0-9a-z]+:)",
    re.IGNORECASE,
)
_SAFE_ATTRIBUTE_RE = re.compile(r"^data-[a-z0-9_-]+$", re.IGNORECASE)
_LABELABLE_ROLES = {"checkbox", "combobox", "radio", "searchbox", "slider", "spinbutton", "switch", "textbox"}


def _clean(value: object | None, *, maximum: int = 1000) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split()).strip()
    if not cleaned or len(cleaned) > maximum:
        return None
    return cleaned


def _raw_id(value: str) -> str:
    """Accept both a raw ID and the simple selector forms used by old callers."""

    cleaned = value.strip()
    if cleaned.startswith("#") and not any(char in cleaned[1:] for char in " .>+~[]"):
        return cleaned[1:]
    match = re.fullmatch(r"\[id=(?:\"([^\"]+)\"|'([^']+)')\]", cleaned)
    if match:
        return match.group(1) or match.group(2)
    return cleaned


def is_dynamic_id(value: str | None) -> bool:
    """Return whether an element ID looks generated and unsafe for replay.

    This is deliberately conservative around meaningful IDs containing a small
    number (``address-line-1`` remains valid) while rejecting UUIDs, timestamps,
    framework counters, long hashes, and React's colon-delimited aria IDs.
    """

    cleaned = _clean(value, maximum=160)
    if cleaned is None:
        return True
    cleaned = _raw_id(cleaned)
    if not cleaned or any(char.isspace() for char in cleaned):
        return True
    if (
        _UUID_RE.fullmatch(cleaned)
        or _REACT_ARIA_ID_RE.fullmatch(cleaned)
        or _FRAMEWORK_ARIA_ID_RE.search(cleaned)
    ):
        return True
    if cleaned.isdigit() or _LONG_NUMBER_RE.search(cleaned):
        return True
    if _LONG_HEX_SEGMENT_RE.search(cleaned) or _GENERATED_PREFIX_RE.search(cleaned):
        return True

    alphanumeric = re.sub(r"[^a-z0-9]", "", cleaned.casefold())
    # A long mixed token with no word separators is normally a generated hash.
    if (
        len(alphanumeric) >= 18
        and cleaned == alphanumeric
        and any(char.isdigit() for char in alphanumeric)
        and any(char.isalpha() for char in alphanumeric)
    ):
        return True
    return False


def _looks_dynamic_attribute_value(value: str) -> bool:
    return bool(
        _UUID_RE.fullmatch(value)
        or _REACT_ARIA_ID_RE.fullmatch(value)
        or _LONG_NUMBER_RE.search(value)
        or _LONG_HEX_SEGMENT_RE.search(value)
        or len(value) > 300
    )


def _css_string(value: str) -> str:
    """Escape an untrusted value for a double-quoted CSS attribute selector."""

    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", "\\a ")
        .replace("\n", "\\a ")
        .replace("\r", "\\d ")
        .replace("\f", "\\c ")
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def build_selector_bundle(
    element: Mapping[str, object] | None = None,
    *,
    role: str | None = None,
    accessible_name: str | None = None,
    label: str | None = None,
    attributes: Mapping[str, object] | None = None,
    element_id: str | None = None,
    name: str | None = None,
    css: str | None = None,
) -> list[SelectorStrategy]:
    """Build ordered selector fallbacks from a DOM observation.

    ``element`` is optional and supports browser-evaluation dictionaries using
    ``role``, ``accessible_name``/``accessibleName``, ``label``, ``attributes``,
    ``id``, ``name_attribute``/``dom_name``, and ``css`` keys.  Explicit keyword
    arguments take precedence.  Strategy values are semantic text for role,
    label, ID, and name selectors; data-attribute and CSS values are complete CSS
    selectors because SelectorStrategy has no separate attribute-name field.
    """

    source: Mapping[str, object] = element or {}
    nested_attributes = _mapping(source.get("attributes"))
    merged_attributes: dict[str, object] = dict(nested_attributes)
    if attributes:
        merged_attributes.update(attributes)
    for attribute_name in DATA_ATTRIBUTE_PRIORITY:
        if attribute_name in source and attribute_name not in merged_attributes:
            merged_attributes[attribute_name] = source[attribute_name]

    resolved_role = _clean(role if role is not None else source.get("role"), maximum=80)
    resolved_accessible_name = _clean(
        accessible_name
        if accessible_name is not None
        else source.get(
            "accessible_name",
            source.get("accessibleName", source.get("name", source.get("text"))),
        ),
        maximum=300,
    )
    resolved_label = _clean(label if label is not None else source.get("label"), maximum=300)
    resolved_id = _clean(
        element_id
        if element_id is not None
        else source.get("id", merged_attributes.get("id")),
        maximum=160,
    )
    resolved_dom_name = _clean(
        name
        if name is not None
        else source.get("name_attribute", source.get("dom_name", merged_attributes.get("name"))),
        maximum=300,
    )
    resolved_css = _clean(css if css is not None else source.get("css"), maximum=1000)

    strategies: list[SelectorStrategy] = []
    if resolved_role and resolved_accessible_name:
        strategies.append(
            SelectorStrategy(
                kind="role",
                value=resolved_accessible_name,
                role=resolved_role.casefold(),
                accessible_name=resolved_accessible_name,
                stable=True,
            )
        )

    semantic_label = resolved_label
    if semantic_label is None and resolved_role and resolved_role.casefold() in _LABELABLE_ROLES:
        semantic_label = resolved_accessible_name
    if semantic_label:
        strategies.append(
            SelectorStrategy(
                kind="label",
                value=semantic_label,
                accessible_name=resolved_accessible_name or semantic_label,
                stable=True,
            )
        )

    for attribute_name in DATA_ATTRIBUTE_PRIORITY:
        attribute_value = _clean(merged_attributes.get(attribute_name), maximum=300)
        if not attribute_value or not _SAFE_ATTRIBUTE_RE.fullmatch(attribute_name):
            continue
        if _looks_dynamic_attribute_value(attribute_value):
            continue
        strategies.append(
            SelectorStrategy(
                kind="data_attribute",
                value=f'[{attribute_name}="{_css_string(attribute_value)}"]',
                accessible_name=resolved_accessible_name,
                stable=True,
            )
        )

    if resolved_id and not is_dynamic_id(resolved_id):
        strategies.append(
            SelectorStrategy(
                kind="id",
                value=_raw_id(resolved_id),
                accessible_name=resolved_accessible_name,
                stable=True,
            )
        )

    if resolved_dom_name:
        strategies.append(
            SelectorStrategy(
                kind="name",
                value=resolved_dom_name,
                accessible_name=resolved_accessible_name,
                stable=True,
            )
        )

    if resolved_css:
        lower_css = resolved_css.casefold()
        css_stable = not (
            ":nth-child" in lower_css
            or ":nth-of-type" in lower_css
            or _LONG_HEX_SEGMENT_RE.search(lower_css)
            or _LONG_NUMBER_RE.search(lower_css)
        )
        strategies.append(
            SelectorStrategy(
                kind="css",
                value=resolved_css,
                accessible_name=resolved_accessible_name,
                stable=css_stable,
            )
        )

    deduplicated: list[SelectorStrategy] = []
    seen: set[tuple[object, ...]] = set()
    for strategy in sorted_selector_strategies(strategies):
        key = (strategy.kind, strategy.value, strategy.role, strategy.accessible_name)
        if key not in seen:
            seen.add(key)
            deduplicated.append(strategy)
    return deduplicated


def sorted_selector_strategies(strategies: Sequence[SelectorStrategy]) -> list[SelectorStrategy]:
    """Normalize caller-provided bundles to the documented resolution order."""

    return [
        strategy
        for _index, strategy in sorted(
            enumerate(strategies),
            key=lambda item: (
                SELECTOR_KIND_PRIORITY[item[1].kind],
                not item[1].stable,
                item[0],
            ),
        )
    ]


def locator_for_strategy(page: Page, strategy: SelectorStrategy) -> Locator | None:
    """Construct (but do not query) the Playwright locator for one strategy."""

    if strategy.kind == "role":
        role = _clean(strategy.role, maximum=80)
        accessible_name = _clean(strategy.accessible_name or strategy.value, maximum=300)
        if not role or not accessible_name:
            return None
        return page.get_by_role(role, name=accessible_name, exact=True)
    if strategy.kind == "label":
        label = _clean(strategy.value, maximum=300)
        return page.get_by_label(label, exact=True) if label else None
    if strategy.kind == "data_attribute":
        selector = _clean(strategy.value)
        return page.locator(selector) if selector else None
    if strategy.kind == "id":
        element_id = _clean(strategy.value, maximum=160)
        if not element_id or is_dynamic_id(element_id):
            return None
        # Always rebuild the attribute selector from an escaped literal. A
        # persisted strategy is data, not trusted CSS; accepting a string that
        # merely starts with ``[id=`` would permit selector-list injection.
        selector = f'[id="{_css_string(_raw_id(element_id))}"]'
        return page.locator(selector)
    if strategy.kind == "name":
        dom_name = _clean(strategy.value, maximum=300)
        if not dom_name:
            return None
        selector = f'[name="{_css_string(dom_name)}"]'
        return page.locator(selector)
    if strategy.kind == "css":
        selector = _clean(strategy.value)
        return page.locator(selector) if selector else None
    return None


async def resolve_selector(
    page: Page,
    strategies: Sequence[SelectorStrategy],
    *,
    require_visible: bool = True,
    visibility_timeout_ms: int = 500,
) -> tuple[Locator, SelectorStrategy] | None:
    """Resolve the first attached (and normally visible) selector fallback.

    Resolution does not click or otherwise mutate the page.  Dynamic IDs are
    rejected again here so untrusted persisted bundles cannot bypass construction
    checks.  Playwright strict-mode/query errors simply advance to the next
    strategy.
    """

    if visibility_timeout_ms < 0:
        raise ValueError("visibility_timeout_ms cannot be negative")
    for strategy in sorted_selector_strategies(strategies):
        try:
            locator = locator_for_strategy(page, strategy)
            if locator is None:
                continue
            count = await locator.count()
            if count < 1:
                continue
            if not require_visible:
                return locator.first, strategy
            # A repeated accessible label may have a hidden mobile copy before a
            # visible desktop control.  Check a bounded number without waiting.
            for index in range(min(count, 20)):
                candidate = locator.nth(index)
                if await candidate.is_visible(timeout=visibility_timeout_ms):
                    return candidate, strategy
        except (PlaywrightError, ValueError, TypeError):
            continue
    return None

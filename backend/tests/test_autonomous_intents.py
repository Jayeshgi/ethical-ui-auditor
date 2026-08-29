from __future__ import annotations

from typing import get_args

import pytest

from app.flow_analysis.autonomous_schemas import GoalFamily, ObservedControl, SelectorStrategy
from app.flow_analysis.intents import (
    GOAL_CONTEXT_TERMS,
    GOAL_TAXONOMY,
    OPPOSITE_TERMS,
    classify_control,
    pair_goal_candidates,
    rank_intent_candidates,
)
from app.flow_analysis.selectors import build_selector_bundle, is_dynamic_id, resolve_selector


def _control(control_id: str, name: str, href: str = "", document_index: int = 0) -> ObservedControl:
    return ObservedControl(
        control_id=control_id,
        role="button",
        name=name,
        href=href or None,
        document_index=document_index,
    )


def test_taxonomy_covers_every_goal_family_with_opposites_and_context() -> None:
    expected = set(get_args(GoalFamily))

    assert set(GOAL_TAXONOMY) == expected
    assert set(OPPOSITE_TERMS) == expected
    assert set(GOAL_CONTEXT_TERMS) == expected
    assert all(taxonomy.opposites for taxonomy in GOAL_TAXONOMY.values())
    assert all(taxonomy.context_terms for taxonomy in GOAL_TAXONOMY.values())
    assert all(all(acquisition and exit_term for acquisition, exit_term in pairs) for pairs in OPPOSITE_TERMS.values())


def test_context_disambiguates_generic_actions_and_newsletter_subscription() -> None:
    disable = _control("disable", "Disable", "/preferences/notifications/disable")
    disable_candidates = classify_control(disable, "Email notification settings")

    assert disable_candidates[0].family == "notifications_enable_disable"
    assert disable_candidates[0].phase == "exit"
    assert disable_candidates[0].contextual is True

    subscribe = _control("subscribe", "Subscribe")
    subscribe_candidates = classify_control(subscribe, "Newsletter and marketing email preferences")

    assert subscribe_candidates[0].family == "newsletter_subscribe_unsubscribe"
    assert subscribe_candidates[0].phase == "acquisition"
    assert not any(candidate.family == "subscribe_cancel" for candidate in subscribe_candidates)


def test_ranking_and_pairing_are_deterministic_and_object_aware() -> None:
    controls = [
        _control("connect-slack", "Connect Slack", "/settings/integrations/slack/connect", 3),
        _control("disconnect-teams", "Disconnect Teams", "/settings/integrations/teams/disconnect", 4),
        _control("disconnect-slack", "Disconnect Slack", "/settings/integrations/slack/disconnect", 5),
        _control("connect-teams", "Connect Teams", "/settings/integrations/teams/connect", 6),
    ]
    first = rank_intent_candidates(controls, ["Connected apps", "Integrations"])
    second = rank_intent_candidates(list(reversed(controls)), ["Connected apps", "Integrations"])

    assert [
        (candidate.control.control_id, candidate.family, candidate.phase, candidate.score)
        for candidate in first
    ] == [
        (candidate.control.control_id, candidate.family, candidate.phase, candidate.score)
        for candidate in second
    ]
    assert {candidate.object_tokens for candidate in first} == {("slack",), ("teams",)}

    pairs = pair_goal_candidates(first)

    assert {pair.signature for pair in pairs} == {
        "integration_connect_disconnect:slack",
        "integration_connect_disconnect:teams",
    }
    assert all(
        pair.acquisition.object_tokens == pair.exit.object_tokens
        for pair in pairs
    )
    assert [pair.confidence for pair in pairs] == sorted(
        (pair.confidence for pair in pairs), reverse=True
    )


def test_family_only_account_actions_can_pair_without_object_tokens() -> None:
    candidates = rank_intent_candidates(
        [
            _control("create", "Create account", "/register", 1),
            _control("delete", "Delete account", "/settings/account/delete", 2),
        ],
        "Account settings",
        ["account_create_delete"],
    )

    pairs = pair_goal_candidates(candidates)

    assert len(pairs) == 1
    assert pairs[0].signature == "account_create_delete:default"
    assert pairs[0].object_tokens == ()


@pytest.mark.parametrize(
    "element_id",
    [
        "550e8400-e29b-41d4-a716-446655440000",
        ":r1a:",
        "ember123",
        "react-select-3-input",
        "radix-:r0:",
        "headlessui-menu-button-:r1:",
        "submit-1712345678901",
        "field-a18f0c932b7d4e11",
    ],
)
def test_dynamic_ids_are_rejected(element_id: str) -> None:
    assert is_dynamic_id(element_id)


def test_selector_bundle_has_resilient_priority_and_omits_dynamic_id() -> None:
    bundle = build_selector_bundle(
        role="textbox",
        accessible_name="Email address",
        label="Email address",
        attributes={"data-testid": "account-email", "name": "email"},
        element_id="ember123",
        name="email",
        css="form > input:nth-of-type(1)",
    )

    assert [strategy.kind for strategy in bundle] == [
        "role",
        "label",
        "data_attribute",
        "name",
        "css",
    ]
    assert bundle[2].value == '[data-testid="account-email"]'
    assert bundle[-1].stable is False
    assert not any(strategy.kind == "id" for strategy in bundle)

    stable_id_bundle = build_selector_bundle(
        role="button",
        accessible_name="Save settings",
        element_id="save-settings",
        name="save",
        css="button.primary",
    )
    assert [strategy.kind for strategy in stable_id_bundle] == ["role", "id", "name", "css"]
    assert stable_id_bundle[1].value == "save-settings"

    observed_control_bundle = build_selector_bundle({"role": "button", "name": "Delete account"})
    assert observed_control_bundle[0].kind == "role"
    assert observed_control_bundle[0].accessible_name == "Delete account"


class _FakeLocator:
    def __init__(self, key: str, count: int, visible_indexes: set[int] | None = None, index: int | None = None):
        self.key = key
        self._count = count
        self._visible_indexes = visible_indexes or set()
        self.index = index

    @property
    def first(self) -> "_FakeLocator":
        return self.nth(0)

    def nth(self, index: int) -> "_FakeLocator":
        return _FakeLocator(self.key, self._count, self._visible_indexes, index)

    async def count(self) -> int:
        return self._count

    async def is_visible(self, timeout: int = 0) -> bool:
        del timeout
        assert self.index is not None
        return self.index in self._visible_indexes


class _FakePage:
    def __init__(self):
        self.calls: list[str] = []

    def get_by_role(self, role: str, *, name: str, exact: bool) -> _FakeLocator:
        assert exact is True
        key = f"role:{role}:{name}"
        self.calls.append(key)
        return _FakeLocator(key, 0)

    def get_by_label(self, label: str, *, exact: bool) -> _FakeLocator:
        assert exact is True
        key = f"label:{label}"
        self.calls.append(key)
        return _FakeLocator(key, 2, {1})

    def locator(self, selector: str) -> _FakeLocator:
        key = f"css:{selector}"
        self.calls.append(key)
        return _FakeLocator(key, 1, {0})


@pytest.mark.asyncio
async def test_selector_resolution_reorders_fallbacks_and_returns_visible_locator() -> None:
    page = _FakePage()
    strategies = [
        SelectorStrategy(kind="css", value="button.save", stable=False),
        SelectorStrategy(kind="label", value="Save settings"),
        SelectorStrategy(
            kind="role",
            value="Save settings",
            role="button",
            accessible_name="Save settings",
        ),
        SelectorStrategy(kind="id", value="ember999"),
    ]

    resolved = await resolve_selector(page, strategies)  # type: ignore[arg-type]

    assert resolved is not None
    locator, strategy = resolved
    assert strategy.kind == "label"
    assert locator.index == 1
    assert page.calls == ["role:button:Save settings", "label:Save settings"]

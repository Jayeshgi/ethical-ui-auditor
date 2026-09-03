from __future__ import annotations

import pytest

from app.flow_analysis.autonomous import AutonomousFlowError, _approved_origins
from app.flow_analysis.autonomous_schemas import AutonomousFlowRequest, ObservedControl
from app.flow_analysis.engine import CONTROLLED_ORIGINS
from app.flow_analysis.risk import action_allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
async def test_dealcart_origin_is_explicitly_available_in_controlled_mode(host: str) -> None:
    origin = f"http://{host}:3000"
    request = AutonomousFlowRequest(
        url=f"{origin}/flows/account?variant=manipulative",
        mode="controlled",
        goal_families=["account_create_delete"],
        analyse_models=False,
    )

    assert origin in CONTROLLED_ORIGINS
    assert await _approved_origins(request) == {origin}


@pytest.mark.asyncio
async def test_unapproved_loopback_port_remains_blocked_in_controlled_mode() -> None:
    request = AutonomousFlowRequest(
        url="http://127.0.0.1:3999/manipulative",
        mode="controlled",
        analyse_models=False,
    )

    with pytest.raises(AutonomousFlowError, match="restricted to test origins"):
        await _approved_origins(request)


@pytest.mark.asyncio
async def test_dealcart_loopback_is_not_mistaken_for_a_public_evidence_only_target() -> None:
    request = AutonomousFlowRequest(
        url="http://127.0.0.1:3000/manipulative",
        mode="evidence_only",
        analyse_models=False,
    )

    with pytest.raises(Exception, match="Private, local, reserved, and loopback"):
        await _approved_origins(request)


def test_destructive_dealcart_action_requires_its_exact_controlled_origin() -> None:
    control = ObservedControl(
        control_id="delete-account",
        role="button",
        name="Delete account",
        input_type="submit",
        form_method="POST",
    )

    assert action_allowed(
        control,
        "controlled",
        "http://127.0.0.1:3000/flows/account",
        ["http://127.0.0.1:3000"],
    ).allowed
    assert not action_allowed(
        control,
        "controlled",
        "http://127.0.0.1:3999/flows/account",
        ["http://127.0.0.1:3000"],
    ).allowed

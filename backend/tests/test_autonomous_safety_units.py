from __future__ import annotations

import pytest

from app.flow_analysis.autonomous_schemas import ObservedControl
from app.flow_analysis.limitations import (
    PageObservation,
    detect_limitations,
    is_mechanism_eligible,
)
from app.flow_analysis.risk import (
    action_allowed,
    classify_action_risk,
    is_action_allowed,
    request_method_allowed,
)


def _control(
    name: str,
    *,
    role: str = "button",
    href: str | None = None,
    input_type: str | None = None,
    form_method: str | None = None,
) -> ObservedControl:
    return ObservedControl(
        control_id=f"control-{name}",
        role=role,
        name=name,
        href=href,
        input_type=input_type,
        form_method=form_method,
    )


@pytest.mark.parametrize(
    ("control", "expected"),
    [
        (_control("Read documentation", role="link", href="/docs"), "read_only"),
        (_control("Open menu"), "reversible"),
        (_control("Cancel"), "reversible"),
        (_control("Sign in", input_type="submit", form_method="post"), "authentication"),
        (_control("Create account", input_type="submit", form_method="post"), "mutating"),
        (_control("Buy now", input_type="submit", form_method="post"), "financial"),
        (_control("Delete my account", input_type="submit", form_method="post"), "destructive"),
        (_control("How to delete your account", role="link", href="/help/delete-account"), "read_only"),
        (_control("Continue", input_type="submit", form_method="post"), "mutating"),
        (_control("Contact by phone", role="link", href="tel:+15550100"), "mutating"),
        (_control("Search", input_type="submit", form_method="get"), "read_only"),
    ],
)
def test_action_risk_classification_is_deterministic(control: ObservedControl, expected: str) -> None:
    assert classify_action_risk(control) == expected
    assert classify_action_risk(control.model_dump()) == expected


def test_filling_a_field_is_reversible_even_when_its_form_posts() -> None:
    field = _control("Email address", role="textbox", input_type="email", form_method="POST")

    assert classify_action_risk(field) == "reversible"
    assert action_allowed(field, "evidence_only", "https://example.test").allowed is True


@pytest.mark.parametrize(
    "name",
    ["Create account", "Accept consent", "Buy now", "Cancel subscription", "Delete account"],
)
def test_evidence_only_blocks_semantic_commits(name: str) -> None:
    control = _control(name, input_type="submit", form_method="POST")
    decision = action_allowed(control, "evidence_only", "https://example.test")

    assert decision.allowed is False
    assert bool(decision) is False
    assert "Evidence-only" in decision.reason
    assert is_action_allowed(control, "evidence_only", "https://example.test") is False


def test_evidence_only_allows_explicit_login_post_but_not_other_posts() -> None:
    login = _control("Sign in", input_type="submit", form_method="POST")
    generic = _control("Continue", input_type="submit", form_method="POST")

    assert action_allowed(login, "evidence_only", "https://example.test").allowed is True
    assert action_allowed(generic, "evidence_only", "https://example.test").allowed is False


def test_controlled_mode_requires_exact_approved_current_and_destination_origins() -> None:
    destructive = _control(
        "Delete account",
        href="https://sandbox.example.test/account/delete",
        input_type="submit",
        form_method="DELETE",
    )
    approved = ["https://sandbox.example.test/"]

    assert action_allowed(destructive, "controlled", "https://sandbox.example.test/settings", approved).allowed
    assert not action_allowed(destructive, "controlled", "https://evil-sandbox.example.test", approved).allowed

    cross_origin = destructive.model_copy(update={"href": "https://payments.example.test/delete"})
    assert not action_allowed(cross_origin, "controlled", "https://sandbox.example.test", approved).allowed


def test_controlled_mode_rejects_native_protocols() -> None:
    native = _control("Continue in app", role="link", href="intent://settings")

    decision = action_allowed(native, "controlled", "https://sandbox.example.test", ["https://sandbox.example.test"])

    assert decision.allowed is False
    assert "external protocols" in decision.reason


@pytest.mark.parametrize(
    ("method", "mode", "is_login", "expected"),
    [
        (None, "evidence_only", False, True),
        ("get", "evidence_only", False, True),
        ("HEAD", "evidence_only", False, True),
        ("POST", "evidence_only", False, False),
        ("POST", "evidence_only", True, True),
        ("DELETE", "evidence_only", True, False),
        ("PATCH", "controlled", False, True),
        ("TRACE", "controlled", False, False),
    ],
)
def test_request_method_guard(method: str | None, mode: str, is_login: bool, expected: bool) -> None:
    assert request_method_allowed(method, mode, is_login=is_login) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Please complete the CAPTCHA to continue.", "captcha_required"),
        ("Two-factor authentication: enter the code from your authenticator app.", "mfa_required"),
        ("Please verify your email address. Check your inbox to continue.", "email_verification_required"),
        ("Login is required to access account settings.", "credentials_required"),
        ("Payment is required before you can continue.", "payment_required"),
        ("Continue with Google", "external_identity_provider"),
        ("Checking your browser before accessing this site.", "bot_protection"),
        ("Too many requests. Please wait before retrying.", "rate_limited"),
        ("To cancel your subscription, call support.", "channel_switch"),
        ("You must use our mobile app to continue.", "native_app_required"),
    ],
)
def test_detects_high_signal_execution_limitations(text: str, expected: str) -> None:
    limitations = detect_limitations(text, phase="exit")

    assert expected in {limitation.code for limitation in limitations}
    assert all(limitation.phase == "exit" for limitation in limitations)
    assert all("not a dark-pattern" in limitation.message or "not a finding" in limitation.message for limitation in limitations)


def test_detects_dom_markers_without_treating_script_mentions_as_visible_text() -> None:
    captcha = detect_limitations(html='<main><div class="g-recaptcha" data-sitekey="public"></div></main>')
    benign_script = detect_limitations(html="<script>documentation mentions captcha and too many requests</script><p>Welcome</p>")

    assert [limitation.code for limitation in captcha] == ["captcha_required"]
    assert benign_script == []


def test_credentials_are_only_requested_when_the_run_does_not_have_them() -> None:
    text = "Please sign in to continue to account settings."

    assert "credentials_required" in {item.code for item in detect_limitations(text, has_credentials=False)}
    assert "credentials_required" not in {item.code for item in detect_limitations(text, has_credentials=True)}


def test_authentication_failure_is_reported_even_when_credentials_were_supplied() -> None:
    limitations = detect_limitations("Incorrect password. Unable to sign in.", has_credentials=True)

    assert [limitation.code for limitation in limitations] == ["authentication_failed"]


def test_observation_object_and_http_status_are_supported() -> None:
    observation = PageObservation(
        text="Request capacity has been reached.",
        url="https://example.test/settings?access_token=secret",
        status_code=429,
    )

    limitations = detect_limitations(observation)

    assert [limitation.code for limitation in limitations] == ["rate_limited"]
    assert "secret" not in " ".join(limitations[0].evidence)


def test_external_identity_provider_is_detected_from_url_without_query_secrets() -> None:
    limitations = detect_limitations(url="https://accounts.google.com/o/oauth2/auth?code=secret")

    assert [limitation.code for limitation in limitations] == ["external_identity_provider"]
    assert "secret" not in " ".join(limitations[0].evidence)


def test_benign_footer_contacts_and_app_promotion_are_not_blockers() -> None:
    text = "Contact us by phone. Download our app for a better experience. We accept major cards."

    assert detect_limitations(text) == []


def test_only_channel_switch_can_be_considered_by_later_mechanism_scoring() -> None:
    channel, captcha = detect_limitations("To unsubscribe, call support. Please complete the CAPTCHA.")

    assert channel.code == "captcha_required"
    assert captcha.code == "channel_switch"
    assert is_mechanism_eligible(channel) is False
    assert is_mechanism_eligible(captcha) is True

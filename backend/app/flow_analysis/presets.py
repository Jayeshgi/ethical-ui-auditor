from __future__ import annotations

from app.flow_analysis.schemas import FlowActionSpec, FlowDefinitionSpec, FlowPairRequest


def automation_exercise_account_lifecycle() -> FlowPairRequest:
    """Published public automation exercise: create and delete a disposable account."""
    acquisition_actions = [
        FlowActionSpec(action="click", selector='a[href="/login"]', description="Open signup and login"),
        FlowActionSpec(action="fill", selector='input[data-qa="signup-name"]', value="{{unique_name}}", description="Enter signup name"),
        FlowActionSpec(action="fill", selector='input[data-qa="signup-email"]', value="{{unique_email}}", description="Enter disposable signup email"),
        FlowActionSpec(action="click", selector='button[data-qa="signup-button"]', description="Continue signup"),
        FlowActionSpec(action="check", selector="#id_gender1", description="Select title"),
        FlowActionSpec(action="fill", selector='input[data-qa="password"]', value="{{test_password}}", description="Enter disposable password"),
        FlowActionSpec(action="select", selector="#days", value="1", description="Select birth day"),
        FlowActionSpec(action="select", selector="#months", value="1", description="Select birth month"),
        FlowActionSpec(action="select", selector="#years", value="1995", description="Select birth year"),
        FlowActionSpec(action="fill", selector='input[data-qa="first_name"]', value="Ethical", description="Enter first name"),
        FlowActionSpec(action="fill", selector='input[data-qa="last_name"]', value="Auditor", description="Enter last name"),
        FlowActionSpec(action="fill", selector='input[data-qa="address"]', value="1 Test Street", description="Enter test address"),
        FlowActionSpec(action="select", selector='select[data-qa="country"]', value="India", description="Select country"),
        FlowActionSpec(action="fill", selector='input[data-qa="state"]', value="Delhi", description="Enter state"),
        FlowActionSpec(action="fill", selector='input[data-qa="city"]', value="New Delhi", description="Enter city"),
        FlowActionSpec(action="fill", selector='input[data-qa="zipcode"]', value="110001", description="Enter postal code"),
        FlowActionSpec(action="fill", selector='input[data-qa="mobile_number"]', value="9999999999", description="Enter test phone"),
        FlowActionSpec(action="click", selector='button[data-qa="create-account"]', description="Create disposable test account", commit=True),
        FlowActionSpec(action="assert_text", value="ACCOUNT CREATED!", description="Verify account creation"),
        FlowActionSpec(action="click", selector='a[data-qa="continue-button"]', description="Continue to signed-in site"),
        FlowActionSpec(action="assert_text", value="Logged in as", description="Verify signed-in state"),
    ]
    exit_actions = [
        FlowActionSpec(action="click", selector='a[href="/delete_account"]', description="Delete disposable account", commit=True),
        FlowActionSpec(action="assert_text", value="ACCOUNT DELETED!", description="Verify account deletion"),
        FlowActionSpec(action="click", selector='a[data-qa="continue-button"]', description="Continue after deletion"),
    ]
    cleanup = [
        FlowActionSpec(action="goto", value="https://automationexercise.com/delete_account", description="Open cleanup deletion endpoint"),
        FlowActionSpec(action="click", selector='a[data-qa="continue-button"]', description="Finish cleanup", timeout_ms=5_000),
    ]
    return FlowPairRequest(
        name="Automation Exercise account creation versus deletion",
        source="automation_exercise",
        mode="controlled",
        acquisition=FlowDefinitionSpec(
            name="Create account",
            goal="Create a disposable e-commerce account",
            start_url="https://automationexercise.com",
            actions=acquisition_actions,
        ),
        exit=FlowDefinitionSpec(
            name="Delete account",
            goal="Permanently delete the same disposable account",
            actions=exit_actions,
        ),
        cleanup_actions=cleanup,
        allowed_origins=["https://automationexercise.com"],
        analyse_models=True,
    )


def local_benchmark(variant: str) -> FlowPairRequest:
    if variant not in {"fair", "obstructed"}:
        raise ValueError("variant must be fair or obstructed")
    base = f"http://127.0.0.1:8000/benchmarks/{variant}"
    acquisition = FlowDefinitionSpec(
        name="Create account",
        goal="Create an account",
        start_url=base,
        actions=[
            FlowActionSpec(action="click", selector='[data-flow="create"]', description="Create account"),
            FlowActionSpec(action="assert_text", value="Account ready", description="Verify account creation"),
        ],
    )
    if variant == "fair":
        exit_actions = [
            FlowActionSpec(action="click", selector='[data-flow="delete"]', description="Delete account"),
            FlowActionSpec(action="assert_text", value="Account deleted", description="Verify account deletion"),
        ]
    else:
        exit_actions = [
            FlowActionSpec(action="click", selector='[data-flow="settings"]', description="Open settings"),
            FlowActionSpec(action="click", selector='[data-flow="account"]', description="Open account controls"),
            FlowActionSpec(action="click", selector='[data-flow="delete"]', description="Find account deletion"),
            FlowActionSpec(action="fill", selector='[data-flow="reason"]', value="Testing user autonomy", description="Complete mandatory reason for leaving"),
            FlowActionSpec(action="click", selector='[data-flow="reason-next"]', description="Submit reason"),
            FlowActionSpec(action="click", selector='[data-flow="reject-offer"]', description="Reject retention offer"),
            FlowActionSpec(action="click", selector='[data-flow="confirm-one"]', description="Confirm deletion once"),
            FlowActionSpec(action="click", selector='[data-flow="confirm-two"]', description="Confirm deletion again"),
            FlowActionSpec(action="assert_text", value="Account deleted", description="Verify account deletion"),
        ]
    return FlowPairRequest(
        name=f"Local {variant} account lifecycle benchmark",
        source="local_benchmark",
        mode="controlled",
        acquisition=acquisition,
        exit=FlowDefinitionSpec(name="Delete account", goal="Delete the same account", actions=exit_actions),
        allowed_origins=["http://127.0.0.1:8000"],
        analyse_models=True,
    )

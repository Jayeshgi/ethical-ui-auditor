"""End-to-end Playwright smoke test for the local DealCart research benchmark."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEALCART_ROOT = PROJECT_ROOT / "benchmarks" / "dealcart"
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(PROJECT_ROOT / ".playwright-browsers"))

from playwright.async_api import Page, async_playwright
FLOW_CONTROLS = {
    "account": ("Create account", "Delete account"),
    "subscription": ("Subscribe", "Cancel subscription"),
    "newsletter": ("Join newsletter", "Unsubscribe"),
    "consent": ("Accept consent", "Withdraw consent"),
    "notifications": ("Enable notifications", "Disable notifications"),
    "integration": ("Connect integration", "Disconnect integration"),
    "payment-method": ("Add payment method", "Remove payment method"),
    "loyalty": ("Join rewards", "Leave rewards"),
    "data-sharing": ("Enable data sharing", "Revoke data sharing"),
    "purchase-return": ("Buy now", "Start return"),
}
SCENARIOS = (
    "genuine-countdown",
    "fake-countdown",
    "session-deadline",
    "scarcity",
    "social-proof",
    "preselection",
    "hidden-rejection",
    "silent-cart-addition",
    "late-price",
    "nagging",
    "misleading-action",
    "subscription-disclosure",
)
OBSTRUCTIONS = (
    "channel-switch",
    "forced-contact",
    "delayed-execution",
    "redirect-loop-a",
    "dead-end",
    "form-burden",
    "information-overload",
    "policy-mismatch",
)
LIMITATIONS = (
    "captcha",
    "mfa",
    "email-verification",
    "payment-required",
    "external-idp",
    "bot-protection",
    "rate-limited",
    "native-app",
)


def _healthy(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/api/health", timeout=1) as response:
            return response.status == 200 and json.load(response).get("status") == "ok"
    except (OSError, urllib.error.URLError, ValueError):
        return False


def _wait_for_server(base_url: str, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _healthy(base_url):
            return
        time.sleep(0.2)
    raise RuntimeError(f"DealCart did not become healthy at {base_url}")


def _timer_seconds(value: str) -> int:
    parts = [int(part) for part in value.split(":")]
    return parts[-1] + parts[-2] * 60 + (parts[-3] * 3600 if len(parts) == 3 else 0)


async def _reset(page: Page, base_url: str) -> None:
    response = await page.request.post(f"{base_url}/api/benchmark/reset", data={})
    assert response.ok, "Benchmark reset failed"


async def _test_flow(page: Page, base_url: str, slug: str, fair: bool) -> None:
    acquire, exit_label = FLOW_CONTROLS[slug]
    await _reset(page, base_url)
    suffix = "?variant=fair" if fair else ""
    await page.goto(f"{base_url}/flows/{slug}{suffix}")
    await page.get_by_role("button", name=acquire, exact=True).click()
    await page.wait_for_selector("[data-testid='acquisition-terminal']")
    if not fair:
        final_progress_step = 6 if slug in {"account", "subscription"} else 3
        for step in range(1, final_progress_step + 1):
            await page.locator(
                f"[data-action='flow-progress'][data-step='{step}']"
            ).click()
    await page.get_by_role("button", name=exit_label, exact=False).click()
    await page.wait_for_selector("[data-testid='exit-terminal']")


async def run_browser_suite(base_url: str) -> dict[str, int]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(f"{base_url}/manipulative")
        await page.wait_for_selector("[data-testid='fake-timer-region']")
        for selector in ("#care-plan-choice", "#marketing-choice", "#sharing-choice"):
            assert await page.locator(selector).is_checked(), f"{selector} should be preselected"
        assert "₹" in await page.locator("#app").inner_text(), "UTF-8 currency text is corrupted"
        initial = _timer_seconds(await page.locator("[data-countdown='fake']").inner_text())
        await page.wait_for_timeout(2200)
        before_reload = _timer_seconds(await page.locator("[data-countdown='fake']").inner_text())
        await page.reload()
        after_reload = _timer_seconds(await page.locator("[data-countdown='fake']").inner_text())
        assert before_reload < initial and after_reload > before_reload, "Fake timer did not reset on reload"

        await _reset(page, base_url)
        await page.goto(f"{base_url}/scenarios/silent-cart-addition")
        await page.locator("[data-action='add-cart']").click()
        await page.wait_for_selector("[data-testid='cart-item-care-plan']")

        await _reset(page, base_url)
        await page.goto(f"{base_url}/fair")
        for selector in ("#care-plan-choice", "#marketing-choice", "#sharing-choice"):
            assert not await page.locator(selector).is_checked(), f"{selector} should be opt-in in the fair control"
        assert await page.get_by_role("button", name="Reject optional cookies").is_visible()
        await page.get_by_role("button", name="Add to Cart").first.click()
        await page.goto(f"{base_url}/cart?variant=fair")
        assert await page.locator("[data-testid='cart-item-care-plan']").count() == 0

        for slug in FLOW_CONTROLS:
            await _test_flow(page, base_url, slug, fair=True)
            await _test_flow(page, base_url, slug, fair=False)

        for slug in SCENARIOS:
            await page.goto(f"{base_url}/scenarios/{slug}")
            await page.wait_for_selector("main h1")

        await page.goto(f"{base_url}/scenarios/late-price")
        assert await page.locator(".late-fee").count() == 0
        await page.locator("[data-action='checkout-step']").click()
        await page.wait_for_selector(".late-fee")
        assert await page.locator(".late-fee").count() == 3

        await page.goto(f"{base_url}/scenarios/nagging")
        await page.wait_for_selector("[role='dialog']")
        await page.locator("[data-action='dismiss-nag']").click()
        await page.wait_for_selector("[role='dialog']", state="detached")
        await page.wait_for_selector("[role='dialog']", timeout=4_000)

        for slug in OBSTRUCTIONS:
            await page.goto(f"{base_url}/flows/obstructions/{slug}")
            await page.wait_for_selector("main h1")
        for slug in LIMITATIONS:
            await page.goto(f"{base_url}/limitations/{slug}")
            await page.get_by_text("This page intentionally stops automation", exact=False).wait_for()
            page_text = await page.locator("#app").inner_text()
            assert "synthetic execution boundary" in page_text.lower(), (slug, page_text)

        first = await (await page.request.get(f"{base_url}/api/benchmark/genuine-deadline")).json()
        second = await (await page.request.get(f"{base_url}/api/benchmark/genuine-deadline")).json()
        assert first["deadline"] == second["deadline"], "Genuine deadline changed between requests"

        await browser.close()
        return {
            "paired_flow_variants": len(FLOW_CONTROLS) * 2,
            "runtime_scenarios": len(SCENARIOS),
            "obstruction_pages": len(OBSTRUCTIONS),
            "limitation_pages": len(LIMITATIONS),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--no-start", action="store_true", help="Require an already-running DealCart server")
    args = parser.parse_args()
    process: subprocess.Popen | None = None
    try:
        if not _healthy(args.base_url):
            if args.no_start:
                raise RuntimeError(f"DealCart is not running at {args.base_url}")
            process = subprocess.Popen(
                ["node", "server.js"],
                cwd=DEALCART_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            _wait_for_server(args.base_url)
        counts = asyncio.run(run_browser_suite(args.base_url.rstrip("/")))
        print("DealCart Playwright smoke test passed:", json.dumps(counts, sort_keys=True))
        return 0
    except Exception as error:
        print(f"DealCart Playwright smoke test failed: {error}", file=sys.stderr)
        traceback.print_exc()
        return 1
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())

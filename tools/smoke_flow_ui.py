from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core.config import RUNTIME_DATA_DIR, configure_runtime_environment  # noqa: E402


def main() -> None:
    email = os.getenv("FLOW_DEMO_EMAIL", "flow-demo-20260814@example.com")
    password = os.getenv("FLOW_DEMO_PASSWORD")
    if not password:
        raise SystemExit("FLOW_DEMO_PASSWORD is required")
    configure_runtime_environment()
    console_errors: list[str] = []
    screenshot = RUNTIME_DATA_DIR / "autonomous-flow-dashboard-smoke.png"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.goto("http://127.0.0.1:8000/flow-analysis", wait_until="networkidle")
        page.locator("#email").fill(email)
        page.locator("#password").fill(password)
        page.get_by_role("button", name="Sign in").click()
        page.locator("#workspace:not(.hidden)").wait_for()
        page.locator("#historyList .history-row").first.wait_for()
        page.locator("#historyList .history-row").filter(
            has_text="benchmarks/obstructed"
        ).first.get_by_role("button", name="Open").click()
        page.locator("#resultPanel:not(.hidden)").wait_for()
        page.get_by_text("Exploration state graph", exact=True).wait_for()
        page.locator("#goals .goal").first.wait_for()
        page.locator("#resultPanel img.evidence-shot").first.wait_for(state="visible")
        page.screenshot(path=str(screenshot), full_page=True)
        browser.close()

    if console_errors:
        raise RuntimeError(f"Dashboard console errors: {console_errors}")
    print(json.dumps({"status": "passed", "screenshot": str(screenshot)}))


if __name__ == "__main__":
    main()

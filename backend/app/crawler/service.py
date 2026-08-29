from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

from playwright.async_api import BrowserContext, Page, async_playwright

from app.core.config import MAX_SCREENSHOT_BYTES, MAX_SCREENSHOT_HEIGHT, RUNTIME_DATA_DIR, configure_runtime_environment
from app.core.security import validate_public_http_url
from app.frontend_analysis.engine import analyze_frontend_behavior


DOM_EXTRACTION_SCRIPT = """
() => {
  const visible = (element) => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' &&
      Number(style.opacity || '1') > 0 && rect.width > 0 && rect.height > 0;
  };
  const selectorFor = (element) => {
    if (element.id) return `#${CSS.escape(element.id)}`;
    const tag = element.tagName.toLowerCase();
    const parent = element.parentElement;
    if (!parent) return tag;
    const siblings = [...parent.children].filter(child => child.tagName === element.tagName);
    return siblings.length === 1 ? tag : `${tag}:nth-of-type(${siblings.indexOf(element) + 1})`;
  };
  const candidates = [...document.querySelectorAll('button,a,label,p,h1,h2,h3,h4,span,li,option,[role="button"],[role="dialog"]')];
  return candidates.flatMap((element) => {
    if (!visible(element)) return [];
    const text = (element.innerText || element.textContent || '').replace(/\\s+/g, ' ').trim();
    if (!text || text.length > 500) return [];
    const childHasSameText = [...element.querySelectorAll('button,a,label,p,h1,h2,h3,h4,span,li,option,[role="button"],[role="dialog"]')]
      .some((child) => visible(child) && (child.innerText || child.textContent || '').replace(/\\s+/g, ' ').trim() === text);
    if (childHasSameText) return [];
    const rect = element.getBoundingClientRect();
    return [{ text, selector: selectorFor(element), bounding_box: { x: rect.x, y: rect.y + window.scrollY, width: rect.width, height: rect.height } }];
  }).slice(0, 500);
}
"""


async def _same_origin_links(page: Page, origin: str) -> list[str]:
    links = await page.eval_on_selector_all("a[href]", "elements => elements.map(a => a.href)")
    result: list[str] = []
    for link in links:
        cleaned, _ = urldefrag(link)
        parsed = urlparse(cleaned)
        if parsed.scheme in {"http", "https"} and f"{parsed.scheme}://{parsed.netloc}" == origin:
            result.append(cleaned)
    return list(dict.fromkeys(result))


async def _capture_page(page: Page, destination: Path, scroll_steps: int) -> dict:
    for _ in range(scroll_steps):
        await page.mouse.wheel(0, 900)
        await page.wait_for_timeout(300)
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(200)
    dimensions = await page.evaluate(
        "() => ({ width: Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0), "
        "height: Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0) })"
    )
    screenshot_truncated = int(dimensions["height"]) > MAX_SCREENSHOT_HEIGHT
    if screenshot_truncated:
        await page.screenshot(
            path=str(destination),
            clip={"x": 0, "y": 0, "width": min(float(dimensions["width"]), 1440), "height": float(MAX_SCREENSHOT_HEIGHT)},
        )
    else:
        await page.screenshot(path=str(destination), full_page=True)
    if destination.stat().st_size > MAX_SCREENSHOT_BYTES:
        raise ValueError(f"Screenshot exceeds the {MAX_SCREENSHOT_BYTES}-byte safety limit.")
    return {
        "url": page.url,
        "title": await page.title(),
        "dom_blocks": await page.evaluate(DOM_EXTRACTION_SCRIPT),
        "screenshot_truncated": screenshot_truncated,
    }


async def capture_website(
    url: str,
    max_pages: int,
    scroll_steps: int,
    analyse_behavior: bool = True,
    behavior_observation_seconds: int = 30,
) -> tuple[str, list[dict], list[str]]:
    """Capture a small, same-origin, read-only set of page states."""
    configure_runtime_environment()
    target_url = validate_public_http_url(url)
    target_origin = f"{urlparse(target_url).scheme}://{urlparse(target_url).netloc}"
    scan_id = f"scan-{uuid.uuid4().hex[:12]}"
    scan_dir = RUNTIME_DATA_DIR / "scans" / scan_id / "screenshots"
    scan_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    captures: list[dict] = []
    queue = [target_url]
    visited: set[str] = set()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        public_hosts: dict[str, bool] = {}

        async def enforce_network_policy(route):
            request = route.request
            parsed = urlparse(request.url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                await route.abort()
                return
            if request.is_navigation_request() and f"{parsed.scheme}://{parsed.netloc}" != target_origin:
                await route.abort()
                return
            hostname = parsed.hostname.rstrip(".").lower()
            if hostname not in public_hosts:
                try:
                    await asyncio.to_thread(validate_public_http_url, request.url)
                    public_hosts[hostname] = True
                except Exception:
                    public_hosts[hostname] = False
            if not public_hosts[hostname]:
                await route.abort()
                return
            await route.continue_()

        async def create_context() -> BrowserContext:
            safe_context: BrowserContext = await browser.new_context(
                viewport={"width": 1440, "height": 1000},
                user_agent="EthicalUIAuditor/0.2 (read-only behavioural scan)",
                accept_downloads=False,
                service_workers="block",
                permissions=[],
            )
            await safe_context.route("**/*", enforce_network_policy)
            return safe_context

        behavior_report = None
        if analyse_behavior:
            behavior_report = await analyze_frontend_behavior(
                browser,
                target_url,
                create_context,
                scan_dir,
                observation_seconds=behavior_observation_seconds,
                analyse_models=False,
            )
            warnings.extend(behavior_report.warnings)

        context = await create_context()
        page = await context.new_page()
        try:
            while queue and len(captures) < max_pages:
                candidate = queue.pop(0)
                if candidate in visited:
                    continue
                visited.add(candidate)
                try:
                    await asyncio.to_thread(validate_public_http_url, candidate)
                    await page.goto(candidate, wait_until="domcontentloaded", timeout=30_000)
                    await page.wait_for_timeout(700)
                    screenshot = scan_dir / f"page-{len(captures) + 1:03d}.png"
                    captured = await _capture_page(page, screenshot, scroll_steps)
                    if captured.pop("screenshot_truncated"):
                        warnings.append(f"Screenshot for {captured['url']} was truncated to {MAX_SCREENSHOT_HEIGHT} pixels.")
                    captured["screenshot_path"] = str(screenshot.relative_to(RUNTIME_DATA_DIR.parent))
                    if not captures and behavior_report is not None:
                        captured["frontend_behavior"] = behavior_report
                    captures.append(captured)
                    for link in await _same_origin_links(page, target_origin):
                        if link not in visited and link not in queue:
                            queue.append(link)
                except Exception as error:  # A partial scan is still useful to a developer.
                    warnings.append(f"Could not capture {candidate}: {type(error).__name__}: {error}")
        finally:
            await context.close()
            await browser.close()
    return scan_id, captures, warnings

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from app.core.security import validate_public_http_url
from app.flow_analysis.schemas import FlowDiscoveryCandidate, FlowDiscoveryResponse


ACQUISITION_TERMS = ("sign up", "signup", "register", "subscribe", "join", "start trial", "create account")
EXIT_TERMS = ("cancel", "unsubscribe", "delete account", "close account", "leave", "remove account", "opt out")


async def discover_flow_candidates(url: str) -> FlowDiscoveryResponse:
    target = await asyncio.to_thread(validate_public_http_url, url)
    origin = f"{urlparse(target).scheme}://{urlparse(target).netloc}"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(service_workers="block", accept_downloads=False)

        async def network_policy(route):
            parsed = urlparse(route.request.url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                await route.abort()
                return
            if route.request.is_navigation_request() and f"{parsed.scheme}://{parsed.netloc}" != origin:
                await route.abort()
                return
            try:
                await asyncio.to_thread(validate_public_http_url, route.request.url)
            except Exception:
                await route.abort()
                return
            await route.continue_()

        await context.route("**/*", network_policy)
        page = await context.new_page()
        try:
            await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
            raw = await page.evaluate(
                r"""() => [...document.querySelectorAll('a,button,[role="button"]')].map((element, index) => ({
                  text: (element.innerText || element.textContent || '').replace(/\s+/g, ' ').trim(),
                  href: element.href || null,
                  selector: element.id ? `#${CSS.escape(element.id)}` : `${element.tagName.toLowerCase()}:nth-of-type(${index + 1})`
                })).filter(item => item.text).slice(0, 500)"""
            )
        finally:
            await context.close()
            await browser.close()

    candidates: list[FlowDiscoveryCandidate] = []
    for item in raw:
        normalized = item["text"].lower()
        for intent, terms in (("acquisition", ACQUISITION_TERMS), ("exit", EXIT_TERMS)):
            matches = [term for term in terms if term in normalized]
            if matches:
                exact = any(normalized == term for term in matches)
                candidates.append(
                    FlowDiscoveryCandidate(
                        intent=intent,
                        text=item["text"][:300],
                        selector=item["selector"],
                        href=item["href"],
                        confidence=0.9 if exact else 0.7,
                    )
                )
                break
    return FlowDiscoveryResponse(
        url=target,
        candidates=candidates,
        note="Heuristic suggestions only. A reviewer must confirm paired goals before execution.",
    )

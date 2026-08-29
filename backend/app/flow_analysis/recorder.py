from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import threading

from playwright.sync_api import sync_playwright

from app.core.config import RUNTIME_DATA_DIR, configure_runtime_environment


RECORDER_SCRIPT = r"""
(() => {
  if (window.__ethicalFlowRecorderInstalled) return;
  window.__ethicalFlowRecorderInstalled = true;
  const selectorFor = (element) => {
    if (element.id) return `#${CSS.escape(element.id)}`;
    for (const attribute of ['data-qa', 'data-testid', 'name']) {
      const value = element.getAttribute(attribute);
      if (value) return `${element.tagName.toLowerCase()}[${attribute}="${CSS.escape(value)}"]`;
    }
    const tag = element.tagName.toLowerCase();
    const parent = element.parentElement;
    if (!parent) return tag;
    const siblings = [...parent.children].filter(child => child.tagName === element.tagName);
    return siblings.length === 1 ? tag : `${tag}:nth-of-type(${siblings.indexOf(element) + 1})`;
  };
  document.addEventListener('click', event => {
    const target = event.target.closest('button,a,input,[role="button"]') || event.target;
    window.ethicalFlowRecord({action: 'click', selector: selectorFor(target), description: `Click ${(target.innerText || target.value || target.textContent || target.tagName).trim().slice(0, 120)}`});
  }, true);
  document.addEventListener('change', event => {
    const target = event.target;
    if (!target.matches('input,textarea,select')) return;
    const isSecret = target.type === 'password';
    const action = target.tagName === 'SELECT' ? 'select' : (target.type === 'checkbox' || target.type === 'radio') ? 'check' : 'fill';
    window.ethicalFlowRecord({
      action,
      selector: selectorFor(target),
      value: isSecret ? '{{secret}}' : (action === 'check' ? null : target.value),
      description: `${action} ${target.name || target.id || target.getAttribute('aria-label') || target.tagName}`
    });
  }, true);
})();
"""


def record_flow(start_url: str, output_path: Path | None = None) -> Path:
    """Open a headed browser and record manual interactions as declarative actions."""
    configure_runtime_environment()
    output_path = output_path or (
        RUNTIME_DATA_DIR / "flow_recordings" / f"recording-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    actions: list[dict] = []
    action_lock = threading.Lock()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})

        def receive_action(_source, payload) -> None:
            with action_lock:
                actions.append(dict(payload))

        context.expose_binding("ethicalFlowRecord", receive_action)
        context.add_init_script(RECORDER_SCRIPT)
        page = context.new_page()
        page.on(
            "framenavigated",
            lambda frame: actions.append(
                {"action": "goto", "value": frame.url, "description": f"Navigate to {frame.url}"}
            ) if frame == page.main_frame and frame.url != "about:blank" else None,
        )
        page.goto(start_url, wait_until="domcontentloaded")
        input("Perform the flow in Chromium, then press Enter here to stop recording... ")
        context.close()
        browser.close()

    output_path.write_text(json.dumps({"start_url": start_url, "actions": actions}, indent=2), encoding="utf-8")
    return output_path

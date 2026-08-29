from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

from playwright.async_api import Locator, Page

from app.core.config import RUNTIME_DATA_DIR
from app.flow_analysis.autonomous_schemas import GraphNode, GraphPhase, ObservedControl, TargetPresentation


CONTROL_SCRIPT = r"""() => {
  const visible = element => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return !!(rect.width && rect.height) && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const labelFor = element => {
    const ariaLabel = element.getAttribute('aria-label');
    if (ariaLabel) return ariaLabel;
    const labelledBy = element.getAttribute('aria-labelledby');
    if (labelledBy) {
      const resolved = labelledBy.split(/\s+/)
        .map(id => document.getElementById(id))
        .filter(Boolean)
        .map(label => label.innerText || label.textContent || '')
        .join(' ')
        .replace(/\s+/g, ' ')
        .trim();
      if (resolved) return resolved;
    }
    if (element.labels && element.labels.length) return [...element.labels].map(label => label.innerText).join(' ');
    return element.innerText || element.value || element.getAttribute('title') ||
      element.getAttribute('placeholder') || element.getAttribute('name') || '';
  };
  const roleFor = element => element.getAttribute('role') || ({
    A: 'link', BUTTON: 'button', SELECT: 'combobox', TEXTAREA: 'textbox'
  }[element.tagName] || (element.tagName === 'INPUT' ?
    (['submit','button','reset'].includes(element.type) ? 'button' :
     ['checkbox','radio'].includes(element.type) ? element.type : 'textbox') : 'control'));
  const heading = element => {
    const container = element.closest('form,section,dialog,main,article,div') || document.body;
    const value = container.querySelector('h1,h2,h3,legend');
    return value ? (value.innerText || '').replace(/\s+/g, ' ').trim() : '';
  };
  const cssFor = element => {
    const tag = element.tagName.toLowerCase();
    const parent = element.parentElement;
    if (!parent) return tag;
    const siblings = [...parent.children].filter(child => child.tagName === element.tagName);
    const localIndex = siblings.indexOf(element) + 1;
    return siblings.length === 1 ? tag : `${tag}:nth-of-type(${localIndex})`;
  };
  return [...document.querySelectorAll('a,button,input,textarea,select,[role="button"],[role="link"],summary')]
    .filter(element => visible(element))
    .slice(0, 500)
    .map((element, index) => {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      const attrs = {};
      for (const name of ['data-testid','data-test','data-qa','data-flow']) {
        const value = element.getAttribute(name);
        if (value) attrs[name] = value;
      }
      return {
        index,
        tag: element.tagName.toLowerCase(),
        role: roleFor(element),
        name: labelFor(element).replace(/\s+/g, ' ').trim().slice(0, 300),
        href: element.href || null,
        input_type: element.type || null,
        form_method: element.form ? (element.form.method || 'get').toLowerCase() : null,
        required: !!element.required || element.getAttribute('aria-required') === 'true',
        disabled: !!element.disabled || element.getAttribute('aria-disabled') === 'true',
        id: element.id || null,
        field_name: element.getAttribute('name') || null,
        attrs,
        context: heading(element).slice(0, 300),
        css: cssFor(element),
        presentation: {
          visible: true,
          viewport_area_ratio: Math.max(0, rect.width * rect.height) / Math.max(1, innerWidth * innerHeight),
          opacity: Number(style.opacity || 1),
          font_size_px: parseFloat(style.fontSize || '0'),
          contrast_ratio: null
        }
      };
    });
}"""


def _control_id(raw: dict) -> str:
    value = "|".join(
        str(raw.get(key) or "") for key in ("role", "name", "href", "input_type", "field_name", "index")
    )
    return "ctl-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\s().-]?){9,15}(?!\d)")
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_SENSITIVE_QUERY_RE = re.compile(
    r"^(?:password|passwd|pwd|token|access_token|refresh_token|id_token|api_?key|client_secret|secret|session|session_?id|authorization)$",
    re.I,
)


def redact_observed_text(value: str, sensitive_values: Sequence[str] = ()) -> str:
    for sensitive in sensitive_values:
        if sensitive:
            value = value.replace(sensitive, "[REDACTED]")
    value = _EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    value = _CARD_RE.sub("[REDACTED_NUMBER]", value)
    return _PHONE_RE.sub("[REDACTED_PHONE]", value)


def redact_observed_url(value: str | None, sensitive_values: Sequence[str] = ()) -> str | None:
    if not value:
        return value
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[REDACTED_URL]"
    hostname = parsed.hostname or ""
    if not parsed.scheme or not hostname:
        return redact_observed_text(value, sensitive_values)
    host = f"[{hostname}]" if ":" in hostname else hostname
    try:
        port = parsed.port
    except ValueError:
        return "[REDACTED_URL]"
    if port is not None:
        host = f"{host}:{port}"
    query_parts: list[str] = []
    for item in parsed.query.split("&") if parsed.query else []:
        key, separator, raw_value = item.partition("=")
        query_parts.append(
            f"{key}{separator}{'[REDACTED]' if _SENSITIVE_QUERY_RE.match(key) else redact_observed_text(raw_value, sensitive_values)}"
        )
    return urlunsplit(
        (parsed.scheme, host, redact_observed_text(parsed.path, sensitive_values), "&".join(query_parts), "")
    )


async def observe_controls(page: Page, sensitive_values: Sequence[str] = ()) -> list[ObservedControl]:
    from app.flow_analysis.selectors import build_selector_bundle

    raw_controls = await page.evaluate(CONTROL_SCRIPT)
    controls: list[ObservedControl] = []
    for raw in raw_controls:
        raw = {
            **raw,
            "name": redact_observed_text(str(raw.get("name") or ""), sensitive_values),
            "href": redact_observed_url(raw.get("href"), sensitive_values),
        }
        if not raw.get("name") and raw.get("input_type") not in {"checkbox", "radio"}:
            continue
        selectors = build_selector_bundle(
            role=raw.get("role"),
            accessible_name=raw.get("name"),
            label=raw.get("name") if raw.get("role") in {"textbox", "combobox", "checkbox", "radio"} else None,
            attributes=raw.get("attrs") or {},
            element_id=raw.get("id"),
            name=raw.get("field_name"),
            css=raw.get("css"),
        )
        controls.append(
            ObservedControl(
                control_id=_control_id(raw),
                role=raw.get("role") or "control",
                name=raw.get("name") or raw.get("field_name") or raw.get("input_type") or "unnamed control",
                href=raw.get("href"),
                input_type=raw.get("input_type"),
                form_method=raw.get("form_method"),
                required=bool(raw.get("required")),
                disabled=bool(raw.get("disabled")),
                selectors=selectors,
                presentation=TargetPresentation.model_validate(raw["presentation"]),
                document_index=int(raw.get("index", 0)),
            )
        )
    return controls


async def page_text(page: Page, sensitive_values: Sequence[str] = ()) -> str:
    try:
        value = await page.locator("body").inner_text(timeout=5_000)
    except Exception:
        value = ""
    return redact_observed_text(re.sub(r"\s+", " ", value).strip(), sensitive_values)[:12_000]


async def page_headings(page: Page, sensitive_values: Sequence[str] = ()) -> list[str]:
    try:
        values = await page.locator("h1,h2,h3").all_inner_texts()
    except Exception:
        values = []
    return list(
        dict.fromkeys(
            redact_observed_text(re.sub(r"\s+", " ", value).strip(), sensitive_values)
            for value in values
            if value.strip()
        )
    )[:30]


async def dialog_text(page: Page, sensitive_values: Sequence[str] = ()) -> str:
    try:
        values = await page.locator('dialog,[role="dialog"],[aria-modal="true"]').all_inner_texts()
    except Exception:
        values = []
    return redact_observed_text(
        re.sub(r"\s+", " ", " ".join(values)).strip(), sensitive_values
    )[:3000]


async def authentication_state(page: Page, text: str) -> str:
    normalized = text.lower()
    if re.search(r"\b(log(?:ged)? out|sign out|my account|account settings|logged in as)\b", normalized):
        return "authenticated"
    password_count = await page.locator('input[type="password"]').count()
    if password_count or re.search(r"\b(log in|sign in)\b", normalized):
        return "anonymous"
    return "unknown"


async def capture_redacted_screenshot(
    page: Page,
    path: Path,
    sensitive_values: Sequence[str] = (),
) -> str | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    masks: list[Locator] = []
    for selector in (
        # Browser evidence must not retain values entered by the user or the
        # automation worker. Masking every editable field is safer than trying
        # to maintain an incomplete list of PII field names.
        'input:not([type="button"]):not([type="submit"]):not([type="reset"]):not([type="checkbox"]):not([type="radio"])',
        "textarea",
        "select",
        '[contenteditable="true"]',
        '[autocomplete^="cc-"]',
        'iframe[src*="stripe" i],iframe[src*="adyen" i],iframe[src*="braintree" i]',
    ):
        locator = page.locator(selector)
        if await locator.count():
            masks.append(locator)
    for sensitive in sensitive_values:
        if len(sensitive.strip()) < 3:
            continue
        locator = page.get_by_text(sensitive, exact=False)
        if await locator.count():
            masks.append(locator)
    try:
        await page.screenshot(path=str(path), full_page=False, mask=masks, mask_color="#111827")
    except Exception:
        return None
    return str(path.relative_to(RUNTIME_DATA_DIR.parent))


async def observe_state(
    page: Page,
    *,
    phase: GraphPhase,
    depth: int,
    run_directory: Path,
    sequence: int,
    has_credentials: bool = False,
    redaction_values: Sequence[str] = (),
) -> tuple[GraphNode, str]:
    from app.flow_analysis.limitations import detect_limitations
    from app.flow_analysis.state_graph import state_fingerprint

    text = await page_text(page, redaction_values)
    headings = await page_headings(page, redaction_values)
    dialogs = await dialog_text(page, redaction_values)
    controls = await observe_controls(page, redaction_values)
    title = redact_observed_text(await page.title(), redaction_values)
    observed_url = redact_observed_url(page.url, redaction_values) or page.url
    auth_state = await authentication_state(page, text)
    fingerprint = state_fingerprint(
        observed_url,
        title=title,
        headings=headings,
        dialog_text=dialogs,
        phase=phase,
        authentication_state=auth_state,
        controls=controls,
    )
    state_id = f"state-{phase[:1]}-{fingerprint[:12]}"
    screenshot = await capture_redacted_screenshot(
        page,
        run_directory / f"graph-{sequence:03d}-{phase}.png",
        redaction_values,
    )
    html = await page.content()
    for sensitive in redaction_values:
        if sensitive:
            html = html.replace(sensitive, "[REDACTED]")
    limitations = detect_limitations(
        text=text,
        html=html,
        url=observed_url,
        has_credentials=has_credentials,
        phase=phase,
    )
    node = GraphNode(
        state_id=state_id,
        fingerprint=fingerprint,
        phase=phase,
        url=observed_url,
        title=title[:500],
        headings=headings,
        dialog_text=dialogs,
        depth=depth,
        authentication_state=auth_state,
        screenshot_path=screenshot,
        controls=controls,
        limitation_codes=list(dict.fromkeys(item.code for item in limitations)),
    )
    return node, text

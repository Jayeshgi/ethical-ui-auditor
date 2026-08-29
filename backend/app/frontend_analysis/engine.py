from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.async_api import Browser, BrowserContext, Page, Response

from app.frontend_analysis.schemas import (
    BehaviorTimelineSample,
    BehaviorDOMSnapshot,
    CodeEvidence,
    FrontendArtifactSummary,
    FrontendBehaviorFinding,
    FrontendBehaviorReport,
    NetworkObservation,
)


ContextFactory = Callable[[], Awaitable[BrowserContext]]
_TIMER_TEXT = re.compile(r"(?<!\d)(?:(\d{1,3}):)?([0-5]?\d):([0-5]\d)(?!\d)")
_DYNAMIC_CODE = re.compile(
    r"setInterval|setTimeout|Date\.now|new\s+Date|countdown|deadline|expires?|remaining|localStorage|sessionStorage",
    re.I,
)
_RELATIVE_DEADLINE_CODE = re.compile(
    r"Date\.now\s*\(\s*\)\s*\+|new\s+Date\s*\(\s*Date\.now\s*\(\s*\)\s*\+|"
    r"(?:duration|countdown|remaining)\s*[=:]",
    re.I,
)
_ABSOLUTE_DEADLINE_CODE = re.compile(r"data-deadline|Date\.parse|deadline\s*[=:]\s*['\"]\d{4}-\d{2}-\d{2}", re.I)
_SCARCITY = re.compile(
    r"(?:only|just)\s+\d+\s+(?:left|remaining|available)|last\s+\d+|selling\s+(?:fast|quickly)", re.I
)
_SOCIAL_PROOF = re.compile(
    r"\d+\s+(?:people|customers|shoppers|travellers|travelers)\s+(?:are\s+)?(?:viewing|watching|bought|purchased)|"
    r"(?:bought|purchased)\s+\d+\s+(?:minutes?|hours?)\s+ago",
    re.I,
)
_SUBSCRIPTION = re.compile(r"per\s+(?:month|week|year)|auto[- ]?renew|recurring|subscription|renews?", re.I)
_OPT_IN = re.compile(r"newsletter|marketing|offers?|insurance|protection|warranty|membership|subscription|auto[- ]?renew", re.I)
_FEE = re.compile(r"service fee|processing fee|handling fee|delivery fee|tax(?:es)?|total", re.I)
_ACCEPT = re.compile(r"accept all|agree|allow all|yes[, ]|continue|confirm|buy|subscribe|start trial", re.I)
_REJECT = re.compile(r"reject|decline|no thanks|not now|manage|essential only|cancel|close", re.I)
_SECRET_KEY = re.compile(r"password|passwd|pwd|token|secret|session|auth|key", re.I)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\s().-]?){9,15}(?!\d)")
_SECRET_ASSIGNMENT = re.compile(
    r"((?:password|passwd|pwd|token|api_?key|client_secret|secret|authorization)\s*[=:]\s*['\"])[^'\"]+",
    re.I,
)
_TOKEN_LITERAL = re.compile(r"\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")


_PAGE_PROBE_SCRIPT = r"""
() => {
  const visible = element => {
    const style = getComputedStyle(element), rect = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity || 1) > 0 && rect.width > 0 && rect.height > 0;
  };
  const selectorFor = element => {
    if (element.id) return `#${CSS.escape(element.id)}`;
    for (const key of ['data-testid','data-test','data-qa','data-flow']) {
      const value = element.getAttribute(key); if (value) return `[${key}="${CSS.escape(value)}"]`;
    }
    const pieces = []; let current = element;
    while (current && current.nodeType === 1 && pieces.length < 5) {
      let piece = current.tagName.toLowerCase();
      const parent = current.parentElement;
      if (parent) {
        const siblings = [...parent.children].filter(child => child.tagName === current.tagName);
        if (siblings.length > 1) piece += `:nth-of-type(${siblings.indexOf(current) + 1})`;
      }
      pieces.unshift(piece); current = parent;
    }
    return pieces.join(' > ');
  };
  const color = value => {
    const match = String(value).match(/[\d.]+/g); if (!match || match.length < 3) return [0,0,0];
    return match.slice(0,3).map(Number);
  };
  const luminance = rgb => {
    const values = rgb.map(v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; });
    return .2126 * values[0] + .7152 * values[1] + .0722 * values[2];
  };
  const presentation = element => {
    const style = getComputedStyle(element), rect = element.getBoundingClientRect();
    const fg = luminance(color(style.color)), bg = luminance(color(style.backgroundColor));
    const contrast = (Math.max(fg,bg)+.05)/(Math.min(fg,bg)+.05);
    return {visible:visible(element), area:Math.round(rect.width*rect.height), font_size:parseFloat(style.fontSize)||0,
      opacity:Number(style.opacity||1), contrast:Math.round(contrast*100)/100, display:style.display,
      visibility:style.visibility, z_index:style.zIndex};
  };
  const all = [...document.querySelectorAll('body *')].slice(0,5000);
  const timers = all.filter(element => visible(element) && /(?<!\d)(?:(?:\d{1,3}):)?(?:[0-5]?\d):(?:[0-5]\d)(?!\d)/.test((element.innerText||'').trim()))
    .filter(element => ![...element.children].some(child => visible(child) && /(?<!\d)(?:(?:\d{1,3}):)?(?:[0-5]?\d):(?:[0-5]\d)(?!\d)/.test((child.innerText||'').trim())))
    .slice(0,5).map(element => ({selector:selectorFor(element), text:(element.innerText||'').replace(/\s+/g,' ').trim().slice(0,500),
      context:(element.parentElement?.innerText||element.innerText||'').replace(/\s+/g,' ').trim().slice(0,1000),
      attributes:Object.fromEntries([...element.attributes].filter(x => /deadline|timer|count|expire|end/i.test(x.name)).map(x => [x.name,x.value.slice(0,300)])),
      presentation:presentation(element)}));
  const choices = [...document.querySelectorAll('input[type=checkbox],input[type=radio],select')].slice(0,200).map(element => {
    const id = element.id, label = (id ? document.querySelector(`label[for="${CSS.escape(id)}"]`) : null) || element.closest('label');
    const selected = element.matches('select') ? [...element.options].filter(x=>x.selected).map(x=>x.text).join(', ') : Boolean(element.checked);
    const initiallySelected = element.matches('select') ? [...element.options].some(x=>x.defaultSelected) : Boolean(element.defaultChecked);
    return {selector:selectorFor(element), type:element.type||element.tagName.toLowerCase(), selected, initially_selected:initiallySelected,
      text:(label?.innerText||element.getAttribute('aria-label')||element.name||'').replace(/\s+/g,' ').trim().slice(0,500), presentation:presentation(element)};
  });
  const controls = [...document.querySelectorAll('button,a,input[type=button],input[type=submit],[role=button]')].slice(0,500).map(element => ({
    selector:selectorFor(element), text:(element.innerText||element.value||element.getAttribute('aria-label')||'').replace(/\s+/g,' ').trim().slice(0,500),
    href:element.href||element.formAction||element.getAttribute('data-href')||null,
    handler:(element.getAttribute('onclick')||'').slice(0,500),
    type:element.type||element.tagName.toLowerCase(), presentation:presentation(element)
  })).filter(item=>item.text);
  const textElements = [...document.querySelectorAll('p,span,div,li,strong,small')].filter(visible).map(element => ({
    selector:selectorFor(element), text:(element.innerText||'').replace(/\s+/g,' ').trim().slice(0,500), presentation:presentation(element)
  })).filter(item=>item.text && item.text.length <= 500);
  const claimPattern=/(?:only|just)\s+\d+\s+(?:left|remaining|available)|last\s+\d+|\d+\s+(?:people|customers|shoppers|travellers|travelers)\s+(?:are\s+)?(?:viewing|watching|bought|purchased)|(?:bought|purchased)\s+\d+\s+(?:minutes?|hours?)\s+ago/i;
  const claims = textElements.filter(item => claimPattern.test(item.text)).filter(item => {
    const element=document.querySelector(item.selector); return !element || ![...element.children].some(child=>claimPattern.test(child.innerText||''));
  }).slice(0,30);
  const disclosurePattern=/per\s+(?:month|week|year)|auto[- ]?renew|recurring|subscription|renews?|service fee|processing fee|handling fee/i;
  const disclosures = [...document.querySelectorAll('p,span,div,li,strong,small,label')].filter(element => {
    const own=(element.innerText||element.textContent||'').replace(/\s+/g,' ').trim();
    return disclosurePattern.test(own) && ![...element.children].some(child=>disclosurePattern.test(child.innerText||''));
  }).map(element => ({
    selector:selectorFor(element), text:(element.innerText||element.textContent||'').replace(/\s+/g,' ').trim().slice(0,500), presentation:presentation(element)
  })).filter(item => item.text && item.text.length <= 500).slice(0,30);
  const dialogs = [...document.querySelectorAll('[role=dialog],dialog,.modal,.popup,[class*=modal],[class*=popup]')].filter(visible)
    .map(element=>(element.innerText||'').replace(/\s+/g,' ').trim().slice(0,500)).filter(Boolean);
  return {timers, choices, controls, claims, disclosures, dialogs,
    expired:/offer\s+(?:has\s+)?expired|sale\s+(?:has\s+)?ended|promotion\s+(?:has\s+)?ended/i.test(document.body.innerText),
    promotion:/limited time|special offer|sale price|discount|%\s*off|buy now/i.test(document.body.innerText)};
}
"""


_MUTATION_INSTALL_SCRIPT = r"""
() => {
  window.__flowlensEvents = [];
  const record = node => {
    if (!(node instanceof Element)) return;
    const target = node.matches?.('[role=dialog],dialog,.modal,.popup,[class*=modal],[class*=popup]') ? node : node.closest?.('[role=dialog],dialog,.modal,.popup,[class*=modal],[class*=popup]');
    if (!target) return;
    const style=getComputedStyle(target), rect=target.getBoundingClientRect();
    if (style.display==='none'||style.visibility==='hidden'||Number(style.opacity||1)<=0||rect.width<=0||rect.height<=0) return;
    const text=(target.innerText||'').replace(/\s+/g,' ').trim().slice(0,500);
    if (text) window.__flowlensEvents.push({elapsed_ms:Math.round(performance.now()),kind:'dialog_visible',text});
    window.__flowlensEvents = window.__flowlensEvents.slice(-200);
  };
  new MutationObserver(records => records.forEach(mutation => {
    if (mutation.type==='attributes') record(mutation.target);
    else [...mutation.addedNodes].forEach(node => { record(node); if(node.querySelectorAll) node.querySelectorAll('[role=dialog],dialog,.modal,.popup,[class*=modal],[class*=popup]').forEach(record); });
  })).observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:['class','style','open','hidden']});
}
"""


def parse_countdown_seconds(value: str | None) -> int | None:
    if not value:
        return None
    match = _TIMER_TEXT.search(value)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)


def _sha256(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8", errors="replace")
    return hashlib.sha256(value).hexdigest()


def _safe_url(value: str) -> str:
    parsed = urlparse(value)
    query = urlencode([(key, "[REDACTED]" if _SECRET_KEY.search(key) else "") for key, _ in parse_qsl(parsed.query)])
    hostname = parsed.hostname or ""
    host = f"[{hostname}]" if ":" in hostname else hostname
    try:
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
    except ValueError:
        host = "[INVALID_HOST]"
    return urlunparse((parsed.scheme, host, _redact_text(parsed.path), "", query, ""))[:2000]


def _same_origin(left: str, right: str) -> bool:
    a, b = urlparse(left), urlparse(right)
    return (a.scheme.lower(), a.netloc.lower()) == (b.scheme.lower(), b.netloc.lower())


def _redact_text(value: str, sensitive_values: tuple[str, ...] = ()) -> str:
    for sensitive in sensitive_values:
        if sensitive:
            value = value.replace(sensitive, "[REDACTED]")
    value = _SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", value)
    value = _TOKEN_LITERAL.sub("[REDACTED_TOKEN]", value)
    value = _EMAIL.sub("[REDACTED_EMAIL]", value)
    value = _CARD.sub("[REDACTED_NUMBER]", value)
    return _PHONE.sub("[REDACTED_PHONE]", value)


def _sanitize_probe(value: Any, sensitive_values: tuple[str, ...] = ()) -> Any:
    if isinstance(value, list):
        return [_sanitize_probe(item, sensitive_values) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key == "href" and isinstance(item, str):
                result[key] = _safe_url(item)
            else:
                result[key] = _sanitize_probe(item, sensitive_values)
        return result
    if isinstance(value, str):
        return _redact_text(value, sensitive_values)
    return value


def _code_excerpt(source: str, match: re.Match[str], sensitive_values: tuple[str, ...] = ()) -> str:
    start, end = max(0, match.start() - 180), min(len(source), match.end() + 220)
    return _redact_text(re.sub(r"\s+", " ", source[start:end]).strip(), sensitive_values)[:600]


async def _safe_screenshot(page: Page, path: Path, sensitive_values: tuple[str, ...] = ()) -> str | None:
    try:
        await page.evaluate(
            """values => { const email=/\\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}\\b/i, card=/(?<!\\d)(?:\\d[ -]?){13,19}(?!\\d)/, phone=/(?<!\\d)(?:\\+?\\d[\\s().-]?){9,15}(?!\\d)/;
            for(const element of document.querySelectorAll('body *')){const direct=[...element.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent||'').join(' ');if(email.test(direct)||card.test(direct)||phone.test(direct)||values.some(v=>v&&direct.includes(v)))element.dataset.flowlensSensitive='true'}}""",
            list(sensitive_values),
        )
        masks = [
            page.locator("input:not([type=button]):not([type=submit]):not([type=reset]):not([type=checkbox]):not([type=radio])"),
            page.locator("textarea,select,[contenteditable=true]"),
            page.locator("[data-flowlens-sensitive=true]"),
        ]
        await page.screenshot(path=str(path), full_page=True, mask=masks)
        await page.locator("[data-flowlens-sensitive=true]").evaluate_all("els => els.forEach(e => e.removeAttribute('data-flowlens-sensitive'))")
        return str(path)
    except Exception:
        return None


async def _probe(page: Page) -> dict[str, Any]:
    return await page.evaluate(_PAGE_PROBE_SCRIPT)


async def _value_for(page: Page, selector: str) -> str | None:
    try:
        return await page.locator(selector).first.evaluate("e => (e.innerText || e.textContent || '').replace(/\\s+/g,' ').trim().slice(0,500)")
    except Exception:
        return None


async def _collect_artifacts(
    page: Page,
    response: Response | None,
    target_url: str,
    network: list[NetworkObservation],
    script_sources: dict[str, tuple[str, str]],
    sensitive_values: tuple[str, ...],
) -> FrontendArtifactSummary:
    original_hash = None
    if response is not None:
        try:
            original_hash = _sha256((await response.body())[:2_000_000])
        except Exception:
            pass
    rendered = await page.content()
    inline_scripts: list[str] = await page.locator("script:not([src])").all_text_contents()
    script_urls: list[str] = await page.locator("script[src]").evaluate_all("els => els.map(e => e.src)")
    code_evidence: list[CodeEvidence] = []
    for match in list(re.finditer(r"data-(?:deadline|expires?|end(?:-time)?)\s*=\s*['\"][^'\"]+", rendered, re.I))[:5]:
        code_evidence.append(
            CodeEvidence(
                source="rendered_dom",
                sha256=_sha256(rendered),
                excerpt=_code_excerpt(rendered, match, sensitive_values),
                signals=["absolute_deadline"],
            )
        )
    for source in inline_scripts[:30]:
        for match in list(_DYNAMIC_CODE.finditer(source))[:3]:
            signals = ["dynamic_frontend_logic"]
            if _RELATIVE_DEADLINE_CODE.search(source):
                signals.append("client_relative_deadline")
            if _ABSOLUTE_DEADLINE_CODE.search(source):
                signals.append("absolute_deadline")
            code_evidence.append(
                CodeEvidence(source="inline_script", sha256=_sha256(source), excerpt=_code_excerpt(source, match, sensitive_values), signals=signals)
            )
            if len(code_evidence) >= 20:
                break
    asset_hashes: dict[str, str] = {}
    for asset_url in list(dict.fromkeys(script_urls))[:12]:
        safe_asset = _safe_url(asset_url)
        captured = script_sources.get(safe_asset)
        if captured is None:
            continue
        try:
            digest, source = captured
            asset_hashes[safe_asset] = digest
            for match in list(_DYNAMIC_CODE.finditer(source))[:2]:
                signals = ["dynamic_frontend_logic"]
                if _RELATIVE_DEADLINE_CODE.search(source):
                    signals.append("client_relative_deadline")
                if _ABSOLUTE_DEADLINE_CODE.search(source):
                    signals.append("absolute_deadline")
                code_evidence.append(
                    CodeEvidence(
                        source="script_asset", asset_url=safe_asset, sha256=digest,
                        excerpt=_code_excerpt(source, match, sensitive_values), signals=signals,
                    )
                )
        except Exception:
            continue
    try:
        storage_keys = await page.evaluate("() => [...new Set([...Object.keys(localStorage),...Object.keys(sessionStorage)])].slice(0,100)")
        storage_keys = ["[REDACTED_KEY]" if _SECRET_KEY.search(key) else _redact_text(key)[:120] for key in storage_keys]
    except Exception:
        storage_keys = []
    try:
        cookie_names = ["[REDACTED_NAME]" if _SECRET_KEY.search(item["name"]) else _redact_text(item["name"])[:120] for item in await context.cookies()]
    except Exception:
        cookie_names = []
    unique_code: list[CodeEvidence] = []
    seen_code: set[tuple[str | None, str | None, str]] = set()
    for item in code_evidence:
        key = (item.asset_url, item.sha256, item.excerpt)
        if key not in seen_code:
            seen_code.add(key)
            unique_code.append(item)
    return FrontendArtifactSummary(
        original_html_sha256=original_hash,
        rendered_dom_sha256=_sha256(rendered),
        inline_script_count=len(inline_scripts),
        script_asset_count=len(script_urls),
        script_asset_hashes=asset_hashes,
        stylesheet_asset_hashes={
            item.url: item.response_sha256
            for item in network
            if item.resource_type == "stylesheet" and item.response_sha256
        },
        storage_keys=list(dict.fromkeys(storage_keys)),
        cookie_names=list(dict.fromkeys(cookie_names)),
        network_observations=network[:100],
        code_evidence=unique_code[:30],
    )


def _finding(
    category: str,
    status: str,
    confidence: float,
    rationale: str,
    *,
    element: str | None = None,
    evidence: list[str] | None = None,
    counter: list[str] | None = None,
    implementation_signal: str | None = None,
    code: list[CodeEvidence] | None = None,
) -> FrontendBehaviorFinding:
    taxonomy = {
        "resetting_countdown": "false_urgency", "non_expiring_offer": "false_urgency",
        "session_relative_deadline": "false_urgency", "fabricated_scarcity": "false_scarcity",
        "fabricated_social_proof": "social_proof", "preselected_option": "forced_consent",
        "hidden_rejection": "forced_consent", "silent_cart_addition": "sneaking",
        "late_price_disclosure": "sneaking", "repeated_nagging": "obstruction",
        "misleading_action": "misleading_claim", "subscription_disclosure": "subscription_manipulation",
    }
    severity = "high" if status == "detected" and confidence >= 0.9 else "medium" if status in {"detected", "suspicious"} else "none"
    score = confidence * (100 if status == "detected" else 75 if status == "suspicious" else 35 if status == "inconclusive" else 0)
    return FrontendBehaviorFinding(
        category=category, dark_pattern_category=taxonomy[category], status=status, severity=severity,
        score=round(score, 1), confidence=round(confidence, 3),
        element=element, evidence=evidence or [], counter_evidence=counter or [], implementation_signal=implementation_signal,
        code_evidence=code or [], rationale=rationale,
    )


def _code_for(artifacts: FrontendArtifactSummary, signal: str) -> list[CodeEvidence]:
    return [item for item in artifacts.code_evidence if signal in item.signals][:5]


def _static_findings(initial: dict[str, Any], clean: dict[str, Any], artifacts: FrontendArtifactSummary) -> list[FrontendBehaviorFinding]:
    findings: list[FrontendBehaviorFinding] = []
    for choice in initial.get("choices", []):
        text = choice.get("text", "")
        if choice.get("initially_selected") and _OPT_IN.search(text):
            findings.append(_finding(
                "preselected_option", "detected", 0.88,
                "An optional marketing, protection, membership, or subscription choice was selected before user action.",
                element=choice.get("selector"), evidence=[f"Initially selected control: {text[:240]}"],
            ))

    controls = initial.get("controls", [])
    accept = [item for item in controls if _ACCEPT.search(item.get("text", ""))]
    reject = [item for item in controls if _REJECT.search(item.get("text", ""))]
    if accept and reject:
        primary = max(accept, key=lambda x: x["presentation"].get("area", 0))
        secondary = min(reject, key=lambda x: x["presentation"].get("area", 0))
        p, s = primary["presentation"], secondary["presentation"]
        reasons = []
        if not s.get("visible"):
            reasons.append("rejection control is not visibly presented")
        if p.get("area", 0) > max(1, s.get("area", 0)) * 2.5:
            reasons.append("accept control is more than 2.5 times larger")
        if p.get("font_size", 0) > max(1, s.get("font_size", 0)) * 1.3:
            reasons.append("accept label is materially larger")
        if s.get("opacity", 1) < 0.6 or s.get("contrast", 10) < 3:
            reasons.append("rejection control has weak opacity or contrast")
        if reasons:
            findings.append(_finding(
                "hidden_rejection", "detected" if len(reasons) >= 2 else "suspicious", 0.88 if len(reasons) >= 2 else 0.72,
                "The acceptance and rejection controls have a materially asymmetric visual presentation.",
                element=secondary.get("selector"), evidence=[*reasons, f"Primary: {primary['text'][:120]}; rejection: {secondary['text'][:120]}"],
            ))

    clean_claims = {item.get("text", "") for item in clean.get("claims", [])}
    for claim in initial.get("claims", []):
        text = claim.get("text", "")
        category = "fabricated_scarcity" if _SCARCITY.search(text) else "fabricated_social_proof" if _SOCIAL_PROOF.search(text) else None
        if not category:
            continue
        identical = text in clean_claims
        findings.append(_finding(
            category, "suspicious" if identical else "inconclusive", 0.61 if identical else 0.42,
            "The dynamic-looking claim was repeated in an independent clean browser session; this is supporting evidence, not proof of fabrication.",
            element=claim.get("selector"), evidence=[f"Claim: {text[:300]}"] + (["Identical text appeared in a clean session."] if identical else []),
            counter=[] if identical else ["The claim changed between sessions."],
        ))

    for control in controls:
        label, href = control.get("text", ""), control.get("href") or ""
        handler = control.get("handler") or ""
        destination_signal = f"{href} {handler}"
        mismatch = None
        if re.search(r"\bcontinue\b|\bnext\b", label, re.I) and re.search(r"subscribe|subscription|checkout|purchase|trial", destination_signal, re.I):
            mismatch = "A generic continuation label points to a subscription, checkout, purchase, or trial destination."
        elif re.search(r"download", label, re.I) and not re.search(r"download|\.pdf|\.zip|\.exe|\.dmg", href, re.I):
            mismatch = "A download-labelled control does not point to an apparent download destination."
        elif re.search(r"close|dismiss|not now", label, re.I) and re.search(r"subscribe|accept|checkout", href, re.I):
            mismatch = "A close or rejection label points to an acceptance or purchase destination."
        if mismatch:
            findings.append(_finding(
                "misleading_action", "suspicious", 0.76, mismatch,
                element=control.get("selector"), evidence=[f"Label: {label[:160]}", f"Destination or public handler signal: {_redact_text(destination_signal)[:500]}"],
            ))

    for disclosure in initial.get("disclosures", []):
        text, style = disclosure.get("text", ""), disclosure.get("presentation", {})
        if not _SUBSCRIPTION.search(text):
            continue
        weak = not style.get("visible") or style.get("font_size", 16) < 11 or style.get("opacity", 1) < 0.6 or style.get("contrast", 10) < 3
        if weak:
            findings.append(_finding(
                "subscription_disclosure", "detected", 0.87,
                "Recurring or subscription terms are present but visually de-emphasized.",
                element=disclosure.get("selector"), evidence=[f"Disclosure: {text[:300]}", f"Presentation: {style}"],
            ))
        if _FEE.search(text) and (not style.get("visible") or style.get("font_size", 16) < 11 or style.get("opacity", 1) < 0.6):
            findings.append(_finding(
                "late_price_disclosure", "suspicious", 0.74,
                "A fee or total disclosure exists in the DOM but is initially hidden.",
                element=disclosure.get("selector"), evidence=[f"Hidden disclosure: {text[:300]}"],
            ))

    selected_addons = [item for item in initial.get("choices", []) if item.get("initially_selected") and re.search(r"insurance|protection|warranty|add[- ]?on", item.get("text", ""), re.I)]
    for addon in selected_addons:
        findings.append(_finding(
            "silent_cart_addition", "suspicious", 0.78,
            "A paid-looking optional add-on is selected before user action; cart-delta confirmation is required for a definitive finding.",
            element=addon.get("selector"), evidence=[f"Preselected add-on: {addon.get('text','')[:300]}"],
            counter=["No purchase or cart mutation was executed by the safe runtime analyzer."],
        ))
    return findings


async def analyze_frontend_behavior(
    browser: Browser,
    target_url: str,
    context_factory: ContextFactory,
    output_directory: Path,
    *,
    observation_seconds: int = 30,
    analyse_models: bool = True,
    sensitive_values: tuple[str, ...] = (),
) -> FrontendBehaviorReport:
    """Run bounded, passive behavioural experiments against browser-delivered frontend code.

    No arbitrary control is clicked. Reload and a clean browser context are the
    only active experiments, which keeps this safe for evidence-only targets.
    """
    output_directory.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    screenshots: list[str] = []
    network: list[NetworkObservation] = []
    script_sources: dict[str, tuple[str, str]] = {}
    response_tasks: set[asyncio.Task] = set()
    context = await context_factory()
    page = await context.new_page()

    async def capture_response(response: Response) -> None:
        if len(network) >= 100 or not _same_origin(response.url, target_url):
            return
        safe = _safe_url(response.url)
        digest = None
        resource_type = response.request.resource_type[:40]
        content_type = (response.headers.get("content-type") or "")[:160] or None
        content_length = int(response.headers.get("content-length") or 0)
        if resource_type in {"document", "script", "stylesheet", "xhr", "fetch"} and content_length <= 1_000_000:
            try:
                body = await response.body()
                if len(body) <= 1_000_000:
                    digest = _sha256(body)
                    if resource_type == "script":
                        script_sources[safe] = (digest, body.decode("utf-8", errors="replace"))
            except Exception:
                pass
        network.append(NetworkObservation(
            method=response.request.method[:16], url=safe, status=response.status,
            resource_type=resource_type, content_type=content_type, response_sha256=digest,
        ))

    def on_response(response: Response) -> None:
        task = asyncio.create_task(capture_response(response))
        response_tasks.add(task)
        task.add_done_callback(response_tasks.discard)

    page.on("response", on_response)
    try:
        response = await page.goto(target_url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(700)
        await page.evaluate(_MUTATION_INSTALL_SCRIPT)
        initial = _sanitize_probe(await _probe(page), sensitive_values)
        initial_path = await _safe_screenshot(page, output_directory / "behavior-initial.png", sensitive_values)
        if initial_path:
            screenshots.append(initial_path)
        if response_tasks:
            await asyncio.gather(*list(response_tasks), return_exceptions=True)
        artifacts = await _collect_artifacts(page, response, target_url, network, script_sources, sensitive_values)

        timer_timelines: dict[str, list[BehaviorTimelineSample]] = {}
        for timer in initial.get("timers", []):
            value = timer.get("text", "")
            timer_timelines[timer["selector"]] = [BehaviorTimelineSample(elapsed_ms=0, value=value, parsed_seconds=parse_countdown_seconds(value))]
        dialog_episodes: list[dict[str, Any]] = []
        for second in range(1, observation_seconds + 1):
            await page.wait_for_timeout(1000)
            for selector, timeline in timer_timelines.items():
                value = await _value_for(page, selector)
                if value is not None:
                    seconds_value = parse_countdown_seconds(value)
                    previous = timeline[-1].parsed_seconds if timeline else None
                    event = "timer_reset" if previous is not None and seconds_value is not None and seconds_value > previous + 2 else (
                        "deadline_reached" if seconds_value is not None and seconds_value <= 1 else "observation"
                    )
                    timeline.append(BehaviorTimelineSample(
                        elapsed_ms=second * 1000, value=value, parsed_seconds=seconds_value, event=event,
                    ))
            if second == observation_seconds:
                try:
                    dialog_episodes = await page.evaluate("() => window.__flowlensEvents || []")
                except Exception:
                    dialog_episodes = []
        observed = _sanitize_probe(await _probe(page), sensitive_values)
        observed_path = await _safe_screenshot(page, output_directory / "behavior-observed.png", sensitive_values)
        if observed_path:
            screenshots.append(observed_path)

        await page.reload(wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(800)
        reloaded = _sanitize_probe(await _probe(page), sensitive_values)
        reload_path = await _safe_screenshot(page, output_directory / "behavior-reload.png", sensitive_values)
        if reload_path:
            screenshots.append(reload_path)
    except Exception as error:
        await context.close()
        return FrontendBehaviorReport(
            status="completed_with_warnings", observation_seconds=observation_seconds,
            warnings=[f"Runtime frontend analysis failed: {type(error).__name__}: {error}"],
        )

    clean_context = await context_factory()
    clean_page = await clean_context.new_page()
    try:
        await clean_page.goto(target_url, wait_until="domcontentloaded", timeout=30_000)
        await clean_page.wait_for_timeout(800)
        clean = _sanitize_probe(await _probe(clean_page), sensitive_values)
        clean_path = await _safe_screenshot(clean_page, output_directory / "behavior-clean-session.png", sensitive_values)
        if clean_path:
            screenshots.append(clean_path)
    except Exception as error:
        clean = {"timers": [], "claims": [], "choices": [], "controls": [], "disclosures": [], "dialogs": []}
        warnings.append(f"Clean-session comparison failed: {type(error).__name__}: {error}")
    finally:
        await clean_context.close()

    findings: list[FrontendBehaviorFinding] = []
    reloaded_timers = {item["selector"]: item for item in reloaded.get("timers", [])}
    clean_timers = {item["selector"]: item for item in clean.get("timers", [])}
    relative_code = _code_for(artifacts, "client_relative_deadline")
    absolute_code = _code_for(artifacts, "absolute_deadline")
    for timer in initial.get("timers", []):
        selector = timer["selector"]
        timeline = timer_timelines.get(selector, [])
        parsed = [item.parsed_seconds for item in timeline if item.parsed_seconds is not None]
        initial_seconds = parsed[0] if parsed else parse_countdown_seconds(timer.get("text"))
        final_seconds = parsed[-1] if parsed else None
        reload_text = reloaded_timers.get(selector, {}).get("text")
        clean_text = clean_timers.get(selector, {}).get("text")
        reload_seconds, clean_seconds = parse_countdown_seconds(reload_text), parse_countdown_seconds(clean_text)
        observed_reset = any(b > a + 2 for a, b in zip(parsed, parsed[1:]))
        progressed = any(b < a for a, b in zip(parsed, parsed[1:]))
        reload_reset = bool(initial_seconds is not None and reload_seconds is not None and observation_seconds >= 5 and reload_seconds >= initial_seconds - 2)
        clean_fresh = bool(initial_seconds is not None and clean_seconds is not None and abs(clean_seconds - initial_seconds) <= 2)
        reached_zero = bool(parsed and min(parsed) <= 1)
        offer_changed = bool(observed.get("expired")) or (not observed.get("promotion", True) and initial.get("promotion", False))
        evidence, counter = [], []
        if observed_reset:
            evidence.append("The countdown jumped backwards or restarted during observation.")
        if reload_reset:
            evidence.append("Reloading restored approximately the original countdown duration.")
        if clean_fresh:
            evidence.append("An independent clean browser session received approximately the same fresh duration.")
        if reached_zero and not offer_changed:
            evidence.append("The countdown reached zero while the promoted offer remained available.")
        if relative_code:
            evidence.append("Browser-delivered code contains a client-relative deadline signal.")
        if absolute_code:
            counter.append("Browser-delivered code contains an absolute-deadline signal.")
        if progressed and reload_reset and clean_fresh and (observed_reset or relative_code):
            status, confidence, signal = "detected", 0.95, "client_relative_deadline"
            rationale = "The countdown behaves as a visitor-relative timer and restarts across reload and clean-session experiments."
        elif reached_zero and not offer_changed:
            status, confidence, signal = "detected", 0.92, "non_expiring_offer"
            rationale = "The urgency deadline expired without the advertised promotion ending."
        elif reload_reset or clean_fresh or observed_reset:
            status, confidence, signal = "suspicious", 0.78, "reset_signal"
            rationale = "The countdown showed reset-like behaviour, but the available observations do not establish all strong-evidence conditions."
        elif absolute_code and initial_seconds is not None and reload_seconds is not None and reload_seconds < initial_seconds:
            status, confidence, signal = "not_detected", 0.9, "absolute_deadline"
            rationale = "The countdown continued toward a shared absolute deadline across reload experiments."
            counter.append("The reload value continued below the initial value instead of restarting.")
        else:
            status, confidence, signal = "inconclusive", 0.48, "unverified_timer"
            rationale = "A countdown was observed, but neither deceptive resetting nor a shared genuine deadline could be verified."
        primary_category = "resetting_countdown"
        finding = _finding(
            primary_category, status, confidence, rationale, element=selector, evidence=evidence, counter=counter,
            implementation_signal=signal, code=[*relative_code, *absolute_code][:6],
        )
        finding = finding.model_copy(update={
            "initial_value": timer.get("text"), "observed_value": timeline[-1].value if timeline else None,
            "after_reload": reload_text, "clean_session_value": clean_text,
            "offer_changed_at_expiry": offer_changed if reached_zero else None,
            "timeline": [
                *timeline,
                *([BehaviorTimelineSample(elapsed_ms=(observation_seconds + 1) * 1000, value=reload_text, parsed_seconds=reload_seconds, event="reload")] if reload_text else []),
                *([BehaviorTimelineSample(elapsed_ms=(observation_seconds + 2) * 1000, value=clean_text, parsed_seconds=clean_seconds, event="clean_session")] if clean_text else []),
            ],
            "screenshot_paths": screenshots,
        })
        findings.append(finding)
        if reached_zero and not offer_changed:
            findings.append(_finding(
                "non_expiring_offer", "detected", 0.92,
                "The countdown reached zero while the advertised offer remained visibly available.",
                element=selector,
                evidence=["The timer reached zero.", "The promotion and offer state did not end or materially change."],
                implementation_signal="non_expiring_offer",
                code=[*relative_code, *absolute_code][:6],
            ))
        if status == "detected" and signal == "client_relative_deadline":
            findings.append(_finding(
                "session_relative_deadline", "detected", 0.93,
                "The deadline is initialized relative to each visitor session rather than shared as a campaign deadline.",
                element=selector, evidence=[item for item in evidence if "clean browser" in item or "client-relative" in item],
                implementation_signal=signal, code=relative_code,
            ))

    findings.extend(_static_findings(initial, clean, artifacts))
    episode_counts = Counter(re.sub(r"\s+", " ", item.get("text", "")).strip().lower() for item in dialog_episodes if item.get("text"))
    repeated = [(text, count) for text, count in episode_counts.items() if count >= 2]
    if repeated:
        text, count = max(repeated, key=lambda item: item[1])
        findings.append(_finding(
            "repeated_nagging", "detected", 0.89,
            "The same dialog or popup was presented repeatedly during passive observation.",
            evidence=[f"Dialog appeared {count} times: {text[:300]}"],
        ))

    # Deduplicate identical category/element results while preserving distinct timer elements.
    deduplicated: list[FrontendBehaviorFinding] = []
    seen: set[tuple[str, str | None]] = set()
    for item in sorted(findings, key=lambda finding: finding.confidence, reverse=True):
        key = (item.category, item.element)
        if key not in seen:
            seen.add(key)
            deduplicated.append(item)

    if analyse_models and deduplicated:
        first_shot = Path(screenshots[0]) if screenshots else None
        try:
            from app.flow_analysis.evidence import analyse_step_evidence
            visual_cues: list[str] = []
            if first_shot and first_shot.exists():
                try:
                    from app.scans.service import get_visual_detector
                    visual_cues = list(dict.fromkeys(item.cue for item in await asyncio.to_thread(get_visual_detector().predict, first_shot)))
                except Exception:
                    pass
            for index, item in enumerate(deduplicated):
                text = "\n".join([item.initial_value or "", *item.evidence, item.rationale])
                support = await asyncio.to_thread(analyse_step_evidence, text, None, None, True, "acquisition")
                deduplicated[index] = item.model_copy(update={
                    "bert_categories": support.bert_categories,
                    "visual_cues": visual_cues,
                })
        except Exception as error:
            warnings.append(f"Behavioural model corroboration failed: {type(error).__name__}: {error}")

    await context.close()
    return FrontendBehaviorReport(
        status="completed_with_warnings" if warnings else "completed",
        observation_seconds=observation_seconds,
        findings=deduplicated,
        dom_snapshots=[
            BehaviorDOMSnapshot(elapsed_ms=0, phase="initial", **{key: initial.get(key, []) for key in ("timers", "claims", "choices", "dialogs")}),
            BehaviorDOMSnapshot(elapsed_ms=observation_seconds * 1000, phase="observed", **{key: observed.get(key, []) for key in ("timers", "claims", "choices", "dialogs")}),
            BehaviorDOMSnapshot(elapsed_ms=(observation_seconds + 1) * 1000, phase="reload", **{key: reloaded.get(key, []) for key in ("timers", "claims", "choices", "dialogs")}),
            BehaviorDOMSnapshot(elapsed_ms=(observation_seconds + 2) * 1000, phase="clean_session", **{key: clean.get(key, []) for key in ("timers", "claims", "choices", "dialogs")}),
        ],
        artifacts=artifacts,
        screenshots=screenshots,
        warnings=warnings,
    )

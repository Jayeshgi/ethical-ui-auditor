from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse


router = APIRouter(tags=["flow-benchmarks"])


def _behavior_page(title: str, body: str, script: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
body{{font-family:Inter,system-ui,sans-serif;background:#f4f6fb;color:#151b2b;margin:0}}header{{background:#17213a;color:#fff;padding:18px 28px}}main{{max-width:980px;margin:34px auto;padding:0 22px}}.product{{display:grid;grid-template-columns:1fr 1fr;gap:26px;background:white;padding:28px;border-radius:18px;box-shadow:0 16px 45px #1a27451a}}.photo{{min-height:340px;border-radius:14px;background:linear-gradient(135deg,#dbe6ff,#b9c8f5);display:grid;place-items:center;font-size:72px}}.price{{font-size:34px;font-weight:850}}.timer{{font:800 34px ui-monospace,monospace;color:#b42318;margin:12px 0}}button,a.cta{{display:inline-block;background:#3157d5;color:white;border:0;border-radius:9px;padding:13px 20px;font-weight:800;text-decoration:none;cursor:pointer}}.choices{{padding:14px;background:#f7f8fc;border-radius:10px;margin:14px 0}}.choices label{{display:block;margin:9px 0}}.consent{{position:fixed;bottom:15px;left:15px;right:15px;background:white;border:1px solid #ccd3e1;padding:16px;box-shadow:0 8px 30px #0002;z-index:20}}.accept{{font-size:17px;padding:14px 24px}}.reject{{font-size:9px;opacity:.38;background:#697386;padding:5px 7px}}.fineprint{{font-size:9px;opacity:.42;color:#6b7280}}.claim{{background:#fff4df;color:#8a3a05;padding:8px 10px;border-radius:8px;margin:8px 0}}.popup{{position:fixed;inset:25% 30%;background:white;border:3px solid #3157d5;border-radius:16px;padding:25px;z-index:30;box-shadow:0 20px 80px #0006}}
</style></head><body><header><b>FlowLens Research Store</b></header><main>{body}</main><script>{script}</script></body></html>"""
    )


@router.get("/behavior-benchmarks/genuine-countdown", response_class=HTMLResponse)
def genuine_countdown_benchmark() -> HTMLResponse:
    # One server-defined absolute deadline is shared by reloads and clean
    # sessions. Keep at least 45 seconds in the current two-minute window.
    now_ms = int(time.time() * 1000)
    deadline_ms = ((now_ms // 120_000) + 1) * 120_000
    if deadline_ms - now_ms < 45_000:
        deadline_ms += 120_000
    body = f"""<section class="product"><div class="photo">🎧</div><div><h1>Scheduled launch sale</h1><p class="price">₹2,499</p>
<p>This public campaign ends for everyone at the same time.</p><div id="sale-countdown" class="timer" data-deadline="{deadline_ms}">Loading…</div>
<p id="offer-state">Sale price available until the scheduled deadline.</p><button type="button">View product details</button></div></section>"""
    script = f"""const campaignDeadline = new Date({deadline_ms});
const timer = document.querySelector('#sale-countdown'); const state = document.querySelector('#offer-state');
function render(){{const seconds=Math.max(0,Math.floor((campaignDeadline-Date.now())/1000));const m=String(Math.floor(seconds/60)).padStart(2,'0'),s=String(seconds%60).padStart(2,'0');timer.textContent=`${{m}}:${{s}}`;if(seconds===0){{state.textContent='Offer expired — the scheduled sale has ended.';document.querySelector('.price').textContent='₹2,999';}}}}
render(); setInterval(render,1000);"""
    return _behavior_page("Genuine shared countdown", body, script)


@router.get("/behavior-benchmarks/fake-countdown", response_class=HTMLResponse)
def fake_countdown_benchmark() -> HTMLResponse:
    body = """<section class="product"><div class="photo">⌚</div><div><h1>Visitor-only flash deal</h1><p class="price">₹1,999</p>
<p>Hurry! This special offer disappears when the timer reaches zero.</p><div id="sale-countdown" class="timer">00:08</div>
<p id="offer-state">Special offer — 40% off. Buy now.</p><button type="button">View product details</button></div></section>"""
    script = """let remaining = 8; const timer = document.querySelector('#sale-countdown');
function render(){timer.textContent=`00:${String(remaining).padStart(2,'0')}`;remaining -= 1;if(remaining < 0){remaining = 8;}}
render(); setInterval(render,1000);"""
    return _behavior_page("Resetting countdown", body, script)


@router.get("/behavior-benchmarks/manipulative-store", response_class=HTMLResponse)
def manipulative_store_benchmark() -> HTMLResponse:
    body = """<section class="product"><div class="photo">📱</div><div><h1>Ultimate phone bundle</h1><p class="price">₹19,999</p>
<div id="sale-countdown" class="timer">00:08</div><p id="offer-state">Limited time special offer — buy now before it expires.</p>
<p class="claim" data-testid="stock-claim">Only 2 left available — selling fast!</p><p class="claim" data-testid="viewer-claim">17 people are viewing this item</p>
<div class="choices"><label><input id="insurance" type="checkbox" checked> Add device protection insurance ₹499</label>
<label><input id="marketing" type="checkbox" checked> Send me marketing offers and partner newsletters</label>
<label><input id="membership" type="checkbox" checked> Start Premium membership</label></div>
<a class="cta" href="/behavior-benchmarks/subscription-started">Continue</a>
<p class="fineprint">Premium is a recurring subscription at ₹999 per month and auto-renews until cancelled. A processing fee is added at checkout.</p></div></section>
<aside class="consent"><b>We value your privacy</b><p>Allow tracking to personalize offers.</p><button class="accept">Accept all</button> <button class="reject">Reject all</button></aside>"""
    script = """let remaining = 8;const timer=document.querySelector('#sale-countdown');
function tick(){timer.textContent=`00:${String(remaining).padStart(2,'0')}`;remaining--;if(remaining<0)remaining=8;}tick();setInterval(tick,1000);
function nag(){const box=document.createElement('section');box.className='popup';box.setAttribute('role','dialog');box.innerHTML='<h2>Wait! Get 10% off</h2><p>Subscribe to our newsletter before you leave.</p>';document.body.appendChild(box);setTimeout(()=>box.remove(),1100);}
setTimeout(nag,1200);setTimeout(nag,4200);setTimeout(nag,7200);"""
    return _behavior_page("Manipulative research storefront", body, script)


@router.get("/behavior-benchmarks/subscription-started", response_class=HTMLResponse)
def misleading_destination_benchmark() -> HTMLResponse:
    return _behavior_page("Subscription destination", "<h1>Subscription checkout</h1><p>No action was performed by the analyzer.</p>", "")


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
body{{font-family:system-ui,sans-serif;background:#f7f8fc;color:#171923;margin:0}}main{{max-width:720px;margin:70px auto;padding:36px;background:white;border:1px solid #d9deea;border-radius:18px;box-shadow:0 18px 55px #24314d18}}
h1{{margin-top:0}}a,button{{display:inline-block;background:#3157d5;color:white;padding:12px 18px;border:0;border-radius:9px;text-decoration:none;font-weight:700;cursor:pointer}}input{{display:block;width:100%;box-sizing:border-box;padding:12px;margin:14px 0;border:1px solid #abb4c7;border-radius:8px}}.muted{{color:#687086}}.quiet{{font-size:10px;opacity:.42;background:#687086}}
</style></head><body><main><h1>{title}</h1>{body}</main></body></html>"""
    )


@router.get("/benchmarks/{variant}", response_class=HTMLResponse)
def benchmark_start(variant: str) -> HTMLResponse:
    if variant not in {"fair", "obstructed"}:
        raise HTTPException(status_code=404, detail="Unknown benchmark")
    return _page(
        "Account setup",
        f'<p>Create a research benchmark account.</p><a data-flow="create" href="/benchmarks/{variant}/dashboard">Create account</a>',
    )


@router.get("/benchmarks/{variant}/dashboard", response_class=HTMLResponse)
def benchmark_dashboard(variant: str) -> HTMLResponse:
    if variant == "fair":
        control = '<a data-flow="delete" href="/benchmarks/fair/deleted">Delete account</a>'
    elif variant == "obstructed":
        control = '<a data-flow="settings" href="/benchmarks/obstructed/settings">Settings</a>'
    else:
        raise HTTPException(status_code=404, detail="Unknown benchmark")
    return _page("Account ready", f"<p>Your benchmark account is active.</p>{control}")


@router.get("/benchmarks/obstructed/settings", response_class=HTMLResponse)
def benchmark_settings() -> HTMLResponse:
    return _page("Settings", '<p>Notification and profile settings.</p><a data-flow="account" href="/benchmarks/obstructed/account">Account controls</a>')


@router.get("/benchmarks/obstructed/account", response_class=HTMLResponse)
def benchmark_account() -> HTMLResponse:
    return _page(
        "Account controls",
        '<p class="muted">Manage your account.</p><a class="quiet" data-flow="delete" href="/benchmarks/obstructed/reason">Delete account</a>',
    )


@router.get("/benchmarks/obstructed/reason", response_class=HTMLResponse)
def benchmark_reason() -> HTMLResponse:
    return _page(
        "Tell us why you are leaving",
        '<p>A reason for deleting your account is required.</p><input required data-flow="reason" aria-label="Reason for deleting"><a data-flow="reason-next" href="/benchmarks/obstructed/offer">Continue</a>',
    )


@router.get("/benchmarks/obstructed/offer", response_class=HTMLResponse)
def benchmark_offer() -> HTMLResponse:
    return _page(
        "Before you go",
        '<p>Stay with us and keep your account. Claim a special offer instead.</p><a data-flow="reject-offer" href="/benchmarks/obstructed/confirm-one">No, continue deleting</a>',
    )


@router.get("/benchmarks/obstructed/confirm-one", response_class=HTMLResponse)
def benchmark_confirm_one() -> HTMLResponse:
    return _page(
        "Are you sure?",
        '<p>Your account will be permanently deleted and this cannot be undone.</p><a data-flow="confirm-one" href="/benchmarks/obstructed/confirm-two">Confirm deletion</a>',
    )


@router.get("/benchmarks/obstructed/confirm-two", response_class=HTMLResponse)
def benchmark_confirm_two() -> HTMLResponse:
    return _page(
        "Last chance",
        '<p>Are you sure you really want to leave?</p><a data-flow="confirm-two" href="/benchmarks/obstructed/deleted">Yes, delete account</a>',
    )


@router.get("/benchmarks/{variant}/deleted", response_class=HTMLResponse)
def benchmark_deleted(variant: str) -> HTMLResponse:
    if variant not in {"fair", "obstructed"}:
        raise HTTPException(status_code=404, detail="Unknown benchmark")
    return _page("Account deleted", '<p>The benchmark account has been removed.</p><a href="/flow-analysis">Return to analysis</a>')

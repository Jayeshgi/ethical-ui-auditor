"use strict";

const SCENARIOS = [
  ["genuine-countdown", "Genuine countdown", "Counter-evidence: shared absolute deadline"],
  ["fake-countdown", "Resetting countdown", "resetting_countdown + non_expiring_offer"],
  ["session-deadline", "Session-relative deadline", "session_relative_deadline"],
  ["scarcity", "Fabricated scarcity", "fabricated_scarcity"],
  ["social-proof", "Fabricated social proof", "fabricated_social_proof"],
  ["preselection", "Preselected optional choices", "preselected_option"],
  ["hidden-rejection", "Hidden rejection", "hidden_rejection"],
  ["silent-cart-addition", "Silent cart addition", "silent_cart_addition"],
  ["late-price", "Late price disclosure", "late_price_disclosure"],
  ["nagging", "Repeated nagging", "repeated_nagging"],
  ["misleading-action", "Misleading action", "misleading_action"],
  ["subscription-disclosure", "Weak recurring terms", "subscription_disclosure"]
];

const OBSTRUCTIONS = [
  ["channel-switch", "Channel switching"],
  ["forced-contact", "Forced contact"],
  ["delayed-execution", "Delayed execution"],
  ["redirect-loop-a", "Redirect loop"],
  ["dead-end", "Dead end"],
  ["form-burden", "Unnecessary form burden"],
  ["information-overload", "Information overload"],
  ["policy-mismatch", "Policy/interface mismatch"]
];

const LIMITATIONS = {
  captcha: ["CAPTCHA required", "Complete the CAPTCHA challenge to continue. Automated execution cannot solve this synthetic boundary."],
  mfa: ["MFA required", "Enter the one-time authentication code to continue. Multi-factor authentication is required."],
  "email-verification": ["Email verification required", "Check your email and follow the verification link before continuing."],
  "payment-required": ["Payment required", "A payment method is required to continue. This benchmark never accepts real card details."],
  "external-idp": ["External identity provider", "Continue with an external identity provider to access account settings."],
  "bot-protection": ["Bot protection detected", "Automated traffic verification must be completed before this journey can continue."],
  "rate-limited": ["Rate limited", "Too many requests. Try again later after the temporary rate limit expires."],
  "native-app": ["Native app required", "This action can only be completed in the DealCart mobile app."]
};

function renderScenario(name) {
  if (name === "genuine-countdown") {
    app.innerHTML = `${timerRegion("genuine")}<section class="panel"><h1>Shared campaign deadline</h1><p>This deadline comes from the server and remains identical across reloads and independent browser sessions. The offer becomes unavailable after expiry.</p></section>`;
    startCountdown("genuine");
    return;
  }
  if (name === "fake-countdown") {
    app.innerHTML = `${timerRegion("fake")}<section class="panel"><h1>Visitor-relative flash deal</h1><p>Every page load receives a fresh twelve-second deadline. The advertised offer remains active even after the timer reaches zero.</p><button type="button">Claim offer after timer expires</button></section>`;
    startCountdown("fake");
    return;
  }
  if (name === "session-deadline") {
    app.innerHTML = `${timerRegion("session")}<section class="panel"><h1>Fresh deadline for every visitor</h1><p>The deadline persists during one synthetic session but a clean browser receives a new duration.</p></section>`;
    startCountdown("session");
    return;
  }
  if (name === "scarcity") {
    app.innerHTML = `<section class="panel"><span class="pill">Inventory pressure experiment</span><h1>Popular technology is almost gone</h1><div class="grid">${PRODUCTS.slice(0, 3).map((product, index) => productCard(product, { scarcity: true, stock: index + 1 })).join("")}</div></section>`;
    return;
  }
  if (name === "social-proof") {
    app.innerHTML = `<section class="panel"><h1>Live shopping activity</h1><div class="evidence-row"><span class="evidence-chip"><i class="pulse"></i> 37 people are viewing this right now</span><span class="evidence-chip">Someone purchased this 30 seconds ago</span><span class="evidence-chip warning">Popular in your area</span></div><p>These deterministic messages are repeated across sessions without real visitor data.</p></section>`;
    return;
  }
  if (name === "preselection") {
    app.innerHTML = `<section class="flow-shell panel"><h1>Optional checkout preferences</h1><label class="choice-card paid"><input type="checkbox" checked><span><strong>Add paid protection for ₹99</strong><small>Optional add-on selected initially</small></span></label><label class="choice-card"><input type="checkbox" checked><span><strong>Receive promotional emails</strong><small>Optional marketing</small></span></label><label class="choice-card"><input type="checkbox" checked><span><strong>Share activity with partners</strong><small>Optional data sharing</small></span></label></section>`;
    return;
  }
  if (name === "hidden-rejection") {
    app.innerHTML = `<section class="flow-shell panel"><h1>Cookie preferences</h1><p>Personalised tracking helps DealCart recommend products.</p><div class="dialog-actions"><button type="button">Accept all cookies</button><button type="button" class="hidden-reject">Reject optional cookies</button></div></section>`;
    return;
  }
  if (name === "silent-cart-addition") {
    const product = PRODUCTS[0];
    app.innerHTML = `<section class="flow-shell panel"><h1>Silent cart addition experiment</h1><p>Add one product, then inspect the cart for an unrequested paid plan.</p>${productCard(product)}<div id="scenario-cart">${state.cart.map(cartItem).join("")}</div></section>`;
    return;
  }
  if (name === "late-price") {
    const revealed = state.checkoutStep >= 3;
    app.innerHTML = `<section class="flow-shell panel"><h1>Review your order</h1><p>The initial advertised total is ₹9,999.</p><div class="price-summary"><div class="price-line"><span>Product subtotal</span><span>₹9,999</span></div>${revealed ? '<div class="price-line late-fee"><span>Convenience fee</span><span>₹49</span></div><div class="price-line late-fee"><span>Handling fee</span><span>₹29</span></div><div class="price-line late-fee"><span>Platform fee</span><span>₹19</span></div><div class="price-line total"><span>Final total</span><span>₹10,096</span></div>' : '<div class="price-line total"><span>Displayed total</span><span>₹9,999</span></div>'}</div>${revealed ? '<p class="fair-disclosure">Demo payment only — no money will be charged.</p>' : '<button type="button" data-action="checkout-step" data-step="3">Continue to final review</button>'}</section>`;
    return;
  }
  if (name === "nagging") {
    app.innerHTML = `<section class="panel"><h1>Repeated promotion experiment</h1><p>Dismiss the promotional dialog. It returns after a deterministic delay.</p><p>Dismissal count: <strong>${state.nagDismissals}</strong></p></section>`;
    scheduleNag(true);
    return;
  }
  if (name === "misleading-action") {
    app.innerHTML = `<section class="flow-shell panel"><h1>Delivery details complete</h1><p>The next control appears to continue checkout but opens an unrelated membership offer.</p><button type="button" data-action="misleading">Continue to delivery</button></section>`;
    return;
  }
  if (name === "subscription-disclosure") {
    app.innerHTML = `<section class="flow-shell panel"><span class="pill">VIP membership</span><h1>30-Day Free Trial</h1><p class="price">₹0 today</p><p class="weak-disclosure">Then ₹199 every month. Automatically renews until cancelled. Recurring membership charges apply.</p><button type="button">Start free trial</button></section>`;
    return;
  }
  renderNotFound();
}

function renderLimitation(name) {
  const item = LIMITATIONS[name];
  if (!item) return renderNotFound();
  app.innerHTML = `<section class="flow-shell panel limitation-card"><span class="pill">Synthetic execution boundary</span><h1>${item[0]}</h1><p>${item[1]}</p><p class="muted">This page intentionally stops automation and must be reported as a limitation, not proof of a dark pattern.</p></section>`;
}

function scheduleNag(force = false) {
  if (!force && state.nagDismissals > 1) return;
  nagHandle = setTimeout(showNag, state.nagDismissals ? 1800 : 1200);
}

function showNag() {
  modalRoot.innerHTML = `<div class="dialog-backdrop"><section class="dialog" role="dialog" aria-modal="true" aria-labelledby="nag-title"><span class="pill">Last chance</span><h2 id="nag-title">Wait! Save 30% before you go</h2><p>Claim this exclusive offer now. Do not leave money on the table.</p><div class="dialog-actions"><button type="button">Claim my discount</button><button type="button" class="hidden-reject" data-action="dismiss-nag">No thanks, I prefer paying full price</button></div></section></div>`;
}

function renderLab() {
  const flowRows = Object.entries(FLOWS).map(([slug, item]) => `<tr><td>${escapeHtml(item.family)}</td><td>${escapeHtml(item.acquireLabel)} → ${escapeHtml(item.exitLabel)}</td><td><a href="${route(`/flows/${slug}`)}">Open flow</a></td></tr>`).join("");
  const scenarioRows = SCENARIOS.map(([slug, title, expected]) => `<tr><td>${escapeHtml(title)}</td><td>${escapeHtml(expected)}</td><td><a href="${route(`/scenarios/${slug}`)}">Open scenario</a></td></tr>`).join("");
  const obstructionRows = OBSTRUCTIONS.map(([slug, title]) => `<tr><td>${escapeHtml(title)}</td><td>${escapeHtml(slug.replaceAll("-", "_"))}</td><td><a href="${route(`/flows/obstructions/${slug}`)}">Open mechanism</a></td></tr>`).join("");
  const limitationRows = Object.entries(LIMITATIONS).map(([slug, item]) => `<tr><td>${escapeHtml(item[0])}</td><td>Execution limitation</td><td><a href="${route(`/limitations/${slug}`)}">Open boundary</a></td></tr>`).join("");
  app.innerHTML = `<section class="panel"><span class="pill">Not linked from normal store journeys</span><h1>DealCart benchmark control centre</h1><p>Use this page to select isolated, deterministic research cases. The normal scanner should target a scenario or flow URL directly.</p><div class="hero-actions"><a class="button" href="/manipulative">Manipulative store</a><a class="button secondary" href="/fair">Fair control</a><button type="button" class="danger" data-action="reset">Reset session</button></div></section>
  <section class="panel"><h2>Paired flows</h2><table class="lab-table"><thead><tr><th>Family</th><th>Actions</th><th>URL</th></tr></thead><tbody>${flowRows}</tbody></table></section>
  <section class="panel"><h2>Runtime scenarios</h2><table class="lab-table"><thead><tr><th>Scenario</th><th>Expected evidence</th><th>URL</th></tr></thead><tbody>${scenarioRows}</tbody></table></section>
  <section class="panel"><h2>Obstruction mechanisms</h2><table class="lab-table"><tbody>${obstructionRows}</tbody></table></section>
  <section class="panel"><h2>Automation limitations</h2><table class="lab-table"><tbody>${limitationRows}</tbody></table></section>`;
}

function renderNotFound() {
  app.innerHTML = `<section class="panel"><h1>Benchmark route not found</h1><p><a href="/lab">Open the scenario directory</a>.</p></section>`;
}

async function enableDebugPanel() {
  if (params.get("debug") !== "true") return;
  try {
    const manifest = await api("/benchmark-manifest.json");
    const matches = manifest.cases.filter(item => item.path === routePath || (item.path === "/manipulative" && routePath === "/manipulative"));
    const panel = document.createElement("aside");
    panel.className = "panel";
    panel.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:200;width:min(420px,calc(100% - 32px));max-height:55vh;overflow:auto;border:2px solid #f044a7";
    panel.innerHTML = `<h2>Ground-truth debug panel</h2><p class="muted">Never use this URL for model evaluation.</p>${matches.map(item => `<div class="choice-card"><span><strong>${escapeHtml(item.category)}</strong><small>${escapeHtml(item.expected)} · ${escapeHtml(item.selector)}</small></span></div>`).join("") || '<p>No manifest cases for this route.</p>'}`;
    document.body.appendChild(panel);
  } catch (error) {
    console.warn("Debug manifest unavailable", error);
  }
}

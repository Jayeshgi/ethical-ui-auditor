"use strict";

const PRODUCTS = window.DEALCART_PRODUCTS;
const FLOWS = window.DEALCART_FLOW_DEFINITIONS;
const app = document.getElementById("app");
const modalRoot = document.getElementById("modal-root");
const params = new URLSearchParams(location.search);
const routePath = normalizeLegacyPath(location.pathname);
const variant = routePath === "/fair" ? "fair" : routePath === "/manipulative" ? "manipulative" : (params.get("variant") === "fair" ? "fair" : "manipulative");
let state = null;
let timerHandles = [];
let nagHandle = null;

function normalizeLegacyPath(pathname) {
  const aliases = {
    "/index.html": "/manipulative",
    "/products.html": "/products",
    "/product-details.html": "/products",
    "/cart.html": "/cart",
    "/checkout.html": "/checkout",
    "/premium.html": "/flows/subscription",
    "/account.html": "/flows/account"
  };
  return aliases[pathname] || pathname.replace(/\/$/, "") || "/manipulative";
}

function route(path) {
  if (path === "/fair" || path === "/manipulative" || path === "/lab") return path;
  return `${path}?variant=${variant}`;
}

function money(value) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(value);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"]/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[character]));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) }
  });
  if (!response.ok) throw new Error((await response.json()).error || `Request failed: ${response.status}`);
  return response.json();
}

async function action(actionName, details = {}) {
  const result = await api("/api/benchmark/action", {
    method: "POST",
    body: JSON.stringify({ action: actionName, variant, ...details })
  });
  state = result.state;
  return state;
}

function clearRuntime() {
  timerHandles.forEach(clearInterval);
  timerHandles = [];
  if (nagHandle) clearTimeout(nagHandle);
  nagHandle = null;
  modalRoot.innerHTML = "";
}

function productById(id) {
  return PRODUCTS.find(product => product.id === id);
}

function productCard(product, options = {}) {
  const manipulative = variant === "manipulative";
  const sponsored = manipulative && options.sponsored;
  return `
    <article class="card product-card" data-testid="product-${product.id}">
      ${sponsored ? '<span class="sponsored">Promoted</span>' : ""}
      <div class="product-art ${product.tone}" role="img" aria-label="${escapeHtml(product.name)} illustration">${product.icon}</div>
      <div class="product-content">
        <span class="pill">${escapeHtml(product.category)}</span>
        <h3>${escapeHtml(product.name)}</h3>
        <p>${escapeHtml(product.description)}</p>
        ${manipulative && options.scarcity ? `<div class="scarcity">Only ${options.stock || 2} left — selling fast!</div>` : '<div class="muted">Available for this synthetic demonstration</div>'}
        <div><span class="price">${money(product.price)}</span> ${manipulative ? `<span class="strike">${money(product.price * 1.35)}</span>` : ""}</div>
        <button type="button" data-action="add-cart" data-product="${product.id}" data-price="${product.price}">Add to Cart</button>
      </div>
    </article>`;
}

function timerRegion(kind) {
  const isGenuine = kind === "genuine";
  return `
    <section class="urgency-region" data-testid="${kind}-timer-region" aria-label="${isGenuine ? "Genuine campaign deadline" : "Limited time sale countdown"}">
      <span>${isGenuine ? "Scheduled campaign closes at its shared deadline" : "FLASH SALE — offer ends soon"}</span>
      <time class="countdown" data-countdown="${kind}" aria-live="off">00:00:12</time>
      <span data-offer-status>${isGenuine ? "Campaign active" : "Deal remains active"}</span>
    </section>`;
}

function renderStore() {
  const manipulative = variant === "manipulative";
  app.innerHTML = `
    ${timerRegion(manipulative ? "fake" : "genuine")}
    <section class="hero">
      <div class="hero-copy">
        <span class="pill">Technology for every setup</span>
        <h1>${manipulative ? "The deal everyone is rushing to claim." : "Technology with clear prices and choices."}</h1>
        <p>${manipulative ? "Act now before these exclusive prices disappear. Thousands of members are upgrading today." : "Compare devices, understand the full price and choose only the services you want."}</p>
        <div class="hero-actions">
          <a class="button" href="${route("/products")}">Shop technology</a>
          <a class="button secondary" href="${route("/flows/subscription")}">${manipulative ? "Start free VIP trial" : "Review VIP membership"}</a>
        </div>
        ${manipulative ? `
          <div class="evidence-row">
            <span class="evidence-chip"><i class="pulse"></i> 37 people are viewing this right now</span>
            <span class="evidence-chip warning">High demand — almost sold out</span>
            <span class="evidence-chip">Someone purchased this 30 seconds ago</span>
          </div>` : '<p class="fair-disclosure">No live-viewer or inventory claims are used in the fair control.</p>'}
      </div>
      <div class="visual-console" aria-label="Featured laptop illustration"><div class="device"></div></div>
    </section>

    <div class="section-head"><div><h2>Featured technology</h2><p>${manipulative ? "Popular products with urgent promotional cues" : "The same products without pressure cues"}</p></div></div>
    <section class="grid" aria-label="Featured products">
      ${PRODUCTS.slice(0, 4).map((product, index) => productCard(product, { scarcity: index < 3, stock: index + 1, sponsored: index === 3 })).join("")}
    </section>

    <div class="section-head"><div><h2>Preferences and optional extras</h2><p>Controlled form presentation for runtime analysis.</p></div></div>
    <section class="grid two">
      <div class="panel" id="default-choice-region">
        <h3>Checkout preferences</h3>
        <label class="choice-card paid">
          <input id="care-plan-choice" type="checkbox" ${manipulative ? "checked" : ""}>
          <span><strong>Add DealCart Care for ₹99</strong><small>Optional synthetic product-protection plan</small></span>
        </label>
        <label class="choice-card">
          <input id="marketing-choice" type="checkbox" ${manipulative ? "checked" : ""}>
          <span><strong>Receive promotional emails</strong><small>Optional marketing communication</small></span>
        </label>
        <label class="choice-card">
          <input id="sharing-choice" type="checkbox" ${manipulative ? "checked" : ""}>
          <span><strong>Share shopping activity with partners</strong><small>Optional third-party data sharing</small></span>
        </label>
      </div>
      <div class="panel" id="consent-region">
        <h3>Shopping privacy</h3>
        <p>${manipulative ? "Accept personalisation to unlock the fastest DealCart experience." : "Choose whether optional personalisation may be used."}</p>
        <div class="dialog-actions">
          <button type="button" data-action="consent-accept">Accept all</button>
          <button type="button" class="${manipulative ? "hidden-reject" : "secondary"}" data-action="consent-reject">Reject optional cookies</button>
        </div>
      </div>
    </section>`;
  startCountdown(manipulative ? "fake" : "genuine");
  if (manipulative) scheduleNag();
}

function renderProducts() {
  app.innerHTML = `
    <div class="section-head"><div><span class="pill">Complete catalogue</span><h1>Technology products</h1><p>Local synthetic product artwork keeps tests deterministic and offline.</p></div></div>
    <section class="grid">${PRODUCTS.map((product, index) => productCard(product, { scarcity: index % 2 === 0, stock: (index % 4) + 1, sponsored: index === 4 })).join("")}</section>`;
}

function cartTotal() {
  return state.cart.reduce((sum, item) => sum + Number(item.price || 0) * Number(item.quantity || 1), 0);
}

function cartItem(item) {
  const product = productById(item.id);
  const name = item.id === "care-plan" ? "DealCart Care protection plan" : (product ? product.name : item.id);
  return `<div class="choice-card ${item.addedByUser ? "" : "paid"}" data-testid="cart-item-${escapeHtml(item.id)}">
    <span><strong>${escapeHtml(name)}</strong><small>${item.addedByUser ? "Added by your action" : "Added automatically without a separate selection"}</small></span>
    <span class="price">${money(item.price)}</span>
    <button class="ghost small" type="button" data-action="remove-cart" data-product="${escapeHtml(item.id)}">Remove</button>
  </div>`;
}

function renderCart() {
  const total = cartTotal();
  app.innerHTML = `<section class="panel">
    <span class="pill">Synthetic cart</span><h1>Your DealCart cart</h1>
    ${state.cart.length ? state.cart.map(cartItem).join("") : '<p class="muted">Your cart is empty. Add a product to begin the mock purchase flow.</p>'}
    <div class="price-summary"><div class="price-line total"><span>Cart total</span><span>${money(total)}</span></div></div>
    <div class="hero-actions"><a class="button secondary" href="${route("/products")}">Continue shopping</a>${state.cart.length ? `<a class="button" href="${route("/checkout")}">Continue to checkout</a>` : ""}</div>
  </section>`;
}

function renderCheckout() {
  const subtotal = cartTotal();
  const fees = 97;
  const step = state.checkoutStep || 1;
  const manipulative = variant === "manipulative";
  const showFees = !manipulative || step >= 3;
  app.innerHTML = `<section class="panel">
    <span class="pill">Demo payment — no money will be charged</span>
    <h1>Mock checkout · step ${step} of 3</h1>
    ${step === 1 ? `<div class="form-grid"><label>Full name<input value="Alex Researcher" autocomplete="off"></label><label>Delivery postcode<input value="000000" autocomplete="off"></label></div><button type="button" data-action="checkout-step" data-step="2">Continue to delivery</button>` : ""}
    ${step === 2 ? `<p>Standard synthetic delivery has been selected.</p><button type="button" data-action="checkout-step" data-step="3">Continue to review order</button>` : ""}
    ${step === 3 ? `<h2>Review order</h2><button type="button" data-action="place-order">Place demo order</button>` : ""}
    <aside class="price-summary" id="checkout-price-summary">
      <div class="price-line"><span>Product subtotal</span><span>${money(subtotal)}</span></div>
      ${showFees ? '<div class="price-line late-fee"><span>Convenience fee</span><span>₹49</span></div><div class="price-line late-fee"><span>Handling fee</span><span>₹29</span></div><div class="price-line late-fee"><span>Platform fee</span><span>₹19</span></div>' : '<p class="fine-print">Additional processing charges may apply later.</p>'}
      <div class="price-line total"><span>${showFees ? "Final total" : "Current displayed total"}</span><span>${money(subtotal + (showFees ? fees : 0))}</span></div>
    </aside>
  </section>`;
}

async function startCountdown(kind) {
  const endpoint = kind === "genuine" ? "/api/benchmark/genuine-deadline" : kind === "session" ? "/api/benchmark/session-deadline" : "/api/benchmark/fake-deadline";
  const config = await api(endpoint);
  const deadline = Date.parse(config.deadline);
  const node = document.querySelector(`[data-countdown="${kind}"]`);
  if (!node) return;
  const statusNode = node.closest(".urgency-region")?.querySelector("[data-offer-status]");
  const tick = () => {
    const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
    const hours = Math.floor(remaining / 3600);
    const minutes = Math.floor((remaining % 3600) / 60);
    const seconds = remaining % 60;
    node.textContent = `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    if (remaining === 0 && statusNode) statusNode.textContent = kind === "genuine" ? "Campaign ended — offer unavailable" : "Deal remains active — timer restarting soon";
  };
  tick();
  timerHandles.push(setInterval(tick, 1000));
}

// FLOW_AND_SCENARIO_RENDERERS

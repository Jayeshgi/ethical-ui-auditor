"use strict";

function toast(message) {
  const root = document.getElementById("toast-root");
  root.innerHTML = `<div class="toast">${escapeHtml(message)}</div>`;
  setTimeout(() => { root.innerHTML = ""; }, 2200);
}

function updateChrome() {
  const badge = document.getElementById("variant-badge");
  badge.textContent = variant === "fair" ? "Fair control" : "Manipulative benchmark";
  badge.classList.toggle("fair", variant === "fair");
  document.getElementById("cart-count").textContent = state.cart.reduce((sum, item) => sum + Number(item.quantity || 1), 0);
  document.querySelectorAll("[data-app-link]").forEach(link => {
    const target = link.dataset.appLink;
    link.href = target === "/manipulative" ? (variant === "fair" ? "/fair" : "/manipulative") : route(target);
  });
}

function renderCurrentRoute() {
  clearRuntime();
  updateChrome();
  if (["/", "/fair", "/manipulative"].includes(routePath)) renderStore();
  else if (routePath === "/products") renderProducts();
  else if (routePath === "/cart") renderCart();
  else if (routePath === "/checkout") renderCheckout();
  else if (routePath === "/premium") renderFlow("subscription");
  else if (routePath === "/account") renderFlow("account");
  else if (routePath === "/lab") renderLab();
  else if (routePath.startsWith("/flows/obstructions/")) renderObstruction(routePath.split("/").pop());
  else if (routePath.startsWith("/flows/")) renderFlow(routePath.split("/").pop());
  else if (routePath.startsWith("/scenarios/")) renderScenario(routePath.split("/").pop());
  else if (routePath.startsWith("/limitations/")) renderLimitation(routePath.split("/").pop());
  else renderNotFound();
}

document.addEventListener("click", async event => {
  const control = event.target.closest("[data-action]");
  if (!control) return;
  event.preventDefault();
  const name = control.dataset.action;
  try {
    if (name === "add-cart") {
      await action("cart:add", { productId: control.dataset.product, price: Number(control.dataset.price) });
      updateChrome();
      if (routePath.includes("silent-cart-addition")) renderCurrentRoute();
      toast(variant === "manipulative" ? "Product added. Your cart may contain an extra plan." : "Product added to cart.");
    } else if (name === "remove-cart") {
      await action("cart:remove", { productId: control.dataset.product });
      renderCurrentRoute();
    } else if (name === "checkout-step") {
      await action("checkout:step", { step: Number(control.dataset.step) });
      renderCurrentRoute();
    } else if (name === "place-order") {
      await action("flow:acquire", { goal: "purchase-return" });
      location.assign(route("/flows/purchase-return"));
    } else if (name === "flow-acquire") {
      await action("flow:acquire", { goal: control.dataset.goal });
      renderCurrentRoute();
    } else if (name === "flow-progress") {
      await action("flow:progress", { goal: control.dataset.goal, step: Number(control.dataset.step) });
      renderCurrentRoute();
    } else if (name === "flow-exit") {
      await action("flow:exit", { goal: control.dataset.goal });
      renderCurrentRoute();
    } else if (name === "dismiss-nag") {
      await action("nag:dismiss");
      modalRoot.innerHTML = "";
      scheduleNag(true);
    } else if (name === "misleading") {
      location.assign(route("/flows/subscription"));
    } else if (name === "reset") {
      const result = await api("/api/benchmark/reset", { method: "POST", body: "{}" });
      state = result.state;
      renderCurrentRoute();
      toast("Synthetic session reset.");
    } else if (name === "consent-accept") {
      toast("Optional consent accepted.");
    } else if (name === "consent-reject") {
      toast("Optional consent rejected.");
    }
  } catch (error) {
    toast(`Benchmark action failed: ${error.message}`);
  }
});

async function boot() {
  try {
    state = await api("/api/benchmark/state");
    renderCurrentRoute();
    await enableDebugPanel();
  } catch (error) {
    app.innerHTML = `<section class="panel limitation-card"><h1>DealCart could not start</h1><p>${escapeHtml(error.message)}</p></section>`;
  }
}

boot();

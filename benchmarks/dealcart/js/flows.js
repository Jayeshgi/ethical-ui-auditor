"use strict";

function flowProgress(count, active) {
  return `<div class="flow-progress" aria-label="Exit progress">${Array.from({ length: count }, (_, index) => `<span class="${index < active ? "active" : ""}"></span>`).join("")}</div>`;
}

function flowState(goal) {
  return state.flows[goal] || { acquired: false, exited: false, step: 0 };
}

function renderFlow(goal) {
  const definition = FLOWS[goal];
  if (!definition) return renderNotFound();
  const current = flowState(goal);
  const manipulative = variant === "manipulative";
  const isPrimary = goal === "account" || goal === "subscription";

  if (current.exited) {
    app.innerHTML = `<section class="flow-shell success-panel" data-testid="exit-terminal">
      <span class="pill">Exit journey complete</span>
      <h1>${escapeHtml(definition.exited)}</h1>
      <p>The synthetic state change is complete and remains visible for Playwright terminal verification.</p>
      <button type="button" class="secondary" data-action="reset">Reset this research session</button>
    </section>`;
    return;
  }

  if (!current.acquired) {
    app.innerHTML = `<section class="flow-shell panel" data-testid="acquisition-state">
      <span class="pill">Paired-flow benchmark · ${escapeHtml(definition.family)}</span>
      <h1>${escapeHtml(definition.title)}</h1>
      <p>${manipulative ? "Joining is intentionally direct. The equivalent exit journey becomes harder after activation." : "The fair control keeps joining and leaving similarly direct."}</p>
      ${goal === "account" ? '<div class="form-grid"><label>Display name<input name="display-name" value="Demo User" autocomplete="off"></label><label>Research email<input name="email" type="email" value="demo@example.test" autocomplete="off"></label></div>' : ""}
      ${goal === "payment-method" ? '<p class="fair-disclosure">Fictional token ending 4242. Never enter a real payment card.</p>' : ""}
      <button type="button" data-action="flow-acquire" data-goal="${goal}">${escapeHtml(definition.acquireLabel)}</button>
    </section>`;
    return;
  }

  if (!manipulative) {
    app.innerHTML = `<section class="flow-shell">
      <div class="success-panel" data-testid="acquisition-terminal"><h1>${escapeHtml(definition.acquired)}</h1></div>
      <div class="panel"><h2>Manage ${escapeHtml(definition.title)}</h2><p>The exit is available at the same level and prominence as acquisition.</p>
      <button type="button" class="danger" data-action="flow-exit" data-goal="${goal}">${escapeHtml(definition.exitLabel)}</button></div>
    </section>`;
    return;
  }

  if (!isPrimary) return renderModerateObstructionFlow(goal, definition, current);
  renderPrimaryObstructionFlow(goal, definition, current);
}

function renderModerateObstructionFlow(goal, definition, current) {
  const step = current.step || 0;
  let body;
  if (step === 0) body = `<h2>${escapeHtml(definition.acquired)}</h2><p>Your benefit is active.</p><button type="button" data-action="flow-progress" data-goal="${goal}" data-step="1">${escapeHtml(definition.hub)}</button>`;
  else if (step === 1) body = `<h2>${escapeHtml(definition.section)}</h2><div class="overload"><p>Recommended settings, member benefits, saved preferences, promotional explanations and account guidance appear before the exit control.</p><p>Keeping this feature active improves personalised deals, faster support and loyalty recommendations. Review all options carefully before making changes.</p></div><button type="button" class="hidden-exit" data-action="flow-progress" data-goal="${goal}" data-step="2">${escapeHtml(definition.exitLabel)}</button>`;
  else if (step === 2) body = `<h2>Tell us why you are leaving</h2><label>Reason for leaving<textarea id="exit-reason" required>Other</textarea></label><button type="button" data-action="flow-progress" data-goal="${goal}" data-step="3">Continue</button>`;
  else body = `<h2>Are you sure?</h2><p>You will lose saved benefits and personalised recommendations.</p><button type="button" data-action="flow-exit" data-goal="${goal}">Confirm ${escapeHtml(definition.exitLabel.toLowerCase())}</button><button type="button" class="secondary">Keep my benefits</button>`;
  app.innerHTML = `<section class="flow-shell"><div class="success-panel" data-testid="acquisition-terminal"><p>${escapeHtml(definition.acquired)}</p></div>${flowProgress(4, step + 1)}<div class="panel">${body}</div></section>`;
}

function renderPrimaryObstructionFlow(goal, definition, current) {
  const step = current.step || 0;
  const exitNoun = goal === "account" ? "account deletion" : "subscription cancellation";
  let body;
  if (step === 0) {
    body = `<h2>${escapeHtml(definition.acquired)}</h2><p>Your benefits are ready. Changes are located in account management.</p><button type="button" data-action="flow-progress" data-goal="${goal}" data-step="1">${escapeHtml(definition.hub)}</button>`;
  } else if (step === 1) {
    body = `<h2>${escapeHtml(definition.section)}</h2><p>Review billing, privacy, recommendations and saved settings.</p><button type="button" data-action="flow-progress" data-goal="${goal}" data-step="2">Advanced ${goal === "account" ? "privacy" : "billing"} options</button>`;
  } else if (step === 2) {
    body = `<h2>Advanced controls</h2><div class="overload"><h3>Before changing your benefits</h3><p>Members receive priority assistance, personalised technology suggestions, faster delivery, saved configurations, price alerts, reward multipliers and early access.</p><p>Closing this relationship removes historical preferences and may make future setup slower. You can pause notifications, change delivery frequency, review recommendations, update your profile, switch plans or contact support.</p><p>DealCart recommends keeping the service active so you do not miss exclusive technology releases.</p></div><div class="danger-zone"><p>The online policy says: "Cancel online in one simple step."</p><button type="button" class="hidden-exit" data-action="flow-progress" data-goal="${goal}" data-step="3">${escapeHtml(definition.exitLabel)}</button></div>`;
  } else if (step === 3) {
    body = `<h2>Tell us why you are leaving</h2><p>A reason is required before ${escapeHtml(exitNoun)} can continue.</p><div class="form-grid"><label>Reason for leaving<select id="exit-reason" required><option value="">Choose a reason</option><option selected>Other</option></select></label><label>Explain your decision<textarea required>Research benchmark request</textarea></label><label>Confirm account email<input type="email" value="demo@example.test" required></label><label>Benefits used this month<input value="Synthetic evaluation" required></label></div><button type="button" data-action="flow-progress" data-goal="${goal}" data-step="4">Continue cancellation request</button>`;
  } else if (step === 4) {
    body = `<div class="retention panel"><span class="pill">Exclusive retention offer</span><h2>Wait - keep every benefit for 70% less</h2><p>Stay to protect rewards, express delivery and personalised prices.</p><button type="button">Keep my benefits and stay</button><button type="button" class="hidden-exit" data-action="flow-progress" data-goal="${goal}" data-step="5">No, continue ${escapeHtml(exitNoun)}</button></div>`;
  } else if (step === 5) {
    body = `<h2>Are you sure you want to continue?</h2><p>This is the first confirmation. Your saved benefits may be lost.</p><button type="button" data-action="flow-progress" data-goal="${goal}" data-step="6">Confirm cancellation</button><button type="button" class="secondary">Go back and keep my account</button>`;
  } else {
    body = `<h2>Final confirmation required</h2><p>Are you really sure? This is your last chance to keep DealCart benefits.</p><button type="button" class="danger" data-action="flow-exit" data-goal="${goal}">Confirm ${escapeHtml(definition.exitLabel.toLowerCase())}</button><button type="button">Keep my benefits</button>`;
  }
  app.innerHTML = `<section class="flow-shell"><div class="success-panel" data-testid="acquisition-terminal"><p>${escapeHtml(definition.acquired)}</p></div>${flowProgress(7, step + 1)}<div class="panel">${body}</div></section>`;
}

function renderObstruction(name) {
  const pages = {
    "channel-switch": ["Cancellation requires another channel", "Call support to cancel. Cancellation cannot be completed online.", "channel_switch"],
    "forced-contact": ["Contact is mandatory", "Speak with an agent to close your account. There is no self-service option.", "forced_contact"],
    "delayed-execution": ["Exit request received", "Account deletion scheduled within 30 days. Your account remains active until then.", "delayed_execution"],
    "dead-end": ["Manage cancellation", "You reached the final account page, but no completion control is available.", "dead_end"],
    "form-burden": ["Additional exit information", "Complete multiple unnecessary fields before the exit request can be considered.", "unnecessary_form_burden"],
    "information-overload": ["Review every alternative", "The exit option is buried among extensive retention explanations and unrelated choices.", "information_overload"],
    "policy-mismatch": ["Easy cancellation policy", "Our policy promises one-step cancellation, while the interface requires several stages.", "policy_interface_mismatch"]
  };
  if (name === "redirect-loop-a" || name === "redirect-loop-b") {
    const next = name.endsWith("a") ? "redirect-loop-b" : "redirect-loop-a";
    app.innerHTML = `<section class="flow-shell panel loop-card"><span class="pill">redirect_loop</span><h1>Verify your cancellation settings</h1><p>This journey repeatedly returns to a previous state without completing cancellation.</p><a class="button" href="${route(`/flows/obstructions/${next}`)}">Continue cancellation</a></section>`;
    return;
  }
  const entry = pages[name];
  if (!entry) return renderNotFound();
  const extra = name === "form-burden" ? '<div class="form-grid"><label>Reason<textarea required></textarea></label><label>Account reference<input required></label><label>Last product viewed<input required></label><label>Preferred callback time<input required></label></div>' : name === "information-overload" ? '<div class="overload"><p>Pause instead, change frequency, update interests, switch delivery, save rewards, contact support, read FAQs, review member history, compare plans and explore twelve alternative settings before leaving.</p><p>DealCart recommends reviewing every benefit and help article before locating account controls.</p></div>' : "";
  app.innerHTML = `<section class="flow-shell panel limitation-card"><span class="pill">${entry[2]}</span><h1>${entry[0]}</h1><p>${entry[1]}</p>${extra}</section>`;
}

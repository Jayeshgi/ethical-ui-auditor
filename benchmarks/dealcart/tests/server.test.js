"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { after, before, test } = require("node:test");
const { createDealCartServer, routeIsApplication, staticPath } = require("../server");

let server;
let base;

before(async () => {
  server = createDealCartServer({ fakeDurationMs: 12_000 });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}`;
});

after(async () => {
  await new Promise(resolve => server.close(resolve));
});

async function newSession() {
  const response = await fetch(`${base}/api/benchmark/state`);
  assert.equal(response.status, 200);
  const cookie = response.headers.get("set-cookie").split(";", 1)[0];
  return { cookie, state: await response.json() };
}

async function post(path, cookie, body) {
  const response = await fetch(`${base}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", cookie },
    body: JSON.stringify(body)
  });
  return { response, json: await response.json() };
}

test("health and application routes are available with security headers", async () => {
  const health = await fetch(`${base}/api/health`);
  assert.equal(health.status, 200);
  assert.equal((await health.json()).service, "dealcart-benchmark");

  for (const path of ["/fair", "/manipulative", "/flows/account", "/flows/obstructions/dead-end", "/scenarios/fake-countdown", "/limitations/mfa", "/lab"]) {
    const response = await fetch(`${base}${path}`);
    assert.equal(response.status, 200, path);
    assert.match(response.headers.get("content-security-policy"), /default-src 'self'/);
    assert.match(await response.text(), /Synthetic research benchmark/);
  }
});

test("route and static-path validation rejects traversal", () => {
  assert.equal(routeIsApplication("/flows/account"), true);
  assert.equal(routeIsApplication("/flows/obstructions/dead-end"), true);
  assert.equal(routeIsApplication("/unknown"), false);
  assert.equal(staticPath("/../server.js"), null);
  assert.equal(staticPath("/%2e%2e/server.js"), null);
  assert.equal(staticPath("/css/styles.css").endsWith("styles.css"), true);
});

test("ground-truth manifest covers every text label, paired flow and limitation", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "benchmark-manifest.json"), "utf8"));
  const cases = manifest.cases;
  const ids = cases.map(item => item.id);
  assert.equal(new Set(ids).size, ids.length, "case IDs must be unique");

  const categories = new Set(cases.map(item => item.category));
  for (const category of [
    "false_urgency", "false_scarcity", "social_proof", "confirm_shaming",
    "fear_or_pressure", "misleading_claim", "subscription_manipulation",
    "forced_consent", "sneaking", "obstruction"
  ]) assert.equal(categories.has(category), true, category);

  const paths = new Set(cases.map(item => item.path));
  for (const slug of [
    "account", "subscription", "newsletter", "consent", "notifications",
    "integration", "payment-method", "loyalty", "data-sharing", "purchase-return"
  ]) assert.equal(paths.has(`/flows/${slug}`), true, slug);
  for (const slug of [
    "captcha", "mfa", "email-verification", "payment-required", "external-idp",
    "bot-protection", "rate-limited", "native-app"
  ]) assert.equal(paths.has(`/limitations/${slug}`), true, slug);
});

test("manipulative cart action silently adds the paid care plan", async () => {
  const { cookie } = await newSession();
  const { response, json } = await post("/api/benchmark/action", cookie, {
    action: "cart:add", variant: "manipulative", productId: "nova-laptop", price: 84999
  });
  assert.equal(response.status, 200);
  assert.deepEqual(json.state.cart.map(item => item.id), ["nova-laptop", "care-plan"]);
  assert.equal(json.state.cart[1].addedByUser, false);
});

test("fair cart action adds only the requested product", async () => {
  const { cookie } = await newSession();
  const { json } = await post("/api/benchmark/action", cookie, {
    action: "cart:add", variant: "fair", productId: "nova-laptop", price: 84999
  });
  assert.deepEqual(json.state.cart.map(item => item.id), ["nova-laptop"]);
});

test("flow state is deterministic and session reset removes it", async () => {
  const { cookie } = await newSession();
  let result = await post("/api/benchmark/action", cookie, { action: "flow:acquire", variant: "manipulative", goal: "account" });
  assert.equal(result.json.state.flows.account.acquired, true);
  result = await post("/api/benchmark/action", cookie, { action: "flow:progress", variant: "manipulative", goal: "account", step: 4 });
  assert.equal(result.json.state.flows.account.step, 4);
  result = await post("/api/benchmark/reset", cookie, {});
  assert.deepEqual(result.json.state.flows, {});
  assert.deepEqual(result.json.state.cart, []);
});

test("genuine deadline is stable while fake deadline is page-relative", async () => {
  const firstGenuine = await (await fetch(`${base}/api/benchmark/genuine-deadline`)).json();
  const secondGenuine = await (await fetch(`${base}/api/benchmark/genuine-deadline`)).json();
  assert.equal(firstGenuine.deadline, secondGenuine.deadline);
  assert.equal(firstGenuine.kind, "absolute");

  const firstFake = await (await fetch(`${base}/api/benchmark/fake-deadline`)).json();
  await new Promise(resolve => setTimeout(resolve, 20));
  const secondFake = await (await fetch(`${base}/api/benchmark/fake-deadline`)).json();
  assert.notEqual(firstFake.deadline, secondFake.deadline);
  assert.equal(firstFake.offerActiveAfterExpiry, true);
});

test("invalid actions and oversized JSON are rejected safely", async () => {
  const { cookie } = await newSession();
  const invalid = await post("/api/benchmark/action", cookie, { action: "unknown" });
  assert.equal(invalid.response.status, 422);
  const malformed = await fetch(`${base}/api/benchmark/action`, {
    method: "POST",
    headers: { "content-type": "application/json", cookie },
    body: "{bad-json"
  });
  assert.equal(malformed.status, 400);
});

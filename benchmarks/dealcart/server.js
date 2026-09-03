"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { URL } = require("node:url");

const ROOT = path.resolve(__dirname);
const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 3000;
const BODY_LIMIT = 64 * 1024;
const SESSION_COOKIE = "dealcart_lab_session";
const VALID_VARIANTS = new Set(["fair", "manipulative"]);
const VALID_GOALS = new Set([
  "account", "subscription", "newsletter", "consent", "notifications",
  "integration", "payment-method", "loyalty", "data-sharing", "purchase-return"
]);

const MIME_TYPES = {
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".ico": "image/x-icon"
};

function freshState() {
  return {
    createdAt: new Date().toISOString(),
    cart: [],
    checkoutStep: 1,
    nagDismissals: 0,
    flows: Object.create(null),
    sessionDeadline: null,
    events: []
  };
}

function parseCookies(header = "") {
  return Object.fromEntries(
    header.split(";").map(part => part.trim()).filter(Boolean).map(part => {
      const index = part.indexOf("=");
      return index < 0 ? [part, ""] : [part.slice(0, index), decodeURIComponent(part.slice(index + 1))];
    })
  );
}

function securityHeaders(contentType) {
  return {
    "Content-Type": contentType,
    "Cache-Control": "no-store, max-age=0",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'"
  };
}

function send(res, status, body, contentType = "text/plain; charset=utf-8", extraHeaders = {}) {
  const payload = Buffer.isBuffer(body) ? body : Buffer.from(String(body), "utf8");
  res.writeHead(status, { ...securityHeaders(contentType), "Content-Length": payload.length, ...extraHeaders });
  res.end(payload);
}

function sendJson(res, status, value, extraHeaders = {}) {
  send(res, status, JSON.stringify(value), MIME_TYPES[".json"], extraHeaders);
}

async function readJson(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > BODY_LIMIT) {
      const error = new Error("Request body is too large.");
      error.statusCode = 413;
      throw error;
    }
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    const error = new Error("Request body must contain valid JSON.");
    error.statusCode = 400;
    throw error;
  }
}

function publicState(state) {
  return {
    createdAt: state.createdAt,
    cart: state.cart.map(item => ({ ...item })),
    checkoutStep: state.checkoutStep,
    nagDismissals: state.nagDismissals,
    flows: JSON.parse(JSON.stringify(state.flows)),
    sessionDeadline: state.sessionDeadline,
    recentEvents: state.events.slice(-20)
  };
}

function record(state, action, details = {}) {
  state.events.push({ action, details, at: new Date().toISOString() });
  if (state.events.length > 100) state.events.splice(0, state.events.length - 100);
}

function validateVariant(value) {
  return VALID_VARIANTS.has(value) ? value : "manipulative";
}

function routeIsApplication(pathname) {
  if (["/", "/fair", "/manipulative", "/products", "/cart", "/checkout", "/premium", "/account", "/lab"].includes(pathname)) return true;
  if (/^\/(?:flows|scenarios|limitations)\/[a-z0-9-]+(?:\/[a-z0-9-]+)?$/.test(pathname)) return true;
  return /^\/(?:index|products|product-details|cart|checkout|premium|account)\.html$/.test(pathname);
}

function staticPath(pathname) {
  if (!/^\/(?:css|js|assets)\/[A-Za-z0-9_./-]+$/.test(pathname) && pathname !== "/benchmark-manifest.json") return null;
  let decoded;
  try {
    decoded = decodeURIComponent(pathname);
  } catch {
    return null;
  }
  const target = path.resolve(ROOT, `.${decoded}`);
  const relative = path.relative(ROOT, target);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) return null;
  return target;
}

function createDealCartServer(options = {}) {
  const sessions = options.sessions || new Map();
  const now = options.now || (() => Date.now());
  const genuineDeadline = options.genuineDeadline || (now() + 24 * 60 * 60 * 1000);
  const fakeDurationMs = options.fakeDurationMs || 12_000;

  function sessionFor(req) {
    const cookies = parseCookies(req.headers.cookie);
    let id = cookies[SESSION_COOKIE];
    let isNew = false;
    if (!id || !/^[a-f0-9-]{36}$/.test(id) || !sessions.has(id)) {
      id = crypto.randomUUID();
      sessions.set(id, freshState());
      isNew = true;
    }
    return { id, state: sessions.get(id), isNew };
  }

  function sessionHeader(session) {
    return session.isNew
      ? { "Set-Cookie": `${SESSION_COOKIE}=${encodeURIComponent(session.id)}; Path=/; HttpOnly; SameSite=Lax` }
      : {};
  }

  const server = http.createServer(async (req, res) => {
    const base = `http://${req.headers.host || `${DEFAULT_HOST}:${DEFAULT_PORT}`}`;
    let requestUrl;
    try {
      requestUrl = new URL(req.url, base);
    } catch {
      sendJson(res, 400, { error: "Invalid URL." });
      return;
    }
    const pathname = requestUrl.pathname;
    const session = sessionFor(req);
    const headers = sessionHeader(session);

    try {
      if (req.method === "GET" && pathname === "/api/health") {
        sendJson(res, 200, { status: "ok", service: "dealcart-benchmark", sessions: sessions.size }, headers);
        return;
      }

      if (req.method === "GET" && pathname === "/api/benchmark/state") {
        sendJson(res, 200, publicState(session.state), headers);
        return;
      }

      if (req.method === "POST" && pathname === "/api/benchmark/reset") {
        sessions.set(session.id, freshState());
        sendJson(res, 200, { status: "reset", state: publicState(sessions.get(session.id)) }, headers);
        return;
      }

      if (req.method === "GET" && pathname === "/api/benchmark/genuine-deadline") {
        sendJson(res, 200, {
          kind: "absolute",
          deadline: new Date(genuineDeadline).toISOString(),
          offerActive: now() < genuineDeadline,
          campaign: "DEALCART-LAB-GENUINE-1"
        }, headers);
        return;
      }

      if (req.method === "GET" && pathname === "/api/benchmark/fake-deadline") {
        const deadline = now() + fakeDurationMs;
        sendJson(res, 200, {
          kind: "page-relative",
          deadline: new Date(deadline).toISOString(),
          initialDurationSeconds: Math.round(fakeDurationMs / 1000),
          offerActiveAfterExpiry: true
        }, headers);
        return;
      }

      if (req.method === "GET" && pathname === "/api/benchmark/session-deadline") {
        if (!session.state.sessionDeadline) session.state.sessionDeadline = now() + 90_000;
        sendJson(res, 200, {
          kind: "session-relative",
          deadline: new Date(session.state.sessionDeadline).toISOString()
        }, headers);
        return;
      }

      if (req.method === "POST" && pathname === "/api/benchmark/action") {
        const body = await readJson(req);
        const variant = validateVariant(body.variant);
        const action = String(body.action || "");

        if (action === "cart:add") {
          const productId = String(body.productId || "").slice(0, 80);
          if (!productId) throw Object.assign(new Error("productId is required."), { statusCode: 422 });
          if (!session.state.cart.some(item => item.id === productId)) {
            session.state.cart.push({ id: productId, quantity: 1, price: Number(body.price) || 0, addedByUser: true });
          }
          if (variant === "manipulative" && !session.state.cart.some(item => item.id === "care-plan")) {
            session.state.cart.push({ id: "care-plan", quantity: 1, price: 99, addedByUser: false });
          }
          record(session.state, action, { productId, variant });
        } else if (action === "cart:remove") {
          const productId = String(body.productId || "");
          session.state.cart = session.state.cart.filter(item => item.id !== productId);
          record(session.state, action, { productId });
        } else if (action === "checkout:step") {
          session.state.checkoutStep = Math.max(1, Math.min(3, Number(body.step) || 1));
          record(session.state, action, { step: session.state.checkoutStep, variant });
        } else if (action === "nag:dismiss") {
          session.state.nagDismissals += 1;
          record(session.state, action, { count: session.state.nagDismissals, variant });
        } else if (["flow:acquire", "flow:progress", "flow:exit"].includes(action)) {
          const goal = String(body.goal || "");
          if (!VALID_GOALS.has(goal)) throw Object.assign(new Error("Unknown goal."), { statusCode: 422 });
          const current = session.state.flows[goal] || { acquired: false, exited: false, step: 0 };
          if (action === "flow:acquire") Object.assign(current, { acquired: true, exited: false, step: 0 });
          if (action === "flow:progress") current.step = Math.max(0, Math.min(8, Number(body.step) || current.step + 1));
          if (action === "flow:exit") Object.assign(current, { acquired: false, exited: true, step: 99 });
          session.state.flows[goal] = current;
          record(session.state, action, { goal, step: current.step, variant });
        } else {
          throw Object.assign(new Error("Unsupported benchmark action."), { statusCode: 422 });
        }
        sendJson(res, 200, { status: "ok", state: publicState(session.state) }, headers);
        return;
      }

      if ((req.method === "GET" || req.method === "HEAD") && routeIsApplication(pathname)) {
        const shell = fs.readFileSync(path.join(ROOT, "index.html"));
        send(res, 200, req.method === "HEAD" ? Buffer.alloc(0) : shell, "text/html; charset=utf-8", headers);
        return;
      }

      if (req.method === "GET" || req.method === "HEAD") {
        const target = staticPath(pathname);
        if (target && fs.existsSync(target) && fs.statSync(target).isFile()) {
          const body = req.method === "HEAD" ? Buffer.alloc(0) : fs.readFileSync(target);
          send(res, 200, body, MIME_TYPES[path.extname(target).toLowerCase()] || "application/octet-stream", headers);
          return;
        }
      }

      sendJson(res, 404, { error: "Route not found." }, headers);
    } catch (error) {
      sendJson(res, error.statusCode || 500, { error: error.statusCode ? error.message : "Internal benchmark error." }, headers);
    }
  });

  server.benchmark = { sessions, genuineDeadline, fakeDurationMs };
  return server;
}

if (require.main === module) {
  const host = process.env.HOST || DEFAULT_HOST;
  const port = Number(process.env.PORT || DEFAULT_PORT);
  const server = createDealCartServer();
  server.listen(port, host, () => {
    console.log("DealCart controlled benchmark is running.");
    console.log(`Store: http://${host}:${port}/manipulative`);
    console.log(`Fair control: http://${host}:${port}/fair`);
    console.log(`Research lab: http://${host}:${port}/lab`);
  });
  const shutdown = () => server.close(() => process.exit(0));
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

module.exports = { createDealCartServer, freshState, routeIsApplication, staticPath };

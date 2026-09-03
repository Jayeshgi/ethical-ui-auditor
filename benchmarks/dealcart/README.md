# DealCart controlled benchmark

DealCart is a disposable, local technology store built specifically for the
FlowLens dark-pattern scanner. It contains a manipulative benchmark and a fair
control with the same products and goals. It never takes real payments, sends
messages, or connects to third-party services.

## Start it

From the repository root:

```powershell
Set-Location '.\benchmarks\dealcart'
npm start
```

Open these pages:

- `http://127.0.0.1:3000/manipulative` — multi-pattern store;
- `http://127.0.0.1:3000/fair` — fair comparison store;
- `http://127.0.0.1:3000/lab` — directory of every isolated case.

Node.js 20 or newer is required. There are no npm dependencies and no install
step. State is held in a disposable in-memory session and resets whenever the
server restarts. Use the Reset button in `/lab` to reset one browser session.

## Run the tests

```powershell
Set-Location '.\benchmarks\dealcart'
npm run check
npm test
Set-Location '..\..'
& '.\.venv\Scripts\python.exe' '.\tools\smoke_dealcart.py'
```

The Node suite checks routing, security headers, state isolation, timer
semantics, safe path handling, fair cart behavior, manipulative silent add-ons,
flows, and reset behavior. The Playwright suite executes all 20 fair/manipulative
flow variants and visits every runtime, mechanism, and limitation case.

## Scan it and export PDF

Start DealCart, start the FastAPI backend in a second PowerShell window, then
open `http://127.0.0.1:8000/flow-analysis`.

Use `http://127.0.0.1:3000/manipulative` with execution mode `Controlled` for a
broad scan. For a predictable short demonstration, select a paired goal and use
its dedicated URL, such as `http://127.0.0.1:3000/flows/account`. Compare it to
`http://127.0.0.1:3000/flows/account?variant=fair`. When a run completes, click
**Download PDF report** in its result header.

Ground-truth metadata lives in `benchmark-manifest.json`. It is deliberately
absent from normal pages so the scanner cannot read its expected answer. Add
`?debug=true` only during manual development; never use debug mode for model
evaluation.

The complete routes, expected evidence, flow design, test matrix, and demo
procedure are documented in [../../docs/dealcart-benchmark.md](../../docs/dealcart-benchmark.md).

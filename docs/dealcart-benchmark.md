# DealCart benchmark specification

## 1. Purpose and acceptance criteria

DealCart is the controlled end-to-end benchmark for FlowLens. It provides a
realistic technology e-commerce interface whose state changes are synthetic and
safe. The benchmark is complete when it can:

1. expose the same acquisition/exit goal in fair and obstructed variants;
2. provide deterministic examples for every supported runtime behavior;
3. expose every structural obstruction and known automation boundary;
4. preserve terminal success text long enough for Playwright to verify it;
5. keep expected labels out of normal scanner-visible content;
6. run locally without a database, network access, or real payment details;
7. pass server/unit tests and an executable Playwright smoke suite; and
8. produce a stored FlowLens result that can be downloaded as a PDF report.

This is a research fixture, not evidence about a real business and not a
compliance certification tool.

## 2. Technology and process boundaries

The benchmark uses semantic HTML, local CSS, vanilla browser JavaScript, and a
Node.js HTTP server built only from Node core modules. The server binds to
`127.0.0.1:3000`, issues an HttpOnly SameSite session cookie, applies no-store
and restrictive security headers, and holds all state in memory.

FlowLens runs separately on `127.0.0.1:8000` and uses:

- Playwright Chromium for navigation, DOM state, screenshots, controls,
  redirects, timing, reloads, and clean-session comparisons;
- OCR and BERT for manipulative language evidence;
- YOLO for visual-cue evidence;
- DOM/CSS and runtime analysis for defaults, hierarchy, dialogs, claims,
  pricing changes, and timer behavior;
- paired-flow graph analysis for acquisition-versus-exit effort;
- PostgreSQL for jobs, results, findings, reviews, and comparisons; and
- Playwright PDF output for downloadable evidence reports.

BERT, YOLO, runtime behavior, and paired-flow scoring keep separate taxonomies.
Their evidence is combined in the report without forcing inaccurate label
equivalence.

## 3. Store variants

| Variant | URL | Expected use |
| --- | --- | --- |
| Manipulative | `/manipulative` | broad multi-pattern scan and positive control |
| Fair | `/fair` | negative/control comparison using the same product domain |
| Research lab | `/lab` | discover all dedicated test routes manually |

Any dedicated route accepts `?variant=fair`; otherwise it uses the
manipulative variant. The main manipulative page includes urgency, scarcity,
social-proof pressure, preselected choices, unequal reject presentation,
promotional interruption, and sponsored content. The fair page removes those
signals or presents an explicit, equal alternative.

## 4. Paired-flow requirements

Every flow begins with an acquisition state, exposes a stable acquisition
terminal, and finishes with a persistent exit terminal. The fair path provides
the equivalent exit immediately. The manipulative path adds exit-only burden.

| Family | Route | Acquisition | Equivalent exit |
| --- | --- | --- | --- |
| `account_create_delete` | `/flows/account` | Create account | Delete account |
| `subscribe_cancel` | `/flows/subscription` | Subscribe | Cancel subscription |
| `newsletter_subscribe_unsubscribe` | `/flows/newsletter` | Join newsletter | Unsubscribe |
| `consent_grant_withdraw` | `/flows/consent` | Accept consent | Withdraw consent |
| `notifications_enable_disable` | `/flows/notifications` | Enable notifications | Disable notifications |
| `integration_connect_disconnect` | `/flows/integration` | Connect integration | Disconnect integration |
| `payment_method_add_remove` | `/flows/payment-method` | Add mock method | Remove method |
| `loyalty_join_leave` | `/flows/loyalty` | Join rewards | Leave rewards |
| `data_share_revoke` | `/flows/data-sharing` | Enable sharing | Revoke sharing |
| `purchase_return` | `/flows/purchase-return` | Complete mock order | Start return |

The account and subscription positive controls use a seven-stage exit:

```text
direct acquisition
  -> management hub
  -> advanced settings
  -> information overload + hidden exit + policy mismatch
  -> forced reason and unnecessary fields
  -> retention offer
  -> first confirmation
  -> final confirmation
  -> persistent exit terminal
```

The remaining positive controls use a shorter but still asymmetric journey:
management hub, information overload/hidden exit, forced reason, confirmation,
then the persistent terminal. This lets tests cover all families without making
each demonstration unnecessarily long.

## 5. Runtime behavior scenarios

| Category | Route | Required observable behavior |
| --- | --- | --- |
| genuine counter-evidence | `/scenarios/genuine-countdown` | one process-wide absolute deadline, stable across reload/session |
| `resetting_countdown` | `/scenarios/fake-countdown` | countdown receives a fresh 12 seconds on reload |
| `non_expiring_offer` | `/scenarios/fake-countdown` | offer remains usable after zero |
| `session_relative_deadline` | `/scenarios/session-deadline` | same session retains deadline; clean session receives a new one |
| `fabricated_scarcity` | `/scenarios/scarcity` | deterministic low-stock pressure with no inventory source |
| `fabricated_social_proof` | `/scenarios/social-proof` | identical mechanically generated viewer/purchase claims |
| `preselected_option` | `/scenarios/preselection` | paid, marketing, and data-sharing options start checked |
| `hidden_rejection` | `/scenarios/hidden-rejection` | reject is materially less prominent than accept |
| `silent_cart_addition` | `/scenarios/silent-cart-addition` | adding a product also adds an unrequested paid care plan |
| `late_price_disclosure` | `/scenarios/late-price` | three fees appear only at final review |
| `repeated_nagging` | `/scenarios/nagging` | dismissed promotion returns after a deterministic delay |
| `misleading_action` | `/scenarios/misleading-action` | “Continue to delivery” opens subscription acquisition |
| `subscription_disclosure` | `/scenarios/subscription-disclosure` | recurring charge is visually weakened beside the free trial |

Timer classification must use behavior rather than the presence of a timer.
The genuine scenario is intentional counter-evidence and should not be reported
as fake urgency.

## 6. Isolated obstruction mechanisms

Dedicated pages make each structural mechanism independently testable:

| Mechanism | Route |
| --- | --- |
| `channel_switch` | `/flows/obstructions/channel-switch` |
| `forced_contact` | `/flows/obstructions/forced-contact` |
| `delayed_execution` | `/flows/obstructions/delayed-execution` |
| `redirect_loop` | `/flows/obstructions/redirect-loop-a` and `redirect-loop-b` |
| `dead_end` | `/flows/obstructions/dead-end` |
| `unnecessary_form_burden` | `/flows/obstructions/form-burden` |
| `information_overload` | `/flows/obstructions/information-overload` |
| `policy_interface_mismatch` | `/flows/obstructions/policy-mismatch` |

Primary paired flows additionally exercise `hidden_exit`, `forced_reason`,
`retention_obstruction`, and `repeated_confirmation`.

## 7. Automation-boundary scenarios

These routes must produce limitations or requests for assistance, never a dark
pattern verdict merely because traversal stopped:

| Boundary | Route | Expected limitation |
| --- | --- | --- |
| CAPTCHA | `/limitations/captcha` | `captcha_required` |
| MFA/OTP | `/limitations/mfa` | `mfa_required` |
| email verification | `/limitations/email-verification` | `email_verification_required` |
| payment | `/limitations/payment-required` | `payment_required` |
| external sign-in | `/limitations/external-idp` | `external_identity_provider` |
| bot challenge | `/limitations/bot-protection` | `bot_protection` |
| request throttle | `/limitations/rate-limited` | `rate_limited` |
| native application | `/limitations/native-app` | `native_app_required` |

## 8. Ground truth and leakage prevention

`benchmark-manifest.json` contains case ID, route, expected category, selector,
and expected status. The normal store never imports or renders this file. A
developer can use `?debug=true` to display matching manifest entries, but debug
URLs are prohibited during scanner evaluation because they expose the answer.

Normal route text describes the user experience, not “this is dark pattern X.”
Isolated mechanism and limitation pages may use mechanism-oriented explanatory
copy because their purpose is deterministic component validation, not blinded
accuracy measurement.

## 9. Server and state contract

The internal API is intentionally small:

- `GET /api/health` — readiness;
- `GET /api/benchmark/state` — current safe session state;
- `POST /api/benchmark/reset` — reset current session;
- `GET /api/benchmark/genuine-deadline` — stable absolute deadline;
- `GET /api/benchmark/fake-deadline` — fresh page-relative deadline;
- `GET /api/benchmark/session-deadline` — session-relative deadline; and
- `POST /api/benchmark/action` — cart, checkout, nag, and flow state changes.

No endpoint accepts real card data. Session state includes cart items, checkout
step, flow state, timer state, and the last 20 safe benchmark events. It is
discarded on server restart.

## 10. FlowLens integration and PDF contract

The backend allowlists the exact controlled origins
`http://127.0.0.1:3000` and `http://localhost:3000`. Other local/private origins
remain blocked. Evidence-only mode continues to reject loopback targets;
DealCart should be scanned in controlled mode.

Completed owner-scoped runs expose:

```http
GET /api/v1/autonomous-flow-runs/{run_id}/report.pdf
Authorization: Bearer <token>
```

The PDF is generated on demand by bundled Chromium and contains:

- URL, run ID, pipeline version, and generation time;
- whole-site URL coverage, page/depth budget status, and individual failures;
- per-page BERT findings, YOLO cues and bounding boxes, fusion links, and screenshots;
- outcome, publication gate, and confidence;
- BERT and YOLO availability notes;
- runtime findings and their evidence/counter-evidence;
- acquisition and exit metrics and step timelines;
- roach-motel conclusion and mechanism findings;
- confidence dimensions, limitations, and warnings; and
- state-graph totals and an interpretation disclaimer.

Dynamic values are HTML-escaped before rendering. The endpoint first verifies
run ownership and refuses incomplete jobs with HTTP 409.

## 11. Automated test matrix

Run all local checks from the repository root:

```powershell
Set-Location '.\benchmarks\dealcart'
npm run check
npm test
Set-Location '..\..'
& '.\.venv\Scripts\python.exe' '.\tools\smoke_dealcart.py'
& '.\.venv\Scripts\python.exe' -m pytest backend/tests -q
```

The Node tests cover HTTP routes and headers, path traversal rejection, fair and
manipulative cart deltas, flow/reset state, true/fake deadlines, invalid actions,
and malformed JSON. The Playwright smoke suite covers all 20 flow variants, all
12 dedicated runtime routes, all 8 mechanism routes, all 8 limitation routes,
UTF-8 rendering, timer reset, late fees, repeated nagging, and stable genuine
deadlines. Backend tests cover origin policy, HTML escaping, PDF ownership,
endpoint response headers, and UI wiring.

## 12. Recommended guide demonstration

Use three PowerShell windows:

1. Start DealCart with `npm start` from `benchmarks/dealcart`.
2. Start PostgreSQL if Windows has not already started it, then run
   `tools/start_native_backend.ps1` from the repository root.
3. Open `http://127.0.0.1:8000/flow-analysis`.

Suggested sequence:

1. Show `/fair`, then `/manipulative`, to establish the controlled pair.
2. Submit `http://127.0.0.1:3000/`, select **Full website audit** and
   **Controlled test target**, and leave all optional credential fields empty.
3. Keep 60 pages, crawl depth 4, runtime 600 seconds, and five seconds of
   per-page behavioral observation for the complete local benchmark.
4. Show the 49-page coverage section and all ten discovered paired families.
5. Compare a one-step fair exit with the seven-stage obstructed account exit.
6. Show the resetting countdown and genuine shared-deadline evidence.
7. Open the stored result and click **Download complete PDF report**.
8. If time permits, show run history, graph evidence, and regression comparison.

For a fast demo, disable BERT/YOLO only if model weights are unavailable and
state clearly that the run is validating flow/runtime behavior. Do not claim a
measured real-world accuracy from synthetic benchmark success.

## 13. Interpretation limits

Passing this benchmark proves that the implementation recognizes controlled,
known behaviors and can execute its product workflow. It does not establish
generalization to arbitrary websites. A defensible accuracy claim still needs a
site-separated, independently reviewed real-world test set with precision,
recall, false-positive analysis, traversal success, calibration error, and
confidence intervals.

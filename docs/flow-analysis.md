# Autonomous paired-flow analysis

The autonomous analyzer looks for **action asymmetry**: a website makes an
acquisition action (join, create, subscribe, enable) materially easier than the
equivalent exit action (leave, delete, cancel, disable). Its primary conclusion
is `roach_motel`. A longer exit is not sufficient by itself. The analyzer must
also establish that the goals are equivalent, reach adequate terminal evidence,
and observe at least one exit-specific obstruction mechanism.

The product workspace is available at
`http://127.0.0.1:8000/flow-analysis`. Its primary workflow requires only a URL;
an explicit goal family and disposable test credentials are optional.

## Autonomous pipeline

```text
URL + safety policy + optional test credentials
  -> destination and origin validation
  -> BERT/YOLO availability check
  -> dynamic frontend observation, reload and clean-session comparison
  -> acquisition-intent discovery
  -> page/dialog state graph and stable selectors
  -> optional authenticated session establishment
  -> corresponding exit-intent discovery
  -> bounded safe traversal and replay
  -> structural mechanism extraction
  -> paired effort score and confidence gate
  -> PostgreSQL history, findings, reviews and comparisons
```

Runs are asynchronous. The API returns HTTP 202 immediately, and the UI polls
the durable job while its stage moves through validation, static analysis,
acquisition discovery, session establishment, exit discovery, replay, scoring,
and persistence. A process restart marks an interrupted in-process run failed;
the stored result of a completed run remains available.

## Supported paired goals

Automatic discovery searches every family, or the caller can constrain a run
to one family:

| Goal family | Acquisition | Exit |
| --- | --- | --- |
| `account_create_delete` | create account | delete account |
| `subscribe_cancel` | subscribe or start trial | cancel subscription or trial |
| `newsletter_subscribe_unsubscribe` | join newsletter | unsubscribe |
| `consent_grant_withdraw` | accept or grant consent | reject or withdraw consent |
| `notifications_enable_disable` | enable notifications | disable notifications |
| `integration_connect_disconnect` | connect integration | disconnect integration |
| `payment_method_add_remove` | add payment method | remove payment method |
| `loyalty_join_leave` | join loyalty programme | leave programme |
| `data_share_revoke` | enable data sharing | revoke sharing |
| `purchase_return` | purchase | initiate return |

The same graph engine can therefore expose hidden exits, dead ends, and channel
switches outside subscription cancellation. It does not use flow asymmetry for
false scarcity, fake countdowns, social proof, confirm-shaming, disguised ads,
or preselected options; BERT, YOLO, and DOM evidence remain the appropriate
detectors for those static patterns.

## What the browser records

A state is a normalized observation of the URL, headings, dialog text,
authentication state, and available controls—not just a URL. This means two
modal states on one page remain distinct. An edge records the accessible action
name, selector strategies, risk, duration, transition status, and evidence
tags. Graph phases are `acquisition`, `session`, and `exit`.

Controls are rediscovered with multiple strategies in preference order:
accessible role and name, associated label, stable data attribute, ID, name,
then CSS fallback. The result reports selector stability and replay stability
rather than assuming one successful traversal will remain reproducible.

Exploration is bounded by configurable state, depth, action, candidate, replay,
and runtime budgets. Budget exhaustion is a limitation and produces an
inconclusive result; it is never interpreted as obstruction.

## Safety and execution modes

`evidence_only` is the default for arbitrary public websites. It permits
read-only exploration and stops at a mutating, financial, or destructive commit
frontier. That frontier can be evidence that the correct terminal action was
located, but no account, payment, subscription, or consent state is changed.

`controlled` is for a website the researcher owns or an explicitly approved
test origin. It may execute risk-classified commit actions—including mutating,
financial, and destructive controls—only on its explicit origin allowlist. The
backend—not the UI—enforces that boundary. Downloads and service workers are
disabled, cross-origin redirects are restricted, and private-network
destinations are rejected except for the local benchmark.

CAPTCHA, OTP, MFA, email verification, bot protection, external identity
providers, payment, and native-app or support-channel boundaries are recorded
as execution limitations. The job may request disposable credentials when that
is the only recoverable boundary. Credential and one-time-code values exist in
worker memory only: PostgreSQL stores `has_credentials: true/false`, never the
secret values. The browser form clears them immediately after submission.

Only run controlled traversal against systems you own or have explicit
permission to test. “Evidence only” reduces side effects; it does not grant
authorization to ignore a website's terms or access controls.

## Mechanism taxonomy

`roach_motel` is the overall paired-flow conclusion. The following findings
explain why the exit journey was obstructive:

- `hidden_exit`
- `forced_reason`
- `retention_obstruction`
- `repeated_confirmation`
- `channel_switch`
- `forced_contact`
- `delayed_execution`
- `redirect_loop`
- `dead_end`
- `unnecessary_form_burden`
- `information_overload`
- `policy_interface_mismatch`

Mechanisms come from structural flow and DOM evidence. Examples include a
required “reason for leaving” field, multiple distinct confirmation states, an
exit control with materially poor presentation, a support-phone requirement,
or a graph that revisits the same state without progress. A text or visual model
prediction is supporting evidence and does not add directly to flow effort.
BERT and YOLO keep their separate taxonomies; no inaccurate one-to-one label
mapping is imposed.

## Effort and candidate thresholds

Each path retains the calibrated manual-flow metric:

```text
base effort = meaningful actions
            + 0.5 * page transitions
            + 0.5 * form fields
            + capped active-time contribution

flow effort = base effort
            + max(0, obstruction weight - justified-safeguard weight)
```

An autonomous `roach_motel` candidate currently requires all of these:

- pairing confidence of at least `0.65`;
- an adequate acquisition and exit terminal (verified or a safe commit
  frontier);
- exit effort at least `3.0` points above acquisition effort;
- exit/acquisition effort ratio of at least `1.75`;
- at least one detected structural exit mechanism; and
- a confidence gate above `inconclusive`.

These are research thresholds, not legal thresholds.

## Confidence gate

Confidence is separate from candidate severity and score. Its dimensions and
weights are:

| Dimension | Weight |
| --- | ---: |
| paired-goal equivalence | 0.25 |
| acquisition terminal evidence | 0.20 |
| exit terminal evidence | 0.20 |
| replay stability | 0.15 |
| selector stability | 0.10 |
| evidence quality | 0.10 |

An overall confidence of at least `0.85` is `auto_report`; `0.65`–`0.849999`
is `report_with_caution`; below `0.65` is `inconclusive`. Missing credentials,
failed authentication, CAPTCHA, MFA, email verification, payment boundaries,
or unverified terminal states cap confidence below the caution threshold. One
replay attempt caps confidence at `0.79`; the default policy performs two.

High-confidence findings do not require a reviewer to complete the automation
pipeline. Caution findings may be reviewed, and inconclusive findings are placed
in the review queue when evidence is still useful. Review decisions are stored
separately from model output to preserve an audit trail.

## API

Create and poll a run:

```http
POST /api/v1/flow-runs/autonomous
Authorization: Bearer <token>
Content-Type: application/json

{
  "url": "https://example.com",
  "mode": "evidence_only",
  "goal_families": ["auto"],
  "analyse_models": true,
  "policy": {
    "max_states": 30,
    "max_depth": 6,
    "max_actions": 50,
    "max_runtime_seconds": 180,
    "max_candidates_per_state": 8,
    "replay_attempts": 2
  }
}
```

The returned job contains only a safe request summary. Poll it until `status` is
`completed`, `needs_input`, `failed`, or `cancelled`.

- `POST /api/v1/flow-runs/autonomous`
- `GET /api/v1/autonomous-flow-runs`
- `GET /api/v1/autonomous-flow-runs/{run_id}`
- `GET /api/v1/autonomous-flow-runs/{run_id}/graph`
- `GET /api/v1/autonomous-flow-runs/{run_id}/findings`
- `GET /api/v1/autonomous-flow-runs/{run_id}/screenshots/{filename}`
- `POST /api/v1/autonomous-flow-runs/{run_id}/cancel`
- `POST /api/v1/autonomous-flow-runs/{run_id}/input`
- `PUT /api/v1/autonomous-findings/{finding_id}/review`
- `GET /api/v1/autonomous-flow-review-queue`
- `POST /api/v1/autonomous-flow-comparisons`
- `GET /api/v1/autonomous-flow-comparisons`

Dynamic frontend findings are stored separately from paired-flow effort. They
cover resetting countdowns, non-expiring offers, visitor-relative deadlines,
preselected choices, hidden rejection, repeated nagging, suspicious scarcity or
social-proof claims, misleading action destinations, and weak price or recurring
subscription disclosures. See `docs/dynamic-frontend-analysis.md` for the full
evidence and confidence model.

The autonomous request schema is checked in as
`docs/autonomous-flow.schema.json`. The legacy reviewed-definition schema is
`docs/flow-pair.schema.json`. Both are also present in `/openapi.json` and the
interactive `/docs` page. Regenerate checked-in schemas after changing a
Pydantic request model:

```powershell
& '.\.venv\Scripts\python.exe' tools\export_flow_schema.py
```

## Regression comparisons

A comparison matches goals by stable signature. It reports acquisition-effort,
exit-effort, ratio, added mechanisms, and resolved mechanisms. An exit increase
of at least 2 points, a ratio increase of at least 0.5, or any added mechanism
is a regression candidate; the inverse is an improvement. Runs from different
origins or pipeline versions, and goals missing from either run, are
inconclusive rather than forced into a comparison.

## Stored data

Native PostgreSQL stores the safe request summary, stage and outcome, graph
nodes and edges, paired goals and metrics, findings, review decisions, and
regression comparisons. Screenshots and model artifacts remain on the project
filesystem; database records hold their evidence references. Raw credential
values are never persisted.

## Controlled validation and calibration

The legacy manual-flow presets remain available as secondary controls:

- fair localhost: one-step creation versus one-step deletion;
- obstructed localhost: hidden exit, required reason, retention, and repeated
  confirmation;
- Automation Exercise: a disposable public lifecycle preset.

For an accuracy claim, do not rely on these smoke controls alone. Build a
site-separated, independently human-reviewed benchmark; record traversal
success and limitation rates; report precision, recall, confidence intervals,
inter-rater agreement, and calibration error. Tune thresholds on a calibration
split and report the final result once on a held-out site split.

## Manual definition fallback

Sites with unusual widgets or authorization boundaries may still be tested with
a reviewed paired JSON definition or the headed recorder:

```powershell
$env:PYTHONPATH = "$PWD\backend"
& '.\.venv\Scripts\python.exe' tools\record_flow.py 'https://example.com'
```

Replace personal values with templates, mark state-changing actions with
`"commit": true`, and review allowed origins before submitting the definition.
Manual definitions are a diagnostic fallback, not a prerequisite for the
autonomous URL-first workflow.

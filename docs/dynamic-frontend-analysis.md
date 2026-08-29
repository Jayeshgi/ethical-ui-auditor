# Dynamic frontend behaviour analysis

FlowLens complements its text, visual, and paired-flow engines with a passive
runtime frontend analyzer. The analyzer asks whether browser-delivered interface
behaviour remains consistent across time, reloads, and independent sessions.
It does not treat the mere presence of timer code or promotional language as
proof of deception.

## Pipeline

```text
URL and safe browser policy
  -> rendered candidate discovery
  -> bounded passive observation (5–90 seconds)
  -> same-session reload
  -> independent clean browser session
  -> DOM/CSS, script and same-origin network evidence
  -> behavioural scoring and confidence
  -> optional BERT/YOLO corroboration
  -> PostgreSQL run result, screenshots, review queue and regression comparison
```

The implementation is in `backend/app/frontend_analysis/`. Autonomous requests
enable it with `analyse_behavior` and configure the observation window through
`policy.behavior_observation_seconds`. It is enabled by default. The normal scan
endpoint exposes the equivalent `analyse_behavior` and
`behavior_observation_seconds` fields.

## Evidence collected

The report retains evidence necessary to reproduce a finding without cloning a
third-party website:

- SHA-256 hashes for the original response, final rendered DOM, and bounded
  same-origin script and stylesheet assets;
- short redacted excerpts around relevant timer or deadline code;
- selectors, element values, computed presentation properties and four bounded
  DOM snapshots (`initial`, `observed`, `reload`, `clean_session`);
- redacted same-origin network metadata and response hashes;
- cookie and browser-storage **names only**, never their values;
- timestamped timer samples and redacted screenshots.

Full JavaScript bundles, full third-party source trees, cookie values, storage
values, credentials, authorization headers, and response bodies are not stored.
Query values are removed from recorded URLs. Editable and PII-like screenshot
content is masked.

The browser can inspect only resources delivered to it. It cannot obtain private
backend source, database logic, secrets, or server-side decisions.

## Countdown experiment

Timer candidates are discovered through rendered time formats, changing DOM
values, public timer/deadline code, and optional BERT/YOLO evidence. For each
candidate the analyzer records one sample per second, then compares its value
after reload and in a separate clean context.

Strong deceptive evidence includes a backward jump during observation, reload
restoring the original duration, a clean session receiving the same fresh
duration, client-relative deadline initialization, or an offer remaining active
after zero. A high-confidence resetting finding requires multiple independent
signals. Source code alone cannot produce a `detected` result.

A shared absolute deadline, decreasing values across reload and clean sessions,
and an offer that changes at expiry are counter-evidence. When neither side can
be established the result is `inconclusive`, not “safe” or “fake.”

## Categories

| Behaviour category | Parent dark-pattern taxonomy | Evidence |
| --- | --- | --- |
| `resetting_countdown` | `false_urgency` | timer restarts or jumps backward |
| `non_expiring_offer` | `false_urgency` | offer remains after zero |
| `session_relative_deadline` | `false_urgency` | every visitor receives a fresh deadline |
| `fabricated_scarcity` | `false_scarcity` | mechanically repeated scarcity claim |
| `fabricated_social_proof` | `social_proof` | mechanically repeated activity claim |
| `preselected_option` | `forced_consent` | optional marketing or paid choice selected initially |
| `hidden_rejection` | `forced_consent` | accept/reject presentation is materially asymmetric |
| `silent_cart_addition` | `sneaking` | paid-looking add-on is selected without user action |
| `late_price_disclosure` | `sneaking` | fee/total disclosure is hidden or strongly weakened |
| `repeated_nagging` | `obstruction` | the same dialog repeatedly returns |
| `misleading_action` | `misleading_claim` | label conflicts with its public destination/handler |
| `subscription_disclosure` | `subscription_manipulation` | recurring terms are visually de-emphasized |

Scarcity and social-proof repetition are intentionally only `suspicious` without
independent server or inventory evidence. Silent cart additions and misleading
actions also remain suspicious when the safe analyzer does not execute a
mutating checkout action.

## Controlled benchmarks

Start the native backend and open `http://127.0.0.1:8000/flow-analysis`. The
**Dynamic frontend research controls** section can load these URLs and configure
controlled mode automatically:

- `/behavior-benchmarks/genuine-countdown` — shared absolute deadline;
- `/behavior-benchmarks/fake-countdown` — resetting, non-expiring timer;
- `/behavior-benchmarks/manipulative-store` — timer, scarcity, social proof,
  preselected choices, hidden rejection, repeated nagging, misleading navigation,
  and weakened recurring-price terms.

For a direct run, select `Controlled test target`, set the frontend observation
window to 10 seconds, and click **Analyze website**. Public sites must remain in
`Evidence only` mode.

## Interpretation

`detected` means the bounded runtime experiment observed strong consistent
evidence. `suspicious` means useful signals require confirmation. `inconclusive`
means the experiment could not establish either deceptive or genuine behaviour.
`not_detected` means the tested candidate had meaningful counter-evidence, not
that the entire website is free of dark patterns.

These are research findings, not legal conclusions. Dynamic findings remain
separate from paired-flow effort, but both appear in the same result, review
queue, history, and before/after regression comparison.

# Ethical UI Auditor

Developer-facing proof of concept for detecting candidate dark-pattern language on a supplied website.

Current pipeline:

```text
URL -> safe Playwright capture and state graph
    -> OCR + BERT text evidence
    -> YOLO visual evidence
    -> DOM/CSS + runtime behavior evidence
    -> paired-flow effort and confidence fusion
    -> PostgreSQL history -> web result + PDF report
```

The current milestone includes Playwright, OCR, BERT-based text analysis, YOLO
v2 visual-cue detection, taxonomy-safe spatial evidence fusion, persistent
asynchronous scan jobs, and an autonomous paired-flow analyzer. The flow
analyzer can either inspect one journey or crawl an entire same-origin website.
The full-site mode records URL coverage and per-page failures, runs static and
runtime evidence analysis on each captured page, discovers acquisition and exit
goals across the site, builds page-state graphs with per-journey budgets, and stores
confidence-gated findings and regression comparisons. A separate dynamic
frontend engine observes timers, defaults, visual hierarchy, repeated dialogs,
scarcity/social-proof claims, and subscription disclosures across time, reload,
and clean browser sessions. Completed autonomous runs can be downloaded as
self-contained PDF evidence reports.

## Text-classification model

The final classifier is a fine-tuned `bert-base-uncased` multi-label model. It predicts the ten dark-pattern categories; `neutral` means no category crosses its separately calibrated threshold. Deterministic rules are retained only to identify exact evidence phrases in a BERT finding.

The scan endpoint intentionally returns HTTP 503 until a trained, validated model artifact exists. It never substitutes keyword rules as model predictions.

## Team setup

The repository includes the original and augmented datasets plus the training code. Generated local files (the Python environment, browser binaries, screenshots, scan data, and model artifacts) are intentionally not versioned.

1. Install Python 3.11+, PostgreSQL 17, Tesseract OCR, Git, and Node.js 20+.
2. Create and activate the local environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. Copy `.env.example` to `.env`, replace the placeholder secrets, then install
   dependencies and the Playwright Chromium browser:

```powershell
pip install -r requirements.txt
playwright install chromium
```

4. Create the native PostgreSQL `auditor` role and `ethical_ui_auditor`
   database, then apply the schema:

```powershell
$env:PYTHONPATH = "$PWD\backend"
& '.\.venv\Scripts\python.exe' -m alembic -c alembic.ini upgrade head
```

5. Train the research/demo model from the repository root:

```powershell
$env:PYTHONPATH = 'C:\Major project\backend'
& 'C:\Major project\.venv\Scripts\python.exe' -m training.train --allow-synthetic-evaluation --epochs 3 --batch-size 4
```

The `--allow-synthetic-evaluation` option is necessary for the current dataset, but the resulting artifact is research/demo-only and must not be presented as a compliance-grade model.

6. Start the native backend (do **not** use `--reload` on Windows, because Playwright needs the Proactor event loop):

```powershell
& '.\tools\start_native_backend.ps1'
```

Open `http://127.0.0.1:8000/docs` to use the API.

Open `http://127.0.0.1:8000/flow-analysis` for the URL-first autonomous flow
workspace, run history, state graphs, review queue, and regression comparisons.
The same workspace includes genuine, resetting-countdown, and multi-pattern
frontend research controls. See `docs/dynamic-frontend-analysis.md` for its
evidence model and interpretation limits.

For the full safe product demonstration, start the DealCart controlled store in
a second PowerShell window:

```powershell
Set-Location 'C:\Major project\benchmarks\dealcart'
npm start
```

Open `http://127.0.0.1:3000/lab` to browse every benchmark case. For one
consolidated audit, submit `http://127.0.0.1:3000/`, select **Full website
audit** and **Controlled test target**, and leave the optional credentials
empty. The default 60-page, depth-4 budget covers the current 49-page DealCart
link graph. Use the **Download complete PDF report** button after the run
completes. The complete route,
flow, test, and presentation specification is in
`docs/dealcart-benchmark.md`.

Native PostgreSQL is the local default. Docker PostgreSQL remains optional for
reproducible team/deployment runs. See `docs/database-workflow.md` for the data
model, backups, and guarded native-to-Docker/Docker-to-native synchronization.

## Accounts and authentication

Product API endpoints use bearer authentication. Create an account with
`POST /api/v1/auth/register`, then obtain a token from
`POST /api/v1/auth/login`. Supply it as `Authorization: Bearer <token>`.
`GET /api/v1/auth/me` returns the authenticated account. Passwords are stored
with Argon2 hashing; the JWT secret and expiry are configured through
`JWT_SECRET_KEY` and `ACCESS_TOKEN_EXPIRE_MINUTES`.

## Training notes

Train only after the real-data quality gate passes:

```powershell
$env:PYTHONPATH = 'C:\Major project\backend'
C:\Major project\.venv\Scripts\python.exe -m training.train
```

For a research/demo artifact when only synthetic coverage exists, use `--allow-synthetic-evaluation`. The artifact and every API scan will be marked as synthetic-assisted; it is not suitable for compliance claims.

See `docs/model-data-requirements.md` for the required real, reviewed examples before training.

## Scan endpoint

`POST /api/v1/scans` queues a scan and returns HTTP 202 with a job resource.

```json
{
  "url": "https://example.com",
  "max_pages": 3,
  "scroll_steps": 2
}
```

Poll `GET /api/v1/scans/{scan_id}` until `status` becomes `completed` or
`failed`. A completed job contains the full scan under `result`, including
separate `findings`, `visual_cues`, and `fusion_links` for each page. The
undocumented `POST /api/v1/scans/run` compatibility endpoint remains available
for trusted local scripts that require a blocking response.

Authenticated users can list their history with `GET /api/v1/scans`, compare
two completed scans with `GET /api/v1/scans/compare`, and create or update an
auditable decision through `PUT /api/v1/scans/{scan_id}/reviews`.

The scanner only follows same-origin links and does not submit forms, authenticate, purchase, accept payments, or perform destructive actions.

## Autonomous paired-flow analysis

The primary flow workflow takes a website URL plus optional disposable test
credentials. It automatically looks for equivalent acquisition and exit goals,
such as account creation/deletion, subscription/cancellation, consent
grant/withdrawal, integration connect/disconnect, or purchase/return. It records
normalized states and actions, timing, selector and replay stability,
obstruction mechanisms, and BERT/YOLO supporting evidence. Results, reviews,
and before/after comparisons persist in PostgreSQL; credential values do not.

Arbitrary public targets default to `evidence_only` and stop at mutating,
financial, or destructive commit frontiers. `controlled` mode is only for owned
or explicitly approved test origins. CAPTCHA, MFA, payment, cross-origin, and
similar boundaries produce limitations and confidence caps, not automatic dark
pattern findings.

Two localhost controls and the reviewed-definition workflow remain available
as secondary diagnostics. See `docs/flow-analysis.md` for the autonomous API,
goal and mechanism taxonomies, confidence gates, schema, safety model, and
calibration protocol.

## Optional container deployment

Copy `.env.example` to `.env`, replace both placeholder secrets, and ensure the
validated model artifacts exist under `model_artifacts/`. Then run:

```powershell
docker compose up --build
```

Compose starts PostgreSQL and the non-root Playwright/FastAPI container, applies
Alembic migrations, and exposes the API on port 8000. The GitHub Actions
workflow compiles and tests the backend and verifies that the production image
builds. Do not deploy with the example secrets.

## External screenshot benchmark

The project can evaluate its OCR-to-BERT path on the web portion of AidUI's
CONTEXTDP benchmark. AidUI is an ICSE 2023 replication package; its screenshot
annotations are an external benchmark and are not merged into this project's
training data. Clone AidUI beside the project root (the default local cache is
`.aidui-review`) and run:

```powershell
$env:PYTHONPATH = 'C:\Major project\backend'
& 'C:\Major project\.venv\Scripts\python.exe' tools\evaluate_contextdp.py
```

The evaluation crops each annotated web UI region, applies the application's OCR,
then applies the existing BERT model. It scores only labels with a documented
semantic mapping and writes `runtime_data/contextdp_web_bert_evaluation.json`.
It is an external OCR-mediated evaluation, not a claim that this text model
reproduces AidUI's visual detector. Cite AidUI and the CONTEXTDP benchmark:
https://github.com/SageSELab/AidUI

## Visual-cue model

The optional visual path uses a locally fine-tuned Ultralytics YOLO26n detector.
The Roboflow dataset is prepared by removing `NO DP` bounding boxes and retaining
those screenshots as background examples:

```powershell
& '.\.venv\Scripts\python.exe' tools\prepare_visual_dataset.py '<extracted Roboflow dataset path>'
```

For the RTX 4050 development environment, CUDA-enabled PyTorch is installed from
the official CUDA 13.0 wheel index. Training then runs with GPU 0:

```powershell
$env:PYTHONPATH = 'C:\Major project\backend'
& '.\.venv\Scripts\python.exe' -m training.train_visual --epochs 100 --batch 8
```

The first research baseline early-stopped after 54 epochs. On the held-out test
split it obtained precision 0.368, recall 0.187, mAP@50 0.185, and mAP@50-95
0.108. A leakage-checked v2 pseudo-label experiment added 40 unique training
screenshots with 79 calibrated box proposals while leaving validation and test
unchanged. V2 obtained precision 0.660, recall 0.227, mAP@50 0.261, and
mAP@50-95 0.155. Its weights are under
`model_artifacts/dark_pattern_yolo_v2/`. The model remains research-only because
the test set is small and the added boxes are machine-proposed rather than
independently reviewed human annotations.

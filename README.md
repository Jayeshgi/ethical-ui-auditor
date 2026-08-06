# Ethical UI Auditor

Developer-facing proof of concept for detecting candidate dark-pattern language on a supplied website.

Current pipeline:

```text
URL → Playwright capture → screenshot + visible DOM text → OCR → fusion → BERT analysis → evidence phrases → JSON
```

The current milestone includes Playwright, OCR, text fusion, and BERT-based text analysis. It deliberately excludes visual YOLO detection, graph analysis, a dashboard, and report/PDF generation.

## Text-classification model

The final classifier is a fine-tuned `bert-base-uncased` multi-label model. It predicts the ten dark-pattern categories; `neutral` means no category crosses its separately calibrated threshold. Deterministic rules are retained only to identify exact evidence phrases in a BERT finding.

The scan endpoint intentionally returns HTTP 503 until a trained, validated model artifact exists. It never substitutes keyword rules as model predictions.

## Team setup

The repository includes the original and augmented datasets plus the training code. Generated local files (the Python environment, browser binaries, screenshots, scan data, and model artifacts) are intentionally not versioned.

1. Install Python 3.11+, Tesseract OCR, and Git.
2. Create and activate the local environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. Install dependencies and the Playwright Chromium browser:

```powershell
pip install -r requirements.txt
playwright install chromium
```

4. Train the research/demo model from the repository root:

```powershell
$env:PYTHONPATH = 'C:\Major project\backend'
& 'C:\Major project\.venv\Scripts\python.exe' -m training.train --allow-synthetic-evaluation --epochs 3 --batch-size 4
```

The `--allow-synthetic-evaluation` option is necessary for the current dataset, but the resulting artifact is research/demo-only and must not be presented as a compliance-grade model.

5. Start the backend (do **not** use `--reload` on Windows, because Playwright needs the Proactor event loop):

```powershell
Set-Location backend
$env:PYTHONPATH = 'C:\Major project\backend'
& 'C:\Major project\.venv\Scripts\python.exe' -m uvicorn app.main:app
```

Open `http://127.0.0.1:8000/docs` to use the API.

## Training notes

Train only after the real-data quality gate passes:

```powershell
$env:PYTHONPATH = 'C:\Major project\backend'
C:\Major project\.venv\Scripts\python.exe -m training.train
```

For a research/demo artifact when only synthetic coverage exists, use `--allow-synthetic-evaluation`. The artifact and every API scan will be marked as synthetic-assisted; it is not suitable for compliance claims.

See `docs/model-data-requirements.md` for the required real, reviewed examples before training.

## Scan endpoint

`POST /api/v1/scans`

```json
{
  "url": "https://example.com",
  "max_pages": 3,
  "scroll_steps": 2
}
```

The scanner only follows same-origin links and does not submit forms, authenticate, purchase, accept payments, or perform destructive actions.

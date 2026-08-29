# How the Ethical UI Auditor Works

## One-sentence explanation

The system reads a webpage like a browser, collects the text that a user can
see, combines webpage text with text read from the screenshot, and asks the
fine-tuned BERT model which dark-pattern category—if any—best matches each text
block.

## Request-to-result flow

```text
URL
  -> safety validation
  -> Playwright browser capture
  -> screenshot + visible DOM text
  -> Tesseract OCR over screenshot
  -> DOM/OCR text fusion
  -> fine-tuned BERT multi-label prediction
  -> YOLO v2 visual-cue detection
  -> taxonomy-safe spatial evidence fusion
  -> evidence phrase + confidence + bounding box
  -> JSON response and saved screenshot
```

### 1. URL safety validation

The API accepts an `http` or `https` URL. Before opening it, the application
rejects local, private, loopback, reserved, and credential-containing URLs.
This prevents the scanner from being used to access local network services.

### 2. Read-only browser capture

Playwright opens the supplied website in a headless Chromium browser. It takes
a full-page screenshot, reads visible text from buttons, links, labels,
headings, paragraphs, list items, dialogs, and similar UI elements, and may
follow a small number of same-origin links. It never logs in, submits a form,
makes a purchase, accepts payments, or intentionally changes website data.

### 3. Two ways of collecting text

The application uses both sources because neither one is complete on its own.

| Source | What it captures | Why it matters |
|---|---|---|
| DOM extraction | Text contained in the website HTML | Usually accurate and includes accessible page text. |
| OCR | Text visually present in the screenshot | Can capture image-based banners, rendered widgets, or text missing from the DOM. |

Tesseract OCR returns text with approximate bounding boxes. The fusion stage
removes near-duplicate text while retaining whether a block came from the DOM,
OCR, or both. DOM text is preferred when the two agree because it is usually
more accurate.

### 4. BERT prediction

Each fused text block is tokenised and passed to the project's fine-tuned
`bert-base-uncased` multi-label classifier. BERT produces a probability for
each of the ten categories:

`false_urgency`, `false_scarcity`, `social_proof`, `confirm_shaming`,
`fear_or_pressure`, `misleading_claim`, `subscription_manipulation`,
`forced_consent`, `sneaking`, and `obstruction`.

Each category has its own threshold, calculated during model validation. A
category is returned only when its BERT probability exceeds that category's
threshold. Several categories may be returned for the same text, because one
piece of UI language can use more than one manipulative technique.

### 5. Evidence in the output

For every BERT prediction, the API returns the category, BERT confidence,
threshold, original text, text source, UI selector when available, and a
bounding box when available. Small deterministic phrase patterns are used only
to highlight an understandable phrase inside a finding; they do **not** decide
whether the model predicts a category. The BERT probability is the decision.

### 6. How to interpret it

The result is a candidate finding, not a legal or compliance conclusion. For
example, many people viewing a product can be genuine social information; it
becomes a suspected dark pattern only when it is deceptive or used to pressure
the user. The live-scan results show why reviewers must inspect the displayed
evidence before treating a candidate as a confirmed dark pattern.

### 7. Visual cues and fusion

YOLO v2 runs on every captured screenshot and returns visual cues separately
from BERT findings. The fusion layer links only documented compatible
categories whose bounding boxes overlap. It does not force the two taxonomies
to match or average their independently calibrated confidence scores. See
`docs/visual-text-fusion.md` for the relationship table and response semantics.

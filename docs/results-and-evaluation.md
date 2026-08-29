# Results and Evaluation

## External evaluation using AidUI CONTEXTDP

To assess how well the proposed OCR-to-BERT pipeline generalises beyond its
training data, we evaluated it on the web portion of the AidUI CONTEXTDP
benchmark. AidUI is the replication package for the ICSE 2023 paper *AidUI:
Toward Automated Recognition of Dark Patterns in User Interfaces*. CONTEXTDP
contains labelled screenshots of web and mobile user interfaces.

This evaluation uses the 102 web annotations that can be mapped unambiguously
to the project taxonomy. For every annotation, the labelled UI bounding box was
cropped from the screenshot, passed through the application's Tesseract OCR
component, and then classified by the existing fine-tuned `bert-base-uncased`
multi-label model. Thus, this is an external OCR-mediated evaluation of the
text-classification path; it does not measure live DOM extraction, page
crawling, or AidUI's visual object detector.

| Category | Precision | Recall | F1 score | Support |
|---|---:|---:|---:|---:|
| False scarcity | 0.958 | 0.920 | 0.939 | 25 |
| False urgency | 1.000 | 0.889 | 0.941 | 54 |
| Forced consent | 0.000 | 0.000 | 0.000 | 12 |
| Social proof | 1.000 | 1.000 | 1.000 | 11 |
| Macro average | 0.740 | 0.702 | 0.720 | 102 |

The results indicate that the model identifies text-based urgency, scarcity,
and social-proof signals effectively in this external benchmark. However, it
does not identify the AidUI `DEFAULT CHOICE` cases under the mapped
`forced_consent` category. This limitation is expected because default-choice
manipulation often depends on visual state (for example, a preselected option),
which may not be present in OCR text alone. Future work should add reviewed
real examples of consent interfaces and combine BERT text predictions with
visual UI-state features.

AidUI labels without an unambiguous mapping, such as `ATTENTION DISTRACTION`,
were excluded rather than forcing an invalid comparison. `NO DP` screenshot
labels were also excluded because this protocol evaluates the labelled positive
UI regions. The trained model remains research-only because its original
threshold evaluation contains both real and synthetic data.

**Citation:** S. M. Hasan Mansur, S. Salma, D. Awofisayo, and K. Moran,
“AidUI: Toward Automated Recognition of Dark Patterns in User Interfaces,”
ICSE 2023. Replication package and CONTEXTDP benchmark:
https://github.com/SageSELab/AidUI

## Live-scan demonstrations

Three read-only one-page scans were carried out through the deployed API. The
request JSON and captured screenshots are retained under `runtime_data/` so
that the demonstration can be reproduced. Each scan follows only the requested
page, does not authenticate or submit forms, and records the model version,
predictions, confidence values, and visual/text evidence.

| URL | Captured text blocks | Candidate findings | Interpretation |
|---|---:|---:|---|
| `https://example.com` | 3 | 0 | Expected clean control page. |
| `https://www.iana.org/help/example-domains` | 50 | 2 | Benign reference-page wording was flagged as `obstruction` and `social_proof`; these are false-positive candidates requiring reviewer rejection. |
| `https://news.ycombinator.com` | 355 | 124 | Points, comments, and timestamps were frequently classified as `social_proof` or urgency. This demonstrates that popularity language alone is not enough to establish a dark pattern. |

The live scans validate the end-to-end operation of URL capture, DOM extraction,
OCR, text fusion, BERT inference, and evidence storage. They must not be
reported as proof that IANA or Hacker News uses dark patterns. Instead, they
demonstrate why the system is a developer-facing screening tool and why a human
reviewer must inspect every candidate result.

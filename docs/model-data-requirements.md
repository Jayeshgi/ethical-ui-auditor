# BERT Training Data Requirements

The application uses a fine-tuned `bert-base-uncased` multi-label classifier. Synthetic records may be included in the training set to improve coverage, but they must never be used to set thresholds or report final evaluation performance.

## Required split policy

| Split | Allowed records |
|---|---|
| Training | reviewed real records and explicitly marked synthetic records |
| Validation | reviewed real records only |
| Test | reviewed real records only |

Records from the same source page must remain in one split. This avoids memorising near-identical text from a website rather than learning the category.

## Minimum evidence target

Before releasing a model, collect at least 100 reviewed real examples per dark-pattern class. Reserve at least 20 real records per class for validation and 20 for the final test set. More examples are required if the wording is repetitive or comes from only a few websites.

The current dataset has no real records for `fear_or_pressure` or `subscription_manipulation`; it has too few real records for `forced_consent`, `sneaking`, and `obstruction`. The training command fails intentionally until every category is present in validation and test data.

## Review record format

Each collected record must include:

```csv
record_id,text,Pattern Category,source_url,page_id,screenshot_path,bounding_box,annotator,review_status
```

`review_status` must be `approved` before the record enters validation or test data. A second reviewer should resolve disagreements for ambiguous categories such as `misleading_claim`, `false_urgency`, and `false_scarcity`.

## Training output

Successful training writes a versioned model artifact containing:

- BERT weights and tokenizer
- category mapping
- validation-derived per-category thresholds
- held-out test metrics
- dataset and model metadata

The API loads only this complete artifact. It will not scan-and-classify with an unvalidated or partially trained model.

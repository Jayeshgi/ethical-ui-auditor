# Visual and Text Evidence Fusion

The auditor intentionally keeps two different taxonomies:

- BERT predicts conceptual dark-pattern categories from language.
- YOLO predicts visible UI cues from pixels.

A visual cue is not automatically a dark-pattern conclusion. The API returns
text findings in `findings`, visual evidence in `visual_cues`, and defensible
cross-modal relationships in `fusion_links`. Model probabilities are never
averaged because they were trained and calibrated for different tasks.

## Supported evidence relationships

| YOLO visual cue | May support BERT category |
|---|---|
| `ACTIVITY MESSAGE` | `social_proof` |
| `COUNTDOWN TIMER` | `false_urgency` |
| `DEFAULT CHOICE` | `forced_consent` |
| `HIGH DEMAND MESSAGE` | `false_scarcity`, `social_proof` |
| `LIMITED TIME MESSAGE` | `false_urgency` |
| `LOW STOCK MESSAGE` | `false_scarcity` |

`ATTENTION DISTRACTION`, `DISGUISED ADS`, `GAMIFICATION`, and `NAGGING`
remain standalone visual cues because the current BERT taxonomy has no
unambiguous equivalent.

## Spatial requirement

The API creates a fusion link only when a compatible visual cue overlaps the
smaller text/visual region by at least 50%. This prevents unrelated evidence on
the same page from being presented as corroboration. A link references the
corresponding entries by `text_finding_index` and `visual_cue_index` and records
the measured overlap and rationale.

## Failure behavior

Text analysis remains available if the optional visual model is missing or its
inference fails. The scan is returned as `completed_with_warnings`, with the
failure recorded in `warnings`. A missing validated BERT artifact still returns
HTTP 503 because text classification is the primary analysis path.

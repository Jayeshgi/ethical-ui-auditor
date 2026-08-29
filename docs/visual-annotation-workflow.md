# Visual Annotation Workflow

The downloaded ContextRico-DP source is CC BY 4.0 and has image-level labels,
not bounding boxes. It must therefore be manually reviewed before augmenting
the YOLO detector. The original `data/visual_dataset/test` split remains an
unchanged held-out test set.

## Create review tasks

From the repository root:

```powershell
& '.\.venv\Scripts\python.exe' tools\build_visual_annotation_queue.py
```

This creates `data/annotation_queue/contextrico/` with 647 compatible tasks,
a Label Studio interface configuration, and a manifest. Suggested labels are
only prompts: draw a tight box only around a cue you can verify in the image.
Choose `no_compatible_cue` when the screenshot-level source label does not map
to a visible cue in this project's ten-class taxonomy.

## Annotate in Label Studio

Install and start Label Studio outside this repository, then enable its local
file serving with the project directory as document root:

```powershell
$env:LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED = 'true'
$env:LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT = 'C:\Major project'
label-studio start
```

Create a project, paste `label_config.xml` into its labeling setup, and import
`tasks.json`. Each reviewer should work from the source-label hint but verify
the visual location and class. Export completed annotations as JSON after a
second reviewer resolves ambiguous cases.

To prefill only high-confidence, text-localisable candidates, run:

```powershell
$env:PYTHONPATH = 'C:\Major project\backend'
& '.\.venv\Scripts\python.exe' tools\propose_text_localized_boxes.py
```

Import `tasks_with_machine_proposals.json` instead of `tasks.json` to see the
proposals. Review every proposed box; this automation deliberately excludes
visual-only cues such as default choice, disguised ads, and nagging.

For a second, calibrated pass that combines OCR and YOLO while removing
perceptual duplicates of the original splits, run:

```powershell
$env:PYTHONPATH = 'C:\Major project\backend'
& '.\.venv\Scripts\python.exe' tools\propose_visual_boxes.py
```

The resulting `tasks_with_max_proposals.json` includes only proposals meeting
per-class validation thresholds. To create a gated pseudo-labelled experiment:

```powershell
& '.\.venv\Scripts\python.exe' tools\build_pseudo_visual_dataset.py
```

Pseudo-labelled images enter training only; the real-labelled validation and
test splits remain unchanged. Keep new weights only if the unchanged test
metrics improve over the v1 baseline.

Do not use the supplied screenshot-level label as a full-image bounding box;
that produces invalid object-detector training data.

## Import reviewed boxes and retrain

Export completed tasks from Label Studio as JSON, then create a new dataset:

```powershell
& '.\.venv\Scripts\python.exe' tools\import_label_studio_yolo.py 'C:\path\to\project-export.json'
```

The tool accepts only boxes from completed tasks and writes a separate
`data/visual_dataset_reviewed/` directory. It copies the original test split
unchanged, so the original baseline remains comparable. Once enough reviewed
boxes are imported, train against the new `data.yaml`:

```powershell
$env:PYTHONPATH = 'C:\Major project\backend'
& '.\.venv\Scripts\python.exe' -m training.train_visual --data 'C:\Major project\data\visual_dataset_reviewed\data.yaml' --epochs 100 --batch 8
```

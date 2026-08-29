# YOLO26 Visual-Cue Model Results

The visual detector was fine-tuned from `yolo26n.pt` on an NVIDIA GeForce RTX
4050 Laptop GPU with 6 GB VRAM. Training used 640-pixel images, batch size 8,
seed 42, automatic mixed precision, and early stopping with patience 20.

The downloaded Roboflow export contains 499 screenshots: 354 training, 93
validation, and 52 test images. Its `NO DP` annotations were removed as objects;
the corresponding screenshots were retained as background examples. The model
therefore detects ten positive visual-cue classes.

Training stopped after 54 of the requested 100 epochs and produced the following
held-out test results:

| Metric | Result |
|---|---:|
| Precision | 0.368 |
| Recall | 0.187 |
| mAP@50 | 0.185 |
| mAP@50-95 | 0.108 |

The best checkpoint is stored at
`model_artifacts/dark_pattern_yolo_v1/best.pt`. GPU inference was verified after
training. These results establish a working visual baseline, but they are too
weak for reliable deployment. Several categories contain only one to three test
objects, and some training categories contain fewer than ten objects. The next
quality step is to add more reviewed bounding-box examples per class or merge a
compatible dataset after checking taxonomy and source-page leakage.

## Calibrated pseudo-label v2 experiment

ContextRico-DP supplied 1,609 additional screenshots with screenshot-level
labels. Because it does not supply bounding boxes, the images were not treated
as direct YOLO ground truth. A second proposal pass combined OCR-localized
phrases with v1 detections constrained to each screenshot's supplied category.
Per-class confidence thresholds were selected on the existing real-labelled
validation split.

Perceptual-hash comparison excluded 265 transformed duplicates of existing
images, including 24 near-duplicates of test images. From the remaining 382
unique candidates, the calibrated process retained 79 boxes in 40 screenshots:
68 `DEFAULT CHOICE` and 11 `NAGGING`. These pseudo-labelled screenshots entered
training only. The original 93-image validation and 52-image test splits stayed
unchanged.

The v2 experiment fine-tuned the v1 checkpoint and stopped after 38 epochs. Its
unchanged-test comparison is:

| Metric | v1 baseline | v2 pseudo-label experiment | Relative change |
|---|---:|---:|---:|
| Precision | 0.368 | 0.660 | +79.6% |
| Recall | 0.187 | 0.227 | +21.5% |
| mAP@50 | 0.185 | 0.261 | +40.9% |
| mAP@50-95 | 0.108 | 0.155 | +43.4% |

The v2 checkpoint is stored at `model_artifacts/dark_pattern_yolo_v2/best.pt`.
It is the stronger research checkpoint, but it remains non-compliance-grade:
the test set is small, several classes have one to three objects, and the new
boxes are calibrated machine proposals rather than independently reviewed
human annotations.

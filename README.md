# OMR from Smartphone Photos

This project prepares an OMR workflow for reading 100-question answer sheets photographed by mobile phones. It compares a CLA-style bubble-fill baseline with a small CNN and evaluates a first-photo workflow against an A-then-B confirmation workflow.

## Try the local application

Double-click `start_omr.cmd` or run `.\tools\start_omr_app.ps1`, then open
`http://127.0.0.1:8765`. An exam key is optional: upload one image or try a sample
to read answers. Example-key grading is explicitly labeled as a demo.
See [APP_RUNBOOK.md](APP_RUNBOOK.md) and [SYSTEM_TEST_RESULTS.md](SYSTEM_TEST_RESULTS.md).

The current completion plan targets 28 October 2026: a usable local system,
CLA/CNN comparisons and operational testing across all 270 verified pairs.
See [PROJECT_COMPLETION_PLAN.md](PROJECT_COMPLETION_PLAN.md) for the scope,
remaining work and acceptance criteria. Existing smoke tests do not establish
that the full system is complete.

> The repository intentionally excludes the collected answer-sheet photos and any completed ground-truth labels. Pair images and transcribe visible marks locally before training; the blank templates are not labeled data.

## Workflow

The user has fixed the final dataset at **270 pairs / 540 A/B images**, with no
additional image collection. The earlier 295-pair target is historical.
All 594 originals are kept:
540 primary images, 47 duplicate copies, six single images awaiting counterparts,
and one additional capture. Ground truth for all 270 sheets would require 27,000 observed
answers; the current official review contains 4,760 answers.

The first development run uses the 38 sheets already reviewed in full (3,800
labels), retaining the other 960 inspected labels in the canonical table. Run
`python tools/prepare_reviewed_pilot.py` for the local metadata subset, or use
`notebooks/omr_reviewed_pilot.ipynb` in Kaggle. This assisted pilot does not report
independent final test accuracy, and uses no tentative drafts as labels.
`python tools/package_reviewed_pilot.py` bundles its 76 photos, metadata and code
into one Kaggle upload ZIP. Marker registration and row crops are shared by
the CLA and CNN inputs; a fallback references other Train sheets only.

1. Build or refresh the inventory: `python tools/build_dataset_manifest.py`.
2. Generate the local image pairing page: `python tools/build_pair_review.py`. Open `data/metadata/pair_review.html` and confirm one A/B retake pair per sheet. Use the JSON backup button during review.
3. Export `pair_decisions.csv` into `data/metadata/` and apply it: `python tools/apply_pair_decisions.py`.
4. Refresh answer rows with `python tools/build_answer_labels_template.py` (existing labels are preserved). Build the click-to-label page with `python tools/build_answer_review.py`, open `data/metadata/answer_review.html`, and record the marks actually visible on each verified sheet. Export CSV and import it with `python tools/apply_answer_labels.py <exported.csv>`.
5. Create reproducible sheet-level splits: `python tools/create_sheet_splits.py`.
6. Convert selected HEIC photos if needed: `python tools/convert_heic.py`.
7. Validate the data: `python tools/validate_dataset.py`.
8. Upload the private data and code datasets to Kaggle and run `notebooks/omr_kaggle.ipynb`. See [KAGGLE_RUNBOOK.md](KAGGLE_RUNBOOK.md).

The supported ground-truth classes are `1`–`5`, `blank`, `multiple`, and `ambiguous`. A/B images from the same sheet always stay in the same split. Metrics must be reported from the held-out Test sheets only.

## Read with the trained model

The returned Kaggle weights are stored locally at `models/row_cnn.pt` (ignored
by Git). Run `.\tools\read_model_sheet.ps1 -Sheet S0035` to read an existing
verified sheet and generate `presentation_build/model_inference/S0035/report.html`.
Predictions remain model drafts and do not modify human labels. See
[models/README.md](models/README.md) for the CLI, requirements and limitations.

The confirmed-label fine-tuning run accepts inspected answers on incomplete
sheets, preserving the original splits and the ten-sheet evaluation cohort.
See [RETRAINING_RUNBOOK.md](RETRAINING_RUNBOOK.md) and
`notebooks/omr_retraining_v2.ipynb`. Original weights and annotations remain intact.
The completed CPU run selected epoch 9; versioned weights/config and evaluation
are in [models/retrained_v2/README.md](models/retrained_v2/README.md).
Use `.\tools\read_model_sheet.ps1 -Sheet S0035 -ModelDir models/retrained_v2`
to read with this version. Its 99.8% A-only / 99.9% A-then-B results refer to
the existing ten-sheet development retest, not all 270 paired sheets.

The web app now uses the shared perspective correction before both CNN and CLA,
including local row straightening on curved forms. Its profile is
`models/retrained_v2_perspective/`; weights and decision thresholds stay at v2.
See [PERSPECTIVE_FIX.md](PERSPECTIVE_FIX.md) and the latest section of
[SYSTEM_TEST_RESULTS.md](SYSTEM_TEST_RESULTS.md) for verification and limitations.

For the risk-first review policy, validation experiments, read-only dataset audit,
and real HTTP smoke test, see [OMR_IMPROVEMENT_RESULTS.md](OMR_IMPROVEMENT_RESULTS.md).

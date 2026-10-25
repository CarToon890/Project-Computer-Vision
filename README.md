# OMR from Smartphone Photos

This project prepares an OMR workflow for reading 100-question answer sheets photographed by mobile phones. It compares a CLA-style bubble-fill baseline with a small CNN and evaluates a first-photo workflow against an A-then-B confirmation workflow.

> The repository intentionally excludes the collected answer-sheet photos and any completed ground-truth labels. Pair images and transcribe visible marks locally before training; the blank templates are not labeled data.

## Workflow

1. Build or refresh the inventory: `python tools/build_dataset_manifest.py`.
2. Generate the local image pairing page: `python tools/build_pair_review.py`. Open `data/metadata/pair_review.html` and confirm one A/B retake pair per sheet. Use the JSON backup button during review.
3. Export `pair_decisions.csv` into `data/metadata/` and apply it: `python tools/apply_pair_decisions.py`.
4. Generate blank answer rows for the verified sheets with `python tools/build_answer_labels_template.py`, then record the marks actually visible on each verified sheet.
5. Create reproducible sheet-level splits: `python tools/create_sheet_splits.py`.
6. Convert selected HEIC photos if needed: `python tools/convert_heic.py`.
7. Validate the data: `python tools/validate_dataset.py --require-300`.
8. Upload the private data and code datasets to Kaggle and run `notebooks/omr_kaggle.ipynb`. See [KAGGLE_RUNBOOK.md](KAGGLE_RUNBOOK.md).

The supported ground-truth classes are `1`–`5`, `blank`, `multiple`, and `ambiguous`. A/B images from the same sheet always stay in the same split. Metrics must be reported from the held-out Test sheets only.

# Run the OMR comparison in Kaggle

The project has 594 source photos from 9 contributors. They are not yet paired or labeled, so the model cannot be evaluated until the human review steps below are complete. Do not treat the 30,000 blank rows in the template as labels.

## Prepare and review the source data locally

1. Open `data/metadata/pair_review.html` in a browser. For each physical sheet, select one A and one B photo from the same contributor and verify the same answer marks/page details. File order and filename are not reliable.
2. Use **บันทึกสำรอง JSON** to back up browser progress regularly. Export `pair_decisions.csv` when finished and copy it to `data/metadata/pair_decisions.csv`.
3. Run `python tools/apply_pair_decisions.py`. This writes `data/metadata/image_inventory_verified.csv` without changing the original inventory.
4. Copy `data/metadata/answer_labels_template.csv` to `data/metadata/answer_labels.csv`. Assign each verified sheet ID and record the marks visible on the paper for questions 1–100 as `1`–`5`, `blank`, `multiple`, or `ambiguous`. These are observed marks, not exam answers.
5. Run `python tools/create_sheet_splits.py`. The script groups by sheet so A and B always stay together.
6. Run `python tools/convert_heic.py` if any selected images are HEIC/HEIF. It creates JPEG copies and a mapping file while preserving the originals.
7. Check the preparation: `python tools/validate_dataset.py --require-300`. It should report `READY` before upload. If fewer than 300 verified sheets are available, omit `--require-300` and document the actual count; all available verified sheets still need complete labels and split assignments.

## Upload private Kaggle datasets

- **OMR data:** include `Dataset-Computer-vision/` and `data/metadata/`. Include `data/normalized_images/` when HEIC conversions were made. Preserve relative paths.
- **OMR code:** include `src/omr_pipeline.py` in a separate Kaggle Dataset.
- Attach both datasets as notebook inputs and open `notebooks/omr_kaggle.ipynb`.
- Notebook dependencies are listed in `requirements.txt`; install them in Kaggle if the environment does not already provide them.

The notebook writes `evaluation.json`, CLA/CNN test predictions, and `row_cnn.pt` under `/kaggle/working/omr-results/`. Results are not generated before human pairing and transcription are complete. Report metrics only after running on the held-out sheet-level Test split.

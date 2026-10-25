# OMR dataset bookkeeping

`image_inventory.csv` is a non-destructive inventory of the source images.
It records the source path, contributor folder, file properties, capture time
when available, and A/B only when the source folder explicitly names that role.
It deliberately leaves `sheet_id` and `pair_id` blank until the two images are
visually confirmed to show the same physical sheet.

## Pairing workflow

1. Filter by contributor and review images side by side. Capture time can help
   find candidates, but it does not prove a pair.
2. Confirm that all 100 answer marks and page-specific details match. A and B
   must show the same answers; a clearer or differently angled retake is okay.
3. Assign one stable `sheet_id` such as `S0001` to both rows, set `pair_id` to
   the same value, set roles to `A` and `B`, then change `pair_status` to
   `verified`.
4. Use `needs_pair_review` for uncertain candidates and `missing` if a retake
   cannot be found. Never split A and B from one sheet across data splits.
5. Use `excluded` for source photos intentionally omitted from the dataset.
   Record them in `excluded_images.csv`; keep the original files for traceability.

Record each human-confirmed pair in `pair_decisions_template.csv`. The
`image_a_id` and `image_b_id` values come from the inventory's `image_id`
column. Save the filled copy as `pair_decisions.csv`, then run
`python tools/apply_pair_decisions.py`. This writes
`image_inventory_verified.csv` without overwriting the original inventory.
Generate grouped splits from that verified copy with
`python tools/create_sheet_splits.py`.

The source image files are not renamed or moved. `relative_path` points to the
original file, so the inventory can be regenerated with:

```powershell
python tools/build_dataset_manifest.py
```

## Exact duplicate files

`duplicate_images.csv` records byte-identical files that should not count as
separate captures. Keep the source files for traceability; the manifest builder
marks the redundant copy with `pair_status=duplicate` and
`duplicate_of_image_id`. Do not use duplicate copies to form A/B pairs or to
increase the sample count.

## Intentionally excluded images

`excluded_images.csv` records source photos omitted from the usable dataset.
The manifest builder marks these rows with `pair_status=excluded` while keeping
the source files in place. To restore an excluded photo, remove its row from
this ledger and rebuild the inventory.

Open `pair_review.html` in a browser to compare source photos. The page creates
thumbnails for JPG and HEIC files, lets a reviewer choose A and B, and exports
the confirmed rows as `pair_decisions.csv`. Pairing progress is stored in that
browser; use **บันทึกสำรอง JSON** to keep a portable backup before switching
devices or browsers.

## Ground-truth labels

Fill `answer_labels_template.csv` after assigning sheet IDs. Add one row per
question, with `question_no` from 1 to 100 and `ground_truth` set to `1`, `2`,
`3`, `4`, `5`, `blank`, `multiple`, or `ambiguous`. These are the marks visible
on the paper, not the exam's answer key. The model's own low-confidence or
unreadable output should be recorded separately from ground truth.

## Current audit

The source folder contains 594 image files from 9 contributor folders: 464 JPG and
130 HEIC. Four folders declare A/B through subfolder names; five folders do
not. This count does not establish how many complete physical-sheet pairs are
present. HEIC files need conversion or a HEIC-capable reader for the Kaggle
pipeline; preserve the originals and keep the inventory paths unchanged.

During initial review, one same-order A/B example had different marked
answers. Pair by answer pattern across the candidate images, not by matching
filename number or list position. The inventory therefore leaves all
`sheet_id` and `pair_id` fields blank and all rows at `needs_pair_review`.

`answer_labels_template.csv` has 30,000 empty question slots for the planned
300 sheets. Assign verified sheet IDs first, then fill the visible answer
marks. These blank rows are annotation slots, not labeled data.
## Project file preparation

The current implementation is ready for human data preparation and then Kaggle execution:

- `tools/build_dataset_manifest.py` creates the source inventory and blank answer template.
- `data/metadata/pair_review.html` is the browser tool for manually confirming shuffled A/B retakes.
- `tools/apply_pair_decisions.py` writes a verified inventory after matching.
- `tools/create_sheet_splits.py` keeps both photos of a sheet together in reproducible Train/Validation/Test splits.
- `tools/validate_dataset.py` checks image files, one A/B pair per sheet, all 100 non-empty ground-truth rows, and split assignments.
- `src/omr_pipeline.py` runs the CLA baseline and CNN comparison, including A-only versus A-then-B workflows.
- `notebooks/omr_kaggle.ipynb` is the Kaggle entry point. See `KAGGLE_RUNBOOK.md` for the exact sequence.

No model results are claimed yet: there are no human-verified pairs or ground-truth labels. The 30,000 rows in the answer template are empty annotation slots.

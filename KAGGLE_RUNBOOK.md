# Run the OMR comparison in Kaggle

The user fixed the final dataset at 270 verified pairs / 540 primary photos, with no further image collection. The old 295-pair goal is historical. The 594 original files include those 540 images, 47 byte-identical extra copies, six unpaired photos and one additional capture. No images are currently classified as excluded. Keep originals and use the metadata ledgers for eligibility. Full transcription of all 270 sheets would require 27,000 observed answers; blank slots and unreviewed OMR drafts are not labels.

## First development pilot

Use `notebooks/omr_reviewed_pilot.ipynb` for the next experiment. It selects the
38 sheets already inspected in full, using 76 original images and 3,800 human
labels. Original splits remain 25 Train / 3 Validation / 10 Test sheets. The
other 960 inspected labels remain in the source CSV; no tentative draft enters
the pilot. Multiple/ambiguous classes have no pilot examples yet. Output metrics
are marked `assisted_development_pilot` and `independent_evaluation=false`.

Run `python tools/package_reviewed_pilot.py` after preparing the subset. The
ready-to-upload folder is `presentation_build/kaggle_reviewed_pilot/` and contains
`omr_reviewed_pilot.zip` plus `omr_reviewed_pilot.ipynb`. The ZIP includes all 76
selected original photos, four metadata files and the required source modules,
so only one private Kaggle Dataset is needed for this pilot. The notebook accepts
the explicit 38-sheet subset while retaining the final 270-pair project scope.

`python tools/prepare_reviewed_pilot.py` also creates the same reviewed subset
under `presentation_build/reviewed_pilot_270/` for local inspection. Its metadata
passes dataset validation. The first GPU pilot has now completed on Kaggle and
its returned evaluation is archived locally under
`presentation_build/kaggle_run_20261026/91d4b3b0d777/`. CPU Torch is now installed
locally in the ignored `.local_model_deps/` folder for saved-model inference;
the training dependencies are not fully installed locally. The original full-dataset notebook below remains
strict and should not be run against incomplete human labels.

The received `row_cnn.pt` is saved under `models/` with a checksum and fixed
Validation cutoff in `model_config.json`. Run
`.\tools\read_model_sheet.ps1 -Sheet S0035` to produce a read-only HTML report
and draft CSV without retraining or changing human labels. See `models/README.md`.
Local inference on S0035 and S0012 reproduces all 200 original Kaggle answers
and A/B fallback choices. This checks deployment compatibility, not accuracy
on unseen sheets or the entire 270-pair set.

A second confirmed-label fine-tuning run has now completed locally on CPU;
Kaggle is optional for reproducing it. It uses 3,259 Train questions and 400
Validation questions without requiring complete sheets. The original ten-sheet
Test cohort is retained. See `RETRAINING_RUNBOOK.md` and `models/retrained_v2/README.md`
for the selected epoch, same-validation recalibration comparison and deployment.
The original Kaggle run and weights remain intact.

The received pilot evaluated 10 Test-split sheets / 1,000 questions: CLA A-only
matched 946; CNN A-only matched 928; CNN A-then-B matched 990, with 3 wrong
non-deferred predictions and 7 deferrals. CNN used B for 69 question rows.
CLA used B for zero question rows, because its current workflow only invokes B
for `ambiguous` without a supplied confidence cutoff. Its 49 false-blank outputs
did not trigger B. This exposes a workflow limitation; equal CLA A-only/A-then-B
metrics do not establish that a second image cannot help CLA. Obtain the two
per-question prediction CSVs before inspecting errors or revising the next run.
These are assisted development results, not independent accuracy on all 270 pairs.

After inspecting original A/B crops, the user confirmed three reference-label
corrections in S0012: question 41 = 5, question 50 = 1, question 64 = 2. They are
all Test-split labels; Train/Validation labels, model outputs and cutoffs remain
unchanged. A separate rescore gives CNN A-then-B **993/1,000 correct and 7
deferrals**, and CLA **949/1,000 correct**. This is a post-label-correction
rescore, not a new training run or an independent test. Original Kaggle files
and the original upload ZIP remain intact; corrected reports are in
`presentation_build/kaggle_run_20261026/91d4b3b0d777/s0012_corrections/rescored/`.

The current review has 4,760 human-inspected answers and 38 fully labeled sheets.
All 859 unheld tasks in the original review queue are complete. The remaining
answers include tentative OMR drafts. The invalid S0294 pair has been withdrawn
and its two originals are now unpaired. Do not run the
full-dataset training command yet. All 101 alternative-image drafts were inspected
and imported from `answer_labels_review (2).csv`; the refreshed page has no
remaining tasks in that supplemental round. The original proposal runs remain
fixed. See `data/metadata/README_DATASET.md` for current counts.

The later paired-score refinement adds 4,242 tentative drafts to the annotation
page. They remain outside official human labels. S0295 has 96 further cached
values awaiting confirmation of visual review. The former S0294 images and two
previously excluded Moast images are retained as four single images awaiting
counterparts. They do not enter the paired A/B experiment.
Neither set should be promoted to training ground truth from a populated-slot
count alone. The official label count remains 4,760 until a confirmed import.

## Prepare and review the source data locally

1. Open `data/metadata/pair_review.html` in a browser. For each physical sheet, select one A and one B photo from the same contributor and verify the same answer marks/page details. File order and filename are not reliable.
2. Use **บันทึกสำรอง JSON** to back up browser progress regularly. Export `pair_decisions.csv` when finished and copy it to `data/metadata/pair_decisions.csv`.
3. Run `python tools/apply_pair_decisions.py`. This writes `data/metadata/image_inventory_verified.csv` without changing the original inventory.
4. Refresh rows for confirmed sheets: `python tools/build_answer_labels_template.py`. It preserves existing answers and backs up the previous CSV. Build `data/metadata/answer_review.html` with `python tools/build_answer_review.py` and use it to transcribe questions 1–100 as `1`–`5`, `blank`, `multiple`, or `ambiguous`. These are observed marks, not exam answers. Start with a 10-sheet pilot, save CSV/JSON backups regularly, and import exported answers with `python tools/apply_answer_labels.py <exported.csv>`. The importer ignores blank cells and rejects conflicting answers by default.
5. Run `python tools/create_sheet_splits.py`. The script groups by sheet so A and B always stay together.
6. Run `python tools/convert_heic.py` if any selected images are HEIC/HEIF. It creates JPEG copies and a mapping file while preserving the originals.
7. Check the preparation: `python tools/validate_dataset.py`. For the full-dataset run, all 270 sheets must have complete human labels and split assignments. The reviewed pilot instead validates its selected 38 sheets only.

## Upload private Kaggle datasets

- **OMR data:** include `Dataset-Computer-vision/` and `data/metadata/`. Include `data/normalized_images/` when HEIC conversions were made. Preserve relative paths.
- **OMR code:** include `src/omr_pipeline.py`, `src/omr_geometry.py`, and `tools/build_answer_pilot.py`, preserving their directory layout. The reviewed pilot ZIP already bundles them with its photos.
- Attach both datasets as notebook inputs and open `notebooks/omr_kaggle.ipynb`.
- Notebook dependencies are listed in `requirements.txt`; install them in Kaggle if the environment does not already provide them.

The notebook writes `evaluation.json`, CLA/CNN test predictions, and `row_cnn.pt` under `/kaggle/working/omr-results/`. Results are not generated before human pairing and transcription are complete. Report metrics only after running on the held-out sheet-level Test split.

Image preparation uses the form markers and detected row centers rather than
requiring a visible outside paper boundary. A spatially guarded fallback uses
an unrelated Train-sheet form reference, never the current sheet's B photo.
Only source pixels are warped; reference answer labels never fill any target.

# OMR dataset bookkeeping

## Review update — 27 October 2026

The user confirmed visual review of the new sheet and row confirmations in
`answer_review_backup (1).json`, including S0295. Imported 1,833 new answers
without overwriting existing answers or changing images, pairs, or splits.
There are now 6,593 confirmed answers: Train 5,092, Validation 400, Test 1,101;
57 sheets are complete and 20,407 answer slots remain unconfirmed. All new
answers belong to Train. The backup, staged CSV, source hash and pre-import
label backup remain local; model weights and existing evaluation are unchanged.
The review used model-assisted drafts, so it does not establish independent
model accuracy.

The subsequent `answer_review_backup (2).json` added 168 explicit human
confirmations from the CNN/CLA risk queue across three Train sheets. It had no
conflicts with existing answers and no pending pair holds. The official table now
contains 6,761 confirmed answers: Train 5,260, Validation 400, Test 1,101; 57
sheets are complete and 20,239 slots remain unconfirmed. The input fingerprint,
images, pairs, split, model weights and existing evaluation are unchanged.

On 28 October `answer_review_backup (3).json` added 392 human confirmations
from the model-assisted risk queue across 64 sheets, without conflicts or held
pairs: Train 331, Validation 33, Test 28. The official table now has 7,153
confirmed answers: Train 5,591, Validation 433, Test 1,129; 61 sheets are fully
labeled and 19,847 slots remain unconfirmed. Historical CNN/CLA comparisons on
these 392 selected risk cases are development diagnostics, not independent
accuracy. No new model training or selection was performed.

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

Refresh `answer_labels.csv` with `python tools/build_answer_labels_template.py` after assigning sheet IDs. Existing answers are preserved and backed up. Use one row per
question, with `question_no` from 1 to 100 and `ground_truth` set to `1`, `2`,
`3`, `4`, `5`, `blank`, `multiple`, or `ambiguous`. These are the marks visible
on the paper, not the exam's answer key. The model's own low-confidence or
unreadable output should be recorded separately from ground truth.

Build `answer_review.html` with `python tools/build_answer_review.py`. It shows
the verified A/B photos, supports keyboard shortcuts and zoom, and saves browser
progress automatically. Start with 10 sheets, then check and continue in batches.
Use **ส่งออก answer_labels_review.csv** and **สำรอง JSON** before taking a break.
The page saves to the browser and Downloads, not directly into the project CSV.
Import the export with `python tools/apply_answer_labels.py <exported.csv>`.
Empty cells never erase existing labels; conflicting answers require an explicit
`--overwrite`. Keep `annotation_previews/` beside the page for HEIC previews.

For the ten-sheet assisted pilot, run `python tools/build_answer_pilot.py` after
creating previews, then rebuild the page with `python tools/build_answer_review.py`.
The provisional marker reader writes `answer_pilot_proposals.json` and row crops
under `answer_pilot_assets/`; neither is ground truth. Keep the proposals fixed
throughout review. Approve each proposal only after inspecting the marks, or
select a corrected answer. The current user-selected `omr_assisted` mode shows
proposals for every split, including Test. The bulk review workflow described
below can prefill tentative drafts; it does not prefill official ground truth.
Whole-sheet review must be checked before the page calculates agreement.
Export the batch-specific `answer_pilot_evaluation_*.csv` alongside the ordinary
answer CSV for the comparison. Its `matches_reviewed_label`, `annotation_mode`,
`evaluation_type` and `independent_evaluation=false` fields describe agreement
after assisted review, not independent final model test performance. A page
without the assisted mode retains the earlier Test-blind behavior.

Prepare the next batch with `python tools/build_answer_pilot.py --start S0011 --end S0035`,
then rebuild the page. A new batch may contain at most 25 verified sheets.
Earlier proposals and their original run IDs are retained. Existing proposals
are never replaced unless `--force` explicitly restarts exactly that whole batch.
The page opens the newly prepared batch while keeping previous browser answers,
and provides a batch selector for progress and evaluation exports.
The v1.3 reader selects the three form markers by their joint geometry rather
than picking extreme squares from background texture. It then tries illumination
normalization, then a printed-feature homography against a registered form.
Answer-circle regions are excluded from reference feature detection. A fallback
homography requires at least 40 inliers spread across more than 35% of the page,
with upper and lower support, and its rows are flagged for closer inspection.
Unregistered images retain an error rather than producing guessed answers.
Pending A/B pairing holds block proposal generation.

### Bulk drafts and a bounded review queue

The user reported progress through **S0038**. The current page preserves browser
entries and begins automatic drafts at **S0039**. `answer_assistance.py` builds
a deterministic queue of **800 risk items and 200 confidence-sample items**,
spread across contributors. Disagreements, special marks and weak readings
receive priority. High-confidence here means the reader's heuristic flag;
it is not a calibrated correctness probability. The surviving frozen workload
has 15,525 original high-flag auto-draft candidates, including rows later reviewed.
Existing entries, visual drafts and explicit clear
tombstones take precedence, so actual additions depend on browser progress.
`answer_review_workload.json` freezes this queue while answers are imported;
rebuilding the same page does not silently assign another 1,000 tasks.
After the confirmed Nat repair, 114 tasks belonging to retired records were
archived, leaving **886 existing tasks (701 risk / 185 sample)**. No replacement
tasks were added. The page displays the actual surviving queue counts.
The later human export contains all 886 task decisions plus one extra answer.
Its 28 ambiguous rows all belong to S0294, whose original A/B answer patterns
conflict: 27 are queue tasks, and question 46 is an additional off-queue review.
Those 27 tasks were initially paused and later archived when the user withdrew
the mismatched pair. The current queue has **859 tasks (674 risk / 185 sample),
all with imported human answers**. All 28 submitted S0294 answers remain archived.

`answer_assistance.js` displays up to ten image rows at once. Small row previews
under `answer_review_assets/` avoid decoding a full 100-row image per card.
Large answer buttons confirm a row in one click; “correct as shown” accepts its
displayed value. Completed cards keep their slots until the group is finished,
then the next ten appear automatically. A sticky action bar confirms remaining
visible rows with Ctrl+Enter. Queue keyboard shortcuts support 1–5/B/M/U,
Enter, arrows and S (defer). Ctrl+Z undoes the last queue transaction and restores
the previous tentative provenance without replacing subsequent manual edits.
Held keys do not repeatedly confirm rows. Existing pending dropdown edits from
older browser states are retained when upgrading the page.
Individual human review is stored in `answerMeta` with the reviewed value;
machine-filled values remain tentative. Existing whole-sheet review flags
migrate to inspected answers, while unreviewed legacy values remain intact
without being silently certified. Routine display changes keep the browser
fingerprint stable; pairing repairs migrate progress to the new fingerprint.
The prior state is also retained under a `-before-bulk-review` backup key.

- `answer_labels_review.csv` contains only human-inspected answers, with other
  question slots blank. The normal label importer remains compatible.
- `answer_omr_drafts.csv` contains remaining proposals and entries with source,
  label status, queue type, image IDs and method/run provenance. It deliberately
  has no `ground_truth` column, so the label importer rejects it as training truth.
- JSON backups retain draft/human provenance and pending review edits.

Completing the 1,000-item queue does not certify the remaining answers. The
confidence sample is for finding faults and planning further review; it does
not establish independent final model accuracy or certify the full dataset.

After the S0294 pause, all 859 unheld original queue items have imported human
answers (674 risk and 185 sample). The confidence sample contains one correction
to the frozen proposal; these assisted comparisons are not independent accuracy.
The user additionally confirmed S0053 question 61 as 5 and S0056 question 64 as 4
from matching A/B row marks. The correction ledger updates older browser values
once, while preserving subsequent intentional edits.

The first version of `answer_draft_supplement.py` prepared 101 tentative drafts from A
where the frozen B reading is uncertain/blank and A passes its existing confidence
flag with a single numeric answer. It preserves the original reader runs,
score thresholds, frozen queue, manual answers, cleared entries, and pairing holds.
The optional **ตรวจร่างเสริมจากภาพ A 101 ข้อ** view uses the existing ten-card
controls without adding tasks to the original queue. These A/B disagreements
still require visual review. Original-run agreement exports continue to compare
against the frozen B proposals; draft exports identify the supplemental method
and run separately. A draft never enters the human label export until inspected.

The later `answer_labels_review (2).csv` contains 4,760 inspected answers,
including all 101 supplemental rows. Import added exactly those 101 answers,
preserving all 4,659 earlier nonempty values and the three confirmed corrections.
All 101 inspected values match their supplemental proposals, and there are no
new ambiguous rows. This is agreement after assisted review, not independent
accuracy. The refreshed page removes the completed supplemental view without
replacing the original queue. Its exact proposal set, original upload, prior
labels and verification report are archived in
`presentation_build/answer_review_import_20261026_round2/`.
There are now 38 fully labeled sheets and 22,240 unheld question slots without
human-inspected labels; tentative OMR drafts remain separate from these labels.

### Paired-score draft refinement

The archived `answer_review_backup.json` retains 20,150 browser entries at
fingerprint `2819904ece2f7fcd`. Its S0295 whole-sheet flag contains 96 additional
values beyond the four already imported. These 96 values remain pending an
explicit confirmation of visual review; merely having 100 populated slots is
not sufficient. They have not changed `answer_labels.csv`. Cached S0294 answers
remain archived in the old cache and backups, outside current human-label exports.

`omr_pair_reading.py` fixes a reproduced faint-mark failure: S0221 question 29
has matching option-4 peaks in A/B, but the old B-only classification is blank.
The new `paired-image-draft-v2` policy retains the original A-confident fallback,
and also permits a numeric draft when both registered rows have the same highest
score, each peak is at least 0.08, and each first/second margin is at least 0.04.
Missing/flat/nonfinite evidence, contradictory peaks, and multiple/ambiguous
readings cannot enter this new consensus branch. The frozen single-image scores,
predictions, original queue, sheet identities and official labels remain fixed.

Threshold probes used reviewed Train labels for selection. The resulting paired
policy matches 350/350 eligible reviewed Train rows and 37/37 Validation rows;
the old B-first output matches 31 and 1 respectively on those same selected rows.
These are assisted development diagnostics on a selected subset, not independent
accuracy or a guarantee for the remaining answers. Test labels were not scored
for selecting this policy. A contributor-spread and boundary-focused visual check
of 40 additional rows found consistent marks; those checks are not human labels.

The page prepares **4,242 additional tentative drafts** across seven contributors.
Replaying the actual backup verifies that all 20,150 existing values survive,
all new drafts stay unverified. The later orphan classification archives S0294
and its 27 held tasks; all 859 completed tasks remain in their original order.
No additional human review tasks were assigned. The optional A/B draft view is
for inspection; the user does not need to review all 4,242 rows in this round.
The draft export identifies the paired method/run and has no `ground_truth`
column. Backup validation, score probes, draft candidates, visual contact sheets
and replay evidence are under `presentation_build/omr_refinement_20261026/`.

`answer_labels_codex_draft.csv`, when present, contains visual transcriptions by
Codex and the source image IDs. These remain separate from the official label
CSV. The page pre-fills them as drafts, flags selected rows for closer inspection,
and requires explicit row review or whole-sheet review before including draft
answers in exported ground truth. A new draft version resets that sheet's review flag once while
preserving manually entered answers. Draft-derived agreement is not an
independent final model evaluation.

`pairing_review_holds.csv` records reported pairing problems awaiting a new
human review. Existing mappings remain available for comparison, but affected
sheets are blocked in the annotation page and excluded from label exports.
The label importer, dataset validator and model pipeline reject unresolved
holds. Clear a hold only after applying the newly confirmed image pairing;
preserve any draft labels by their source image ID rather than blindly moving
them to a different physical sheet.

After applying a confirmed repair, `answer_pairing_migrations.json` records the
old and new page fingerprints and affected sheets. The annotation page copies
browser progress for unchanged pairs to the new fingerprint, discards cached
answers and review flags only for repaired sheets, and leaves the old cache
available as a backup. Frozen automatic proposals for changed pairs are
archived and removed from the active registry until they are regenerated.

The jilayu repair for S0035–S0066 was confirmed in
`jilayu_pair_review_decisions.csv`: A IMG_8831–IMG_8862 maps to B
IMG_8830–IMG_8799 in reverse order. S0034 is unchanged. The visual draft
originally attached to S0035 follows its source B image to S0066 and still
requires whole-sheet answer review. Repair evidence and pre-change backups
are retained locally in `presentation_build/jilayu_repair/`.

## Current audit

The user ended image collection and fixed the final scope at **270 pairs /
540 primary A/B images**. The earlier 295-pair target is historical; no additional
photos are required for this round. `dataset_scope.json` records that decision.
Original source files remain **594 files /
547 unique byte contents**. File-content counts do not count physical sheets.
The inventory statuses are **540 verified, 47 duplicate, 1 additional capture
and 6 awaiting correct counterparts**. There are no currently excluded images.
Only verified A/B records enter paired experiments, and training also requires
their human-inspected labels.

The Moast folder retains **30 active pairs, four single images awaiting
counterparts, and two byte-identical copies**, totaling 66 original files.
The four single images are `IMG_20261024_213350.jpg`,
`IMG_20261024_220627.jpg`, `IMG_20261024_215556.jpg`, and
`IMG_20261024_215619.jpg`. Their answer marks differ; none of their six possible
combinations is a valid identical-answer pair. The latter two files were moved
from the excluded classification back to `needs_pair_review` at the user's
request. No source file was deleted, renamed, moved or physically duplicated.

The invalid S0294 pair record is withdrawn and reserved in `retired_sheet_ids.csv`.
Its original pair decision, 100 empty official label slots, split entry, frozen
proposals and 27 previously held queue tasks are archived. Its two image rows
now have blank `sheet_id`/`pair_id` and appear in `unpaired_images.csv`.
The hold ledger marks the old record `retired`; no active pair has a pending
pairing hold. Original pre-change metadata and browser-state migration evidence
are under `presentation_build/moast_orphans_20261026/`.

The user confirmed nine Nat pairs: A/2–A/9 with B/2–B/9, and upside-down A/10
with B/1. They retain **S0068–S0076**. A/16 is an additional capture of S0072
and is not counted as a new pair. **A/1 and B/10 remain unpaired** according to
the user's explicit clarification after the review CSV's ambiguous final choice.
Old records **S0067 and S0077–S0099**, plus the later S0294 withdrawal, are
archived without renumbering other sheets. Nat has 45 extra byte-identical copies;
the full source audit and confirmed repair are in `presentation_build/nat_pairing_audit/`.

`unpaired_images.csv` is the active ledger for all **six singleton images**:
four Moast images and two Nat images. They may be used for exploratory
single-image OMR, with results kept outside paired A/B comparisons and official
training labels. The user will not collect further photos, so these six single
images stay outside the final paired set. Earlier capture-completion proposals
are historical and are not outstanding user tasks.

The working `answer_labels.csv` contains **27,000 slots for 270 sheets**, with
**4,760 official human-inspected answers**, 38 fully labeled sheets and 22,240
slots still without human-inspected labels. S0295 retains four imported answers;
its 96 additional cached values still await confirmation of actual visual review.
Current Train/Validation/Test assignments contain **198/33/39** sheets, with
every retained assignment unchanged. HEIC files require conversion or a
HEIC-capable reader for Kaggle; keep originals and inventory paths intact.

The original review allocation now retains **859/859 completed tasks**. Its
141 removed tasks (114 Nat, 27 S0294) stay archived, with no replacement tasks.
Frozen per-image predictions for the remaining 270 sheets are unchanged. The
4,242 paired-score draft candidates remain tentative and separate from official
labels. The browser fingerprint migrates from `2819904ece2f7fcd` to
`b7569dce5e487ff8`, preserving all active answers/provenance and retaining the
old cache as a backup for withdrawn records.

The older `answer_labels_template.csv` is a planning template and is not the
pipeline's label input. Empty slots are not labeled data.
## Project file preparation

The current implementation is ready for human data preparation and then Kaggle execution:

- `tools/build_dataset_manifest.py` creates the source inventory and blank answer template.
- `data/metadata/pair_review.html` is the browser tool for manually confirming shuffled A/B retakes.
- `tools/apply_pair_decisions.py` writes a verified inventory after matching.
- `tools/create_sheet_splits.py` keeps both photos of a sheet together in reproducible Train/Validation/Test splits.
- `tools/validate_dataset.py` checks image files, one A/B pair per sheet, all 100 non-empty ground-truth rows, and split assignments.
- `src/omr_pipeline.py` runs the CLA baseline and CNN comparison, including A-only versus A-then-B workflows.
- `notebooks/omr_kaggle.ipynb` is the Kaggle entry point. See `KAGGLE_RUNBOOK.md` for the exact sequence.

The first development pilot selects the 38
fully inspected sheets (76 images / 3,800 human labels), keeping original split
assignments at 25 Train / 3 Validation / 10 Test. The other 960 inspected labels
remain in the canonical CSV. `tools/prepare_reviewed_pilot.py` creates a validated
metadata subset in `presentation_build/reviewed_pilot_270/`, and
`notebooks/omr_reviewed_pilot.ipynb` prepares the same subset in Kaggle. Drafts are
not labels, and this assisted pilot is not independent final accuracy. The final
collection remains all 270 pairs; selecting 38 for development does not reduce it.

The user returned `evaluation.json` from the first Kaggle CUDA run. It matches
the prepared pilot's 25/3/10 sheet splits and 1,000 Test-split label supports.
CNN A-only matches 928/1,000; CNN A-then-B matches 990/1,000, with 3 incorrect
answers and 7 deferrals. CLA matches 946/1,000 in both workflows and never invokes
B in this run; 49 of its outputs mark labeled nonblank rows as blank. The returned
file and audited matrix counts are archived in
`presentation_build/kaggle_run_20261026/91d4b3b0d777/`. Per-question prediction
CSVs and model weights have not been received. Official labels remain 4,760,
and these OMR-assisted pilot results remain non-independent development evidence.

The subsequent original-photo review found three erroneous reference values in
S0012. The user explicitly approved question 41 from 3 to 5, question 50 from 2
to 1, and question 64 from 3 to 2. The correction ledger updates old browser
values once. Exactly those three canonical labels and current pilot labels were
changed; the official count stays 4,760. Original predictions and evaluation
files are untouched. A separate post-correction rescore yields CNN A-then-B
993 correct, zero incorrect answers and 7 deferrals out of 1,000; CLA yields
949 correct and 51 incorrect. These are reused predictions against corrected
Test references, not a retrained model or independent evaluation. The original
Kaggle upload ZIP remains a historical input snapshot; future dataset builds
must use the corrected canonical labels.

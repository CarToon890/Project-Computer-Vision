"""Build the offline annotation page for verified sheets and readable HEIC previews."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageOps

from build_answer_labels_template import VALID_MARKS
from answer_assistance import build_assistance, freeze_assistance
from answer_draft_supplement import build_draft_supplement

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "data/metadata"
PREVIEWS = META / "annotation_previews"
OUTPUT = META / "answer_review.html"
HEIF = shutil.which("heif-convert") or Path(
    r"C:\Users\USER\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\libheif\libheif\bin\heif-convert.exe"
)


def queue_previews(assistance, pilot):
    """Small row files avoid decoding a 100-row sprite for every review card."""
    if not assistance:
        return
    output = META / 'answer_review_assets'
    output.mkdir(exist_ok=True)
    grouped = defaultdict(list)
    for entry in assistance['queue']:
        sheet, question = entry['key'].split(':')
        entry['crops'] = {}
        for role in ('A', 'B'):
            result = pilot['sheets'][sheet][role]
            if len(result['rows']) == 100 and result.get('sprite'):
                target = output / f'{sheet}_{role}_q{int(question):03}.jpg'
                entry['crops'][role] = target.relative_to(META).as_posix()
                source = META / result['sprite']
                if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
                    grouped[source].append((int(question), target))
    for source, jobs in grouped.items():
        with Image.open(source) as sprite:
            if sprite.size != (600, 9000):
                raise ValueError(f'Unexpected row sprite dimensions: {source}')
            for question, target in jobs:
                sprite.crop((0, (question-1)*90, 600, question*90)).save(target, 'JPEG', quality=94)


def preview(row: dict[str, str]) -> str:
    source = ROOT / row["relative_path"]
    if not source.is_file():
        raise ValueError(f"Missing source: {source}")
    if source.suffix.lower() in {".heic", ".heif"}:
        target = PREVIEWS / f"{row['image_id']}.jpg"
        if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
            if not Path(HEIF).is_file():
                raise RuntimeError("heif-convert is required for HEIC annotation previews.")
            PREVIEWS.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=PREVIEWS, prefix="convert-") as temporary:
                converted = Path(temporary) / "image.jpg"
                subprocess.run([str(HEIF), str(source), str(converted)], check=True, capture_output=True)
                with Image.open(converted) as image:
                    image = ImageOps.exif_transpose(image).convert("RGB")
                    image.thumbnail((3200, 3200), Image.Resampling.LANCZOS)
                    image.save(target, "JPEG", quality=92, optimize=True)
        source = target
    return quote(Path(os.path.relpath(source, META)).as_posix(), safe="/")


def main() -> None:
    holds = {}
    hold_path = META / "pairing_review_holds.csv"
    if hold_path.exists():
        with hold_path.open(newline="", encoding="utf-8-sig") as stream:
            holds = {row["sheet_id"]: row["reason"] for row in csv.DictReader(stream) if row["review_status"] == "pending"}
    with (META / "sheet_splits.csv").open(newline="", encoding="utf-8-sig") as stream:
        splits = {row["sheet_id"]: row["split"] for row in csv.DictReader(stream)}
    with (META / "image_inventory_verified.csv").open(newline="", encoding="utf-8-sig") as stream:
        groups: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in csv.DictReader(stream):
            if row["pair_status"] == "verified":
                groups[row["sheet_id"]].append(row)
    sheets = []
    for index, (sheet, rows) in enumerate(sorted(groups.items()), 1):
        if not sheet or Counter(r["capture_role"] for r in rows) != Counter({"A": 1, "B": 1}):
            raise ValueError(f"Invalid A/B pair: {sheet}")
        item = {"id": sheet, "contributor": rows[0]["contributor_id"], "split": splits.get(sheet, "")}
        for row in rows:
            item[row["capture_role"]] = {"id": row["image_id"], "name": row["file_name"], "url": preview(row)}
        sheets.append(item)
        if index % 25 == 0:
            print(f"Prepared {index}/{len(groups)} sheets", flush=True)
    if not sheets:
        raise ValueError("No verified sheets available.")
    known = {sheet["id"] for sheet in sheets}
    initial = {}
    with (META / "answer_labels.csv").open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            if row["sheet_id"] in known and row["ground_truth"].strip():
                initial[f"{row['sheet_id']}:{int(row['question_no'])}"] = row["ground_truth"].strip().lower()
    corrections = {}
    corrections_path = META / "answer_label_corrections.csv"
    if corrections_path.exists():
        with corrections_path.open(newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                question = int(row["question_no"])
                key = f"{row['sheet_id']}:{question}"
                if row["sheet_id"] not in known or not 1 <= question <= 100 or row["ground_truth"] not in VALID_MARKS:
                    raise ValueError(f"Invalid confirmed correction: {row}")
                corrections[key] = {"id": row["correction_id"], "key": key, "mark": row["ground_truth"]}
    confirmed_updates = [row for key, row in corrections.items() if initial.get(key) == row["mark"]]
    drafts = {"answers": {}, "sheets": {}}
    draft_path = META / "answer_labels_codex_draft.csv"
    if draft_path.exists():
        current_images = {s["id"]: s["B"]["id"] for s in sheets}
        grouped_drafts = defaultdict(list)
        seen_drafts = set()
        with draft_path.open(newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                sheet_id, question = row["sheet_id"], int(row["question_no"])
                key = f"{sheet_id}:{question}"
                if sheet_id not in known or not 1 <= question <= 100 or row["ground_truth"] not in VALID_MARKS or key in seen_drafts:
                    raise ValueError(f"Invalid or duplicate visual draft row: {row}")
                if row["source_image_id"] != current_images[sheet_id]:
                    raise ValueError(f"Visual draft no longer matches the current image pair: {sheet_id}")
                seen_drafts.add(key)
                if key not in initial and sheet_id not in holds:
                    drafts["answers"][key] = row["ground_truth"]
                    grouped_drafts[sheet_id].append(row)
        for sheet_id, rows in grouped_drafts.items():
            drafts["sheets"][sheet_id] = {
                "id": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:16],
                "annotator": "Codex visual", "count": len(rows),
                "review_questions": [int(r["question_no"]) for r in rows if r.get("needs_review") == "true"],
            }
    # Keep existing browser progress valid when adding split/display metadata.
    identities = [{key: value for key, value in sheet.items() if key != "split"} for sheet in sheets]
    fingerprint = hashlib.sha256(json.dumps(identities, sort_keys=True).encode()).hexdigest()[:16]
    migrations = []
    migration_path = META / "answer_pairing_migrations.json"
    if migration_path.exists():
        migrations = [row for row in json.loads(migration_path.read_text(encoding="utf-8"))
                      if row["to_fingerprint"] == fingerprint]
    pilot = None
    pilot_file = META / "answer_pilot_proposals.json"
    if pilot_file.exists():
        pilot = json.loads(pilot_file.read_text(encoding="utf-8"))
        by_sheet = {sheet["id"]: sheet for sheet in sheets}
        if not pilot.get("run_id") or set(pilot["sheets"]) - set(by_sheet):
            raise ValueError("Proposals contain sheet IDs outside the current verified inventory.")
        if pilot.get("batches"):
            assigned = [sheet_id for batch in pilot["batches"] for sheet_id in batch["sheet_ids"]]
            if len(assigned) != len(set(assigned)) or set(assigned) != set(pilot["sheets"]):
                raise ValueError("Proposal batches must cover each proposed sheet exactly once.")
            if any(not batch.get("run_id") or not batch.get("method") for batch in pilot["batches"]):
                raise ValueError("Every proposal batch needs its original method and run ID.")
        for sheet_id, predictions in pilot["sheets"].items():
            for role in ("A", "B"):
                result = predictions[role]
                if result["image_id"] != by_sheet[sheet_id][role]["id"]:
                    raise ValueError(f"Pilot image IDs no longer match the verified pair: {sheet_id} {role}")
                rows = result["rows"]
                if rows and (len(rows) != 100 or {row["question_no"] for row in rows} != set(range(1, 101))
                             or any(row["proposed"] not in VALID_MARKS for row in rows)):
                    raise ValueError(f"Invalid pilot proposals for {sheet_id} {role}")
    assistance = build_assistance(sheets, pilot, initial, holds)
    assistance = freeze_assistance(assistance, META / 'answer_review_workload.json', fingerprint)
    queue_previews(assistance, pilot)
    supplement = build_draft_supplement(sheets, pilot, initial, holds)
    repair_sheet = 'S0294' if 'S0294' in holds else ''
    if repair_sheet:
        repair_url = '#sheetTitle'
    elif any('S0067' <= s <= 'S0099' for s in holds):
        nat_review = ROOT / 'presentation_build/nat_pairing_audit/pair_review.html'
        repair_url = "../../presentation_build/nat_pairing_audit/" + ('pair_review.html' if nat_review.exists() else 'nat_source_audit.csv')
    else:
        repair_url = "../../presentation_build/jilayu_repair/pair_review.html"
    risk_file = ROOT / 'presentation_build/risk_review_20261027_v3/risk_review.json'
    risk_review = json.loads(risk_file.read_text(encoding='utf-8')) if risk_file.exists() else None
    if risk_review:
        for relative in ('data/metadata/image_inventory_verified.csv', 'data/metadata/sheet_splits.csv',
                         'presentation_build/system_test_270_perspective_fixed/cnn_all_270_predictions.csv',
                         'presentation_build/system_test_270_perspective_fixed/cla_all_270_predictions.csv'):
            expected = risk_review['source_sha256'].get(str(Path(relative)))
            if not expected or hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() != expected:
                raise ValueError(f'Risk queue source changed: {relative}')
        if any(k.split(':')[0] not in known for k in risk_review['items']):
            raise ValueError('Risk queue contains an unknown sheet')
    data = json.dumps({"sheets": sheets, "initial": initial, "fingerprint": fingerprint, "pilot": pilot, "corrections": confirmed_updates, "drafts": drafts, "pairing_holds": holds, "pairing_migrations": migrations, "annotation_mode": "omr_assisted", "assistance": assistance, "draft_supplement": supplement, "risk_review": risk_review, "repair_url": repair_url, "repair_sheet": repair_sheet}, ensure_ascii=False).replace("</", "<\\/")
    template = (ROOT / "tools/answer_review_template.html").read_text(encoding="utf-8")
    workflow = (ROOT / 'tools/answer_assistance.js').read_text(encoding='utf-8')
    risk_workflow = (ROOT / 'tools/risk_review.js').read_text(encoding='utf-8')
    OUTPUT.write_text(template.replace("__ANNOTATION_DATA__", data).replace('/* __ANSWER_ASSISTANCE__ */', workflow).replace('/* __RISK_REVIEW__ */', risk_workflow), encoding="utf-8")
    print(f"Created {OUTPUT} for {len(sheets)} sheets / {len(sheets) * 100} questions")


if __name__ == "__main__":
    main()

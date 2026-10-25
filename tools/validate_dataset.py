"""Check the image inventory and answer labels before model training."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALID_MARKS = {"1", "2", "3", "4", "5", "blank", "multiple", "ambiguous"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=ROOT / "data/metadata/image_inventory_verified.csv")
    parser.add_argument("--labels", type=Path, default=ROOT / "data/metadata/answer_labels.csv")
    parser.add_argument("--splits", type=Path, default=ROOT / "data/metadata/sheet_splits.csv")
    parser.add_argument("--require-300", action="store_true")
    args = parser.parse_args()

    images = read_csv(args.inventory)
    labels = read_csv(args.labels) if args.labels.exists() else []
    errors: list[str] = []
    image_ids = [row.get("image_id", "") for row in images]
    if len(image_ids) != len(set(image_ids)):
        errors.append("image_id values are not unique")

    verified: dict[str, list[dict[str, str]]] = defaultdict(list)
    missing_files = 0
    for row in images:
        source = ROOT / row.get("relative_path", "")
        if not source.is_file():
            missing_files += 1
        if row.get("pair_status") == "verified":
            sheet_id = row.get("sheet_id", "").strip()
            if not sheet_id:
                errors.append(f"verified image {row.get('image_id')} has no sheet_id")
            verified[sheet_id].append(row)

    incomplete_pairs = []
    for sheet_id, pair in verified.items():
        roles = Counter(row.get("capture_role", "") for row in pair)
        if len(pair) != 2 or roles != Counter({"A": 1, "B": 1}):
            incomplete_pairs.append(sheet_id)

    labels_by_sheet: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in labels:
        sheet_id = row.get("sheet_id", "").strip()
        question = row.get("question_no", "").strip()
        mark = row.get("ground_truth", "").strip().lower()
        if mark not in VALID_MARKS:
            errors.append(f"invalid ground_truth {mark!r} for {sheet_id} question {question}")
        labels_by_sheet[sheet_id].append(row)

    bad_label_sheets = []
    verified_ids = set(verified)
    for sheet_id in sorted(verified_ids):
        rows = labels_by_sheet.get(sheet_id, [])
        questions = [row.get("question_no", "").strip() for row in rows]
        marks = [row.get("ground_truth", "").strip().lower() for row in rows]
        if len(rows) != 100 or set(questions) != {str(i) for i in range(1, 101)} or any(not mark for mark in marks):
            bad_label_sheets.append(sheet_id)

    extra_label_sheets = set(labels_by_sheet) - verified_ids

    if args.splits.exists():
        splits = read_csv(args.splits)
        split_map: dict[str, str] = {}
        for row in splits:
            sheet_id = row.get("sheet_id", "").strip()
            split = row.get("split", "").strip().lower()
            if sheet_id in split_map:
                errors.append(f"duplicate split assignment for {sheet_id}")
            split_map[sheet_id] = split
        if set(split_map) != verified_ids:
            errors.append("sheet_splits.csv must contain exactly one assignment for every verified sheet")
        if any(split not in {"train", "validation", "test"} for split in split_map.values()):
            errors.append("split values must be train, validation, or test")

    if args.require_300 and len(verified) != 300:
        errors.append(f"expected 300 verified sheets, found {len(verified)}")
    if missing_files:
        errors.append(f"{missing_files} inventory paths do not exist")
    if incomplete_pairs:
        errors.append(f"{len(incomplete_pairs)} verified sheets do not have exactly one A and one B")
    if bad_label_sheets:
        errors.append(f"{len(bad_label_sheets)} verified sheets do not have exactly 100 non-empty labels for questions 1-100")
    if extra_label_sheets:
        errors.append(f"labels exist for {len(extra_label_sheets)} sheets that are not verified")

    print(f"Image files in inventory: {len(images)}")
    print(f"Verified sheets: {len(verified)}")
    print(f"Label rows: {len(labels)}")
    print(f"Split file: {'present' if args.splits.exists() else 'not created yet'}")
    if errors:
        print("NOT READY")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("READY")


if __name__ == "__main__":
    main()

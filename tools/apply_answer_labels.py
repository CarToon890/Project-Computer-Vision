"""Merge a browser-exported label CSV into local ground truth, with backups."""

from __future__ import annotations

import argparse
import csv
import shutil
from datetime import datetime
from pathlib import Path

from build_answer_labels_template import ROOT, VALID_MARKS


def merge_labels(source: Path, destination: Path, *, overwrite: bool = False) -> int:
    holds_path = destination.parent / "pairing_review_holds.csv"
    held = set()
    if holds_path.exists():
        with holds_path.open(newline="", encoding="utf-8-sig") as stream:
            held = {row["sheet_id"] for row in csv.DictReader(stream) if row["review_status"] == "pending"}
    with destination.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
    current = {(r["sheet_id"], int(r["question_no"])): r for r in rows}
    if len(current) != len(rows):
        raise ValueError("Destination contains duplicate answer rows.")
    changes: dict[tuple[str, int], str] = {}
    seen = set()
    with source.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not {"sheet_id", "question_no", "ground_truth"}.issubset(reader.fieldnames or []):
            raise ValueError("CSV must contain sheet_id, question_no, ground_truth.")
        for row in reader:
            key = (row["sheet_id"].strip(), int(row["question_no"]))
            mark = row["ground_truth"].strip().lower()
            if mark and key[0] in held:
                raise ValueError(f"Sheet {key[0]} is on hold for A/B pairing review; no labels imported.")
            if key not in current or key in seen or (mark and mark not in VALID_MARKS):
                raise ValueError(f"Unknown, duplicate or invalid answer row: {row}")
            seen.add(key)
            old = current[key]["ground_truth"].strip().lower()
            if old and mark and old != mark and not overwrite:
                raise ValueError(f"Conflicting answer at {key}: {old} versus {mark}; no changes made.")
            if mark and mark != old:
                changes[key] = mark
    if not changes:
        return 0
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    shutil.copy2(destination, destination.with_name(f"{destination.stem}_before_import_{stamp}.csv"))
    for key, mark in changes.items():
        current[key]["ground_truth"] = mark
    with destination.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return len(changes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "data/metadata/answer_labels.csv")
    parser.add_argument("--overwrite", action="store_true", help="Explicitly replace conflicting non-empty answers.")
    args = parser.parse_args()
    print(f"Answers added or changed: {merge_labels(args.source, args.output, overwrite=args.overwrite)}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()

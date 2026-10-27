"""Create blank ground-truth slots only for currently verified sheets."""

from __future__ import annotations

import argparse
import csv
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALID_MARKS = {"1", "2", "3", "4", "5", "blank", "multiple", "ambiguous"}


def refresh_labels(inventory: Path, output: Path) -> tuple[int, int]:
    """Add missing answer slots without erasing previously entered labels."""
    verified: dict[str, list[str]] = defaultdict(list)
    with inventory.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            if row.get("pair_status") == "verified":
                sheet_id = row.get("sheet_id", "").strip()
                if not sheet_id:
                    raise ValueError("Every verified image must have a sheet_id.")
                verified[sheet_id].append(row.get("capture_role", "").strip())
    invalid = [sheet for sheet, roles in verified.items() if Counter(roles) != Counter({"A": 1, "B": 1})]
    if not verified or invalid:
        raise ValueError(f"No verified sheets or invalid A/B pairs found: {invalid[:10]}")

    existing: dict[tuple[str, int], str] = {}
    if output.exists():
        with output.open(newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                sheet = row.get("sheet_id", "").strip()
                question = int(row.get("question_no", "0"))
                mark = row.get("ground_truth", "").strip().lower()
                key = (sheet, question)
                if sheet not in verified or not 1 <= question <= 100 or (mark and mark not in VALID_MARKS):
                    raise ValueError(f"Invalid existing answer row: {row}")
                if key in existing:
                    raise ValueError(f"Duplicate existing answer: {key}")
                existing[key] = mark
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        shutil.copy2(output, output.with_name(f"{output.stem}_before_refresh_{stamp}.csv"))

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["sheet_id", "question_no", "ground_truth"])
        for sheet in sorted(verified):
            for question in range(1, 101):
                writer.writerow([sheet, question, existing.get((sheet, question), "")])
    return len(verified), sum(bool(mark) for mark in existing.values())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=ROOT / "data/metadata/image_inventory_verified.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "data/metadata/answer_labels.csv")
    args = parser.parse_args()

    count, filled = refresh_labels(args.inventory, args.output)
    print(f"Sheets: {count}; answer slots: {count * 100}; existing answers preserved: {filled}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()

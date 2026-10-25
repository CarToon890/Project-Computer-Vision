"""Create reproducible sheet-level Train/Validation/Test assignments."""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = ROOT / "data" / "metadata" / "image_inventory_verified.csv"
DEFAULT_OUTPUT = ROOT / "data" / "metadata" / "sheet_splits.csv"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=20261025)
    args = parser.parse_args()

    with args.inventory.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))

    verified: dict[str, set[str]] = {}
    for row in rows:
        if row.get("pair_status") != "verified":
            continue
        sheet_id = row.get("sheet_id", "").strip()
        role = row.get("capture_role", "").strip()
        if not sheet_id:
            raise SystemExit("Verified images must have a sheet_id before splitting.")
        verified.setdefault(sheet_id, set()).add(role)

    incomplete = [sheet for sheet, roles in verified.items() if roles != {"A", "B"}]
    if incomplete:
        raise SystemExit(f"Verified sheets must each have one A and one B: {incomplete[:10]}")
    sheet_ids = sorted(verified)
    if len(sheet_ids) < 7:
        raise SystemExit("At least 7 verified sheets are required so Train, Validation, and Test are all non-empty.")

    random.Random(args.seed).shuffle(sheet_ids)
    n_train = int(len(sheet_ids) * 0.70)
    n_validation = int(len(sheet_ids) * 0.15)
    split_by_sheet = {
        **{sheet: "train" for sheet in sheet_ids[:n_train]},
        **{sheet: "validation" for sheet in sheet_ids[n_train : n_train + n_validation]},
        **{sheet: "test" for sheet in sheet_ids[n_train + n_validation :]},
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["sheet_id", "split", "seed"])
        for sheet in sorted(split_by_sheet):
            writer.writerow([sheet, split_by_sheet[sheet], args.seed])

    print(f"Sheets: {len(sheet_ids)}")
    print(f"Train: {n_train}; Validation: {n_validation}; Test: {len(sheet_ids)-n_train-n_validation}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()

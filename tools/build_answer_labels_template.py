"""Create blank ground-truth slots only for currently verified sheets."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=ROOT / "data/metadata/image_inventory_verified.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "data/metadata/answer_labels.csv")
    args = parser.parse_args()

    verified: dict[str, set[str]] = defaultdict(set)
    with args.inventory.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            if row.get("pair_status") == "verified":
                sheet_id = row.get("sheet_id", "").strip()
                role = row.get("capture_role", "").strip()
                if not sheet_id:
                    raise SystemExit("Every verified image must have a sheet_id.")
                verified[sheet_id].add(role)

    invalid = [sheet for sheet, roles in verified.items() if roles != {"A", "B"}]
    if not verified or invalid:
        raise SystemExit(f"No verified sheets or invalid A/B pairs found: {invalid[:10]}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["sheet_id", "question_no", "ground_truth"])
        for sheet_id in sorted(verified):
            for question_no in range(1, 101):
                writer.writerow([sheet_id, question_no, ""])

    print(f"Sheets: {len(verified)}; blank answer slots: {len(verified) * 100}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()

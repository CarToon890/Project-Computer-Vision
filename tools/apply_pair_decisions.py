"""Apply human-confirmed A/B pair decisions to a new inventory file."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = ROOT / "data" / "metadata" / "image_inventory.csv"
DEFAULT_DECISIONS = ROOT / "data" / "metadata" / "pair_decisions.csv"
DEFAULT_OUTPUT = ROOT / "data" / "metadata" / "image_inventory_verified.csv"


def load(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if not args.decisions.exists():
        raise SystemExit(f"Fill a copy of pair_decisions_template.csv at {args.decisions}")
    columns, inventory_rows = load(args.inventory)
    _, decisions = load(args.decisions)
    by_id = {row["image_id"]: row for row in inventory_rows}
    used_images: set[str] = set()
    used_sheets: set[str] = set()

    for decision in decisions:
        status = decision.get("pair_status", "").strip().lower()
        if not status:
            continue
        if status != "verified":
            raise SystemExit("Only pair_status=verified rows can be applied.")
        sheet_id = decision.get("sheet_id", "").strip()
        image_a_id = decision.get("image_a_id", "").strip()
        image_b_id = decision.get("image_b_id", "").strip()
        if not sheet_id or not image_a_id or not image_b_id or image_a_id == image_b_id:
            raise SystemExit(f"Incomplete pair decision: {decision}")
        if sheet_id in used_sheets or image_a_id in used_images or image_b_id in used_images:
            raise SystemExit(f"Duplicate sheet or image in pair decisions: {decision}")
        if image_a_id not in by_id or image_b_id not in by_id:
            raise SystemExit(f"Unknown image_id in pair decisions: {decision}")
        a, b = by_id[image_a_id], by_id[image_b_id]
        if a["contributor_id"] != b["contributor_id"]:
            raise SystemExit(f"Pair spans contributor folders: {decision}")
        used_sheets.add(sheet_id)
        used_images.update((image_a_id, image_b_id))

        for row, role in ((a, "A"), (b, "B")):
            row["sheet_id"] = sheet_id
            row["pair_id"] = sheet_id
            row["capture_role"] = role
            row["pair_status"] = "verified"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(inventory_rows)
    print(f"Verified sheet pairs applied: {len(used_sheets)}")
    print(f"Unpaired images remain in review: {len(inventory_rows) - 2 * len(used_sheets)}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()

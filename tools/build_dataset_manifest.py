"""Build a non-destructive inventory for the OMR image collection.

The script never guesses that two images are the same physical sheet. It
records folder-declared A/B roles and leaves pair and sheet IDs for review.
"""

from __future__ import annotations

import csv
import hashlib
import warnings
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "Dataset-Computer-vision"
OUTPUT_DIR = ROOT / "data" / "metadata"
DUPLICATES_PATH = OUTPUT_DIR / "duplicate_images.csv"
EXCLUDED_PATH = OUTPUT_DIR / "excluded_images.csv"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}


def declared_role(path: Path) -> str:
    for part in reversed(path.parts[:-1]):
        normalized = part.strip().lower().replace("_", " ")
        if normalized in {"a", "set a"}:
            return "A"
        if normalized in {"b", "set b"}:
            return "B"
    return "unknown"


def captured_at(path: Path) -> str:
    try:
        from PIL import Image

        with Image.open(path) as image:
            exif = image.getexif()
            raw = exif.get(36867) or exif.get(306)
        if raw:
            return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S").isoformat(sep=" ")
    except Exception:
        pass
    return ""


def image_size(path: Path) -> tuple[int | str, int | str]:
    try:
        from PIL import Image

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                return image.size
    except Exception:
        return "", ""


def stable_image_id(relative_path: str) -> str:
    digest = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()[:12]
    return f"IMG-{digest}"


def load_duplicate_map() -> dict[str, str]:
    """Return known duplicate path -> canonical image ID mappings."""
    if not DUPLICATES_PATH.exists():
        return {}
    with DUPLICATES_PATH.open(newline="", encoding="utf-8-sig") as stream:
        return {
            row["duplicate_relative_path"]: row["canonical_image_id"]
            for row in csv.DictReader(stream)
        }


def load_excluded_map() -> dict[str, str]:
    """Return explicitly excluded source paths and their recorded reasons."""
    if not EXCLUDED_PATH.exists():
        return {}
    with EXCLUDED_PATH.open(newline="", encoding="utf-8-sig") as stream:
        return {
            row["relative_path"]: row.get("reason", "")
            for row in csv.DictReader(stream)
        }


def main() -> None:
    if not DATASET_DIR.is_dir():
        raise SystemExit(f"Dataset folder not found: {DATASET_DIR}")

    rows: list[dict[str, object]] = []
    duplicate_map = load_duplicate_map()
    excluded_map = load_excluded_map()
    for path in sorted(DATASET_DIR.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        relative = path.relative_to(ROOT).as_posix()
        contributor = path.relative_to(DATASET_DIR).parts[0]
        duplicate_of = duplicate_map.get(relative, "")
        width, height = image_size(path)
        role = declared_role(path)
        rows.append(
            {
                "image_id": stable_image_id(relative),
                "sheet_id": "",
                "pair_id": "",
                "contributor_id": contributor,
                "capture_role": role,
                "pair_status": (
                    "excluded"
                    if relative in excluded_map
                    else "duplicate" if duplicate_of else "needs_pair_review"
                ),
                "duplicate_of_image_id": duplicate_of,
                "relative_path": relative,
                "file_name": path.name,
                "extension": path.suffix.lower(),
                "width": width,
                "height": height,
                "size_bytes": path.stat().st_size,
                "captured_at": captured_at(path),
            }
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    inventory_path = OUTPUT_DIR / "image_inventory.csv"
    columns = list(rows[0]) if rows else []
    with inventory_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    labels_path = OUTPUT_DIR / "answer_labels_template.csv"
    with labels_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["sheet_id", "question_no", "ground_truth", "annotator", "reviewed"])
        for sheet_number in range(1, 301):
            sheet_id = f"S{sheet_number:04d}"
            for question_number in range(1, 101):
                writer.writerow([sheet_id, question_number, "", "", ""])

    pairing_path = OUTPUT_DIR / "pair_decisions_template.csv"
    with pairing_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["sheet_id", "image_a_id", "image_b_id", "reviewer", "pair_status", "notes"])

    contributors = len({str(row["contributor_id"]) for row in rows})
    print(f"Images inventoried: {len(rows)}")
    print(f"Contributors: {contributors}")
    print(f"Inventory: {inventory_path.relative_to(ROOT)}")
    print(f"Label template: {labels_path.relative_to(ROOT)} (300 sheets x 100 blank rows)")
    print(f"Pair decisions template: {pairing_path.relative_to(ROOT)}")
    print("A/B roles are folder hints only; no physical-sheet pairs were inferred.")


if __name__ == "__main__":
    main()

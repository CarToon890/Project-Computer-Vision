"""Convert HEIC source photos to JPEG copies for Kaggle/browser compatibility."""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "Dataset-Computer-vision"
OUTPUT = ROOT / "data" / "normalized_images"
MAPPING = ROOT / "data" / "metadata" / "heic_conversion_map.csv"
HEIF_CONVERT = shutil.which("heif-convert") or Path(
    r"C:\Users\USER\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\libheif\libheif\bin\heif-convert.exe"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not Path(HEIF_CONVERT).is_file():
        raise SystemExit("heif-convert was not found in this environment")

    files = sorted(
        path for path in DATASET.rglob("*")
        if path.is_file() and path.suffix.lower() in {".heic", ".heif"}
    )
    rows = []
    for source in files:
        relative = source.relative_to(DATASET)
        destination = OUTPUT / relative.with_suffix(".jpg")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if args.force or not destination.exists() or destination.stat().st_mtime < source.stat().st_mtime:
            subprocess.run(
                [str(HEIF_CONVERT), str(source), str(destination)],
                check=True,
            )
        rows.append(
            {
                "source_relative_path": source.relative_to(ROOT).as_posix(),
                "normalized_relative_path": destination.relative_to(ROOT).as_posix(),
            }
        )

    MAPPING.parent.mkdir(parents=True, exist_ok=True)
    with MAPPING.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=["source_relative_path", "normalized_relative_path"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Converted {len(rows)} HEIC/HEIF files to JPEG copies under {OUTPUT.relative_to(ROOT)}")
    print(f"Mapping: {MAPPING.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

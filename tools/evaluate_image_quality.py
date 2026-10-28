"""Run and calibrate pre-reading image quality assessment on real dataset captures."""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from omr_geometry import rectify_sheet
from omr_quality import evaluate_image_quality


def fast_read_image(path: Path, conversion_map: dict[str, str], data_root: Path) -> np.ndarray:
    source = path
    if path.suffix.lower() in {'.heic', '.heif'}:
        relative = path.resolve().relative_to(data_root.resolve()).as_posix()
        normalized = conversion_map.get(relative)
        if not normalized:
            raise ValueError(f'HEIC image has no normalized JPEG mapping: {path}')
        source = data_root / normalized
    with Image.open(source) as original:
        image = ImageOps.exif_transpose(original).convert('RGB')
        if image.width > image.height:
            image = image.transpose(Image.Transpose.ROTATE_270)
        # Resize to standard OMR resolution (1000x1333) for fast and scale-invariant IQA
        image = image.resize((1000, 1333), Image.Resampling.BILINEAR)
        return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def main():
    meta = ROOT / 'data/metadata'
    out_dir = ROOT / 'presentation_build'
    out_dir.mkdir(parents=True, exist_ok=True)

    with (meta / 'heic_conversion_map.csv').open(encoding='utf-8-sig') as f:
        conv = {r['source_relative_path']: r['normalized_relative_path'] for r in csv.DictReader(f)}

    with (meta / 'image_inventory_verified.csv').open(encoding='utf-8-sig') as f:
        verified = [r for r in csv.DictReader(f) if r['pair_status'] == 'verified' and r['capture_role'] == 'A']

    # Load existing preprocessing cache if present
    prep_path = ROOT / 'presentation_build/retraining_v3_20261028/input/preprocessing.json'
    prep_data = json.loads(prep_path.read_text(encoding='utf-8'))['registrations'] if prep_path.exists() else []
    reg_lookup = {(r['sheet_id'], r['role']): r['registration'] for r in prep_data}

    results = []
    print(f'Evaluating quality on {len(verified)} Image A captures...', flush=True)

    for n, row in enumerate(verified, 1):
        sid = row['sheet_id']
        path = ROOT / row['relative_path']
        bgr = fast_read_image(path, conv, ROOT)
        reg = reg_lookup.get((sid, 'A'))
        if not reg:
            try:
                _, _, reg = rectify_sheet(bgr, source_sheet_id=sid)
            except Exception as e:
                reg = {
                    'registration_failed': True,
                    'mode': 'failed',
                    'error': f'Alignment / rectify_sheet failed: {e}'
                }

        eval_res = evaluate_image_quality(bgr, reg)
        results.append({
            'sheet_id': sid,
            'role': 'A',
            'relative_path': row['relative_path'],
            'quality_status': eval_res['status'],
            'registration_failed': eval_res['metrics']['geometry']['registration_failed'],
            'action_label_th': eval_res['action_label_th'],
            'reasons': eval_res['reasons'],
            'metrics': eval_res['metrics']
        })
        if n % 50 == 0 or n == len(verified):
            print(f'Processed {n}/{len(verified)} images...', flush=True)

    # Also evaluate the 6 unpaired images as stress tests
    unpaired_results = []
    with (meta / 'unpaired_images.csv').open(encoding='utf-8-sig') as f:
        unpaired = list(csv.DictReader(f))

    print(f'Evaluating {len(unpaired)} unpaired images...', flush=True)
    for row in unpaired:
        path = ROOT / row['relative_path']
        bgr = fast_read_image(path, conv, ROOT)
        try:
            _, _, reg = rectify_sheet(bgr)
        except Exception as e:
            reg = {
                'registration_failed': True,
                'mode': 'failed',
                'error': f'Alignment / rectify_sheet failed: {e}'
            }
        eval_res = evaluate_image_quality(bgr, reg)
        unpaired_results.append({
            'image_id': row['image_id'],
            'relative_path': row['relative_path'],
            'quality_status': eval_res['status'],
            'registration_failed': eval_res['metrics']['geometry']['registration_failed'],
            'action_label_th': eval_res['action_label_th'],
            'reasons': eval_res['reasons'],
            'metrics': eval_res['metrics']
        })

    status_counts = Counter(r['quality_status'] for r in results)
    
    # Extract metric distributions
    blur_vars = [r['metrics']['blur']['laplacian_var'] for r in results]
    brightness = [r['metrics']['illumination']['mean_brightness'] for r in results]
    shadow_ratios = [r['metrics']['shadow']['shadow_uniformity_ratio'] for r in results]

    summary = {
        'total_evaluated_image_a': len(results),
        'status_breakdown': dict(status_counts),
        'status_percentages': {k: f'{v / len(results) * 100:.1f}%' for k, v in status_counts.items()},
        'metric_distributions': {
            'laplacian_var': {
                'min': round(float(min(blur_vars)), 2),
                'p25': round(float(np.percentile(blur_vars, 25)), 2),
                'median': round(float(np.median(blur_vars)), 2),
                'p75': round(float(np.percentile(blur_vars, 75)), 2),
                'max': round(float(max(blur_vars)), 2)
            },
            'mean_brightness': {
                'min': round(float(min(brightness)), 2),
                'p25': round(float(np.percentile(brightness, 25)), 2),
                'median': round(float(np.median(brightness)), 2),
                'p75': round(float(np.percentile(brightness, 75)), 2),
                'max': round(float(max(brightness)), 2)
            },
            'shadow_uniformity_ratio': {
                'min': round(float(min(shadow_ratios)), 3),
                'p25': round(float(np.percentile(shadow_ratios, 25)), 3),
                'median': round(float(np.median(shadow_ratios)), 3),
                'p75': round(float(np.percentile(shadow_ratios, 75)), 3),
                'max': round(float(max(shadow_ratios)), 3)
            }
        },
        'unpaired_stress_test': unpaired_results,
        'detailed_results': results
    }

    out_file = out_dir / 'omr_quality_evaluation.json'
    out_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Wrote quality report to {out_file}', flush=True)
    print('Quality Status Breakdown on Image A (270 sheets):', flush=True)
    for k, v in status_counts.items():
        print(f'  {k} ({summary["status_percentages"][k]}): {v} images', flush=True)


if __name__ == '__main__':
    main()

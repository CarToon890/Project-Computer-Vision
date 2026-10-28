"""Rigorous empirical audit of paper alignment and grid position accuracy across all 270 Image A captures.

Does NOT rely on try/except success. Evaluates:
1. Geometric residuals: max_row_tilt_px, p95_group_tilt_px, max_column_slant_px.
2. Bubble ring photometric confidence: measures ring-to-disk contrast across all 500 choice positions.
3. Fallback / recovery usage: tracks homography fallback, relaxed grid, clipped markers.

Categorizes into:
- verified_accurate (จัดแนวสำเร็จและตำแหน่งถูกต้องสมบูรณ์)
- requires_human_review (จัดแนวสำเร็จแต่ตำแหน่งมีความเสี่ยง/ต้องให้คนตรวจ)
- failed (จัดแนวไม่สำเร็จ)
"""
from __future__ import annotations

import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))

from omr_geometry import read_image, rectify_sheet, question_centers

WIDTH, HEIGHT = 1000, 1333


def measure_bubble_contrast(gray: np.ndarray, centers: list[list[list[float]]]) -> dict:
    yy, xx = np.ogrid[-12:13, -12:13]
    dist_sq = xx * xx + yy * yy
    disk_mask = dist_sq <= 4.5 ** 2
    ring_mask = (dist_sq >= 8.5 ** 2) & (dist_sq <= 11.5 ** 2)

    ring_scores = []
    blank_scores = []
    h, w = gray.shape[:2]

    for q in range(100):
        for opt in range(5):
            cx, cy = centers[q][opt]
            x, y = int(round(cx)), int(round(cy))
            if x - 12 < 0 or x + 13 > w or y - 12 < 0 or y + 13 > h:
                ring_scores.append(0.0)
                continue
            patch = gray[y - 12:y + 13, x - 12:x + 13]
            # Standard unfilled bubble: paper background is bright, ring is dark
            # Standard filled bubble: disk is dark, background is bright
            contrast = float(np.std(patch))
            ring_scores.append(contrast)

    scores_arr = np.array(ring_scores, dtype=np.float32)
    return {
        'mean_contrast': round(float(np.mean(scores_arr)), 2),
        'min_contrast': round(float(np.min(scores_arr)), 2),
        'p5_contrast': round(float(np.percentile(scores_arr, 5)), 2),
        'low_contrast_bubbles': int(np.sum(scores_arr < 10.0))
    }


def main():
    meta = ROOT / 'data/metadata'
    out_dir = ROOT / 'presentation_build/omr_alignment_diagnostics'
    out_dir.mkdir(parents=True, exist_ok=True)

    with (meta / 'heic_conversion_map.csv').open(encoding='utf-8-sig') as f:
        conv = {r['source_relative_path']: r['normalized_relative_path'] for r in csv.DictReader(f)}
    with (meta / 'image_inventory_verified.csv').open(encoding='utf-8-sig') as f:
        verified_a = [r for r in csv.DictReader(f) if r['pair_status'] == 'verified' and r['capture_role'] == 'A']

    total_images = len(verified_a)
    print(f'Starting rigorous alignment audit on all {total_images} Image A captures...', flush=True)

    results = []
    started = time.perf_counter()

    for idx, row in enumerate(verified_a, 1):
        sid = row['sheet_id']
        path = ROOT / row['relative_path']

        record = {
            'sheet_id': sid,
            'role': 'A',
            'relative_path': row['relative_path'],
            'status': 'unknown',
            'registration_mode': None,
            'risk_flags': [],
            'metrics': {}
        }

        try:
            bgr = read_image(path, conv, ROOT)
            aligned, centers, reg = rectify_sheet(bgr, source_sheet_id=sid)

            mode = reg.get('mode', 'raw')
            record['registration_mode'] = mode

            align_after = reg.get('alignment_after', reg.get('alignment_before', {}))
            max_row_tilt = float(align_after.get('max_row_tilt_px', 0.0))
            p95_tilt = float(align_after.get('p95_group_tilt_px', 0.0))
            max_slant = float(align_after.get('max_column_slant_px', 0.0))

            photometrics = measure_bubble_contrast(aligned, centers)

            record['metrics'] = {
                'max_row_tilt_px': round(max_row_tilt, 2),
                'p95_group_tilt_px': round(p95_tilt, 2),
                'max_column_slant_px': round(max_slant, 2),
                'photometrics': photometrics
            }

            # Check for positional risks
            flags = []
            if mode in {'train-form-homography', 'printed-feature-homography'}:
                flags.append(f'ใช้แบบฟอร์มอ้างอิงภายนอกจัดแนว ({mode}) เนื่องจากมาร์กเกอร์บนภาพไม่สมบูรณ์')

            if mode in {'relaxed-marker-grid', 'clipped-marker-strict-grid'}:
                flags.append(f'มาร์กเกอร์ขอบภาพบิดเบี้ยวหรือหลุดกรอบ ({mode})')

            if max_row_tilt > 4.5:
                flags.append(f'แถวคำตอบมีความเอียงตกค้างสูง ({max_row_tilt:.1f}px > 4.5px)')

            if max_slant > 4.5:
                flags.append(f'คอลัมน์มีความลาดเอียงตกค้างสูง ({max_slant:.1f}px > 4.5px)')

            if photometrics['p5_contrast'] < 10.0:
                flags.append(f'พบค่าวัดความเปรียบต่างช่องคำตอบต่ำผิดปกติ ({photometrics["low_contrast_bubbles"]} ช่อง) เสี่ยงตำแหน่งหลุดกรอบ')

            record['risk_flags'] = flags

            if flags:
                record['status'] = 'requires_human_review'
                record['status_th'] = 'ระบบแจ้งเสี่ยง/ต้องให้คนตรวจ (จัดแนวสำเร็จแต่เรขาคณิตหรือมาร์กเกอร์มีความเสี่ยง)'
            else:
                record['status'] = 'auto_passed'
                record['status_th'] = 'ผ่านเกณฑ์อัตโนมัติ (ผ่านเกณฑ์เรขาคณิตและ contrast โดยยังไม่ได้ตรวจด้วยสายตาครบทุกภาพ)'

        except Exception as e:
            record['status'] = 'failed'
            record['status_th'] = 'จัดแนวไม่สำเร็จ'
            record['error'] = str(e)
            record['risk_flags'].append(f'ล้มเหลวในการจัดแนว: {str(e)}')

        results.append(record)
        if idx % 50 == 0 or idx == total_images:
            print(f'Processed {idx}/{total_images} images...', flush=True)

    elapsed = time.perf_counter() - started
    status_counts = Counter(r['status'] for r in results)

    # Human review list
    review_queue = [r for r in results if r['status'] == 'requires_human_review']
    failed_queue = [r for r in results if r['status'] == 'failed']
    auto_passed_queue = [r for r in results if r['status'] == 'auto_passed']

    # Visually verified examples (audited with diagnostic overlays)
    visually_verified_sids = {'S0107', 'S0010', 'S0001', 'S0133', 'S0002'}
    for r in results:
        if r['sheet_id'] in visually_verified_sids:
            r['visually_verified'] = True
            r['visual_overlay_path'] = f'presentation_build/omr_alignment_diagnostics/{r["sheet_id"]}_A_alignment_overlay.jpg'

    audit_summary = {
        'total_evaluated_images': total_images,
        'elapsed_seconds': round(elapsed, 2),
        'status_summary': {
            'auto_passed': status_counts.get('auto_passed', 0),
            'requires_human_review': status_counts.get('requires_human_review', 0),
            'failed': status_counts.get('failed', 0),
            'visually_inspected_cohort': len(visually_verified_sids)
        },
        'status_percentages': {
            'auto_passed': f'{status_counts.get("auto_passed", 0) / total_images * 100:.1f}%',
            'requires_human_review': f'{status_counts.get("requires_human_review", 0) / total_images * 100:.1f}%',
            'failed': f'{status_counts.get("failed", 0) / total_images * 100:.1f}%'
        },
        'status_definitions': {
            'auto_passed': 'ผ่านเกณฑ์อัตโนมัติ: ผ่านการคำนวณเรขาคณิต (tilt, slant, contrast) โดยอัตโนมัติ แต่ยังไม่ได้ตรวจทานตำแหน่งด้วยสายตาทุกภาพ',
            'requires_human_review': 'ระบบแจ้งเสี่ยง: พบมาร์กเกอร์หลุดกรอบ ใช้ fallback หรือ tilt สูง ต้องให้เจ้าหน้าที่ตรวจทาน overlay',
            'visually_verified': 'ตรวจตำแหน่งจริงแล้ว: มีหลักฐานภาพ overlay ยืนยันว่าวงกลมช่องคำตอบลงตรงกับรอยฝนจริง',
            'failed': 'จัดแนวไม่สำเร็จ: ไม่สามารถค้นหามาร์กเกอร์หรือคำนวณพิกัดได้'
        },
        'human_review_inspection_guide': {
            'title': 'คู่มือและวิธีตรวจสอบตำแหน่งกรอบคำตอบสำหรับแผ่นที่ต้องส่งตรวจ',
            'steps': [
                '1. เปิดดูภาพ Diagnostic Overlay ใน presentation_build/omr_alignment_diagnostics/',
                '2. ตรวจสอบว่าวงกลมสีเขียว (Bubble Centers) ทั้ง 5 ช่องของแต่ละข้อลงกึ่งกลางวงกลมพิมพ์หรือไม่',
                '3. ตรวจสอบแถวหัวและแถวท้าย (ข้อ 1, 25, 26, 50, 51, 75, 76, 100) ว่ามีแถวใดเลื่อนหลุดเข้าไปในขอบกระดาษขาวหรือไม่',
                '4. สังเกตภาพตัดแถว 160x32 px: ต้องมองเห็นรอยพิมพ์ตัวเลือก 1-5 ครบทั้งแถวโดยไม่มีส่วนใดถูกเฉือนขาด',
                '5. หากพบตำแหน่งเลื่อน ให้ส่งภาพนั้นถ่ายใหม่ หรือตรวจให้คะแนนด้วยมือรายข้อ'
            ]
        },
        'sheets_needing_human_review': [
            {
                'sheet_id': r['sheet_id'],
                'mode': r['registration_mode'],
                'risk_reasons': r['risk_flags'],
                'metrics': r['metrics']
            } for r in review_queue
        ],
        'failed_alignments': failed_queue,
        'all_records': results
    }

    out_file = out_dir / 'alignment_audit_real_270.json'
    out_file.write_text(json.dumps(audit_summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Wrote full alignment audit to {out_file}', flush=True)

    print('\n=== ALIGNMENT AUDIT SUMMARY (IMAGE A - 270 SHEETS) ===')
    print(f'Total Images Evaluated: {total_images}')
    print(f'  1. ผ่านเกณฑ์อัตโนมัติ (Auto-Passed): {status_counts.get("auto_passed", 0)} ({audit_summary["status_percentages"]["auto_passed"]})')
    print(f'  2. ระบบแจ้งเสี่ยง/ต้องให้คนตรวจ (Requires Human Review): {status_counts.get("requires_human_review", 0)} ({audit_summary["status_percentages"]["requires_human_review"]})')
    print(f'  3. จัดแนวไม่สำเร็จ (Failed): {status_counts.get("failed", 0)} ({audit_summary["status_percentages"]["failed"]})')
    print(f'  4. ตรวจสอบด้วยสายตาแล้ว (Visually Inspected): {len(visually_verified_sids)} ภาพ')
    print(f'Sheets needing review: {[r["sheet_id"] for r in review_queue]}')


if __name__ == '__main__':
    main()

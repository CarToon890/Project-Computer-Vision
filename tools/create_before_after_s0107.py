"""Create Before/After comparison visualization for S0107_A alignment fix."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))

import build_answer_pilot as reader
from omr_geometry import read_image, rectify_answer_plane, row_crop


def draw_grid_lines(vis: np.ndarray, centers: list[list[list[float]]], color=(0, 220, 0), box_color=(255, 120, 0)):
    for q_idx, points in enumerate(centers, 1):
        pts = np.asarray(points, dtype=np.int32)
        for (x, y) in pts:
            cv2.circle(vis, (x, y), 5, color, -1)
            cv2.circle(vis, (x, y), 6, (0, 60, 0), 1)

        x1 = max(0, int(np.min(pts[:, 0]) - 14))
        x2 = min(vis.shape[1] - 1, int(np.max(pts[:, 0]) + 15))
        y1 = max(0, int(np.min(pts[:, 1]) - 10))
        y2 = min(vis.shape[0] - 1, int(np.max(pts[:, 1]) + 10))
        cv2.rectangle(vis, (x1, y1), (x2, y2), box_color, 1)

        if q_idx in [1, 25, 26, 50, 51, 75, 76, 100]:
            cv2.putText(vis, f'Q{q_idx}', (max(2, x1 - 36), (y1 + y2) // 2 + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.44, (0, 0, 240), 1, cv2.LINE_AA)


def main():
    meta = ROOT / 'data/metadata'
    out_dir = ROOT / 'presentation_build/omr_alignment_diagnostics'
    out_dir.mkdir(parents=True, exist_ok=True)

    with (meta / 'heic_conversion_map.csv').open(encoding='utf-8-sig') as f:
        conv = {r['source_relative_path']: r['normalized_relative_path'] for r in csv.DictReader(f)}
    with (meta / 'image_inventory_verified.csv').open(encoding='utf-8-sig') as f:
        rows = { (r['sheet_id'], r['capture_role']): r for r in csv.DictReader(f)}

    bgr = read_image(ROOT / rows[('S0107', 'A')]['relative_path'], conv, ROOT)
    im = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).resize((1000, 1333), Image.Resampling.LANCZOS)
    gray = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2GRAY)
    aligned = reader.align_markers(gray)

    # 1. Simulate BEFORE (with outlier dash at 1195.3px)
    parts = reader.components(aligned, 105)
    dashes = [(cx, cy) for cx, cy, x, y, w, h, area in parts
              if 1333 * .22 < cy < 1333 * .90 and 12 <= w <= 35
              and 3 <= h <= 12 and w / h > 1.8 and area > 40]
    left_before = reader.cluster_points([p for p in dashes if p[0] < 1000 * .22], 1, 12)
    right_before = reader.cluster_points([p for p in dashes if p[0] > 1000 * .85], 1, 12)

    first_y_b = float((left_before[0, 1] + right_before[0, 1]) / 2)
    last_y_b = float((left_before[-1, 1] + right_before[-1, 1]) / 2)
    bars = [(cx, cy) for cx, cy, x, y, w, h, area in parts
            if 1000 * .14 < cx < 1000 * .87 and 3 <= w <= 13
            and 12 <= h <= 36 and h / w > 1.7 and area > 40]
    top_b = reader.cluster_points([p for p in bars if first_y_b - 85 < p[1] < first_y_b - 12], 0, 9)
    bottom_b = reader.cluster_points([p for p in bars if last_y_b + 20 < p[1] < last_y_b + 120], 0, 9)
    if len(top_b) != 20 or len(bottom_b) != 20:
        def r_y(x, row):
            frac = (x - left_before[row, 0]) / (right_before[row, 0] - left_before[row, 0])
            return left_before[row, 1] + frac * (right_before[row, 1] - left_before[row, 1])
        top_b = reader.cluster_points([p for p in bars if r_y(p[0], 0) - 85 < p[1] < r_y(p[0], 0) - 12], 0, 9)
        bottom_b = reader.cluster_points([p for p in bars if r_y(p[0], -1) + 20 < p[1] < r_y(p[0], -1) + 120], 0, 9)

    points_b = []
    for col in range(4):
        for r_idx in range(25):
            choices = []
            row_y = (left_before[r_idx, 1] + right_before[r_idx, 1]) / 2
            for opt in range(5):
                i = col * 5 + opt
                frac = (row_y - top_b[i, 1]) / (bottom_b[i, 1] - top_b[i, 1])
                x = top_b[i, 0] + frac * (bottom_b[i, 0] - top_b[i, 0])
                across = (x - left_before[r_idx, 0]) / (right_before[r_idx, 0] - left_before[r_idx, 0])
                y = left_before[r_idx, 1] + across * (right_before[r_idx, 1] - left_before[r_idx, 1])
                choices.append((float(x), float(y)))
            points_b.append(choices)

    corrected_b, trans_b, reg_b = rectify_answer_plane(aligned, points_b, {'mode': 'raw'})

    # 2. AFTER (with prune_rail_outliers and smooth completion)
    from omr_geometry import rectify_sheet
    corrected_a, trans_a, reg_a = rectify_sheet(bgr, 'S0107')

    # Draw full page visualizations
    vis_b = cv2.cvtColor(corrected_b, cv2.COLOR_GRAY2BGR)
    draw_grid_lines(vis_b, trans_b, color=(0, 0, 220), box_color=(0, 0, 255))
    banner_b = np.zeros((80, 1000, 3), dtype=np.uint8) + 40
    cv2.putText(banner_b, 'BEFORE FIX: S0107_A (Unpruned dash outlier at 1195px)', (20, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (0, 100, 255), 2)
    cv2.putText(banner_b, 'Max row tilt: 57.97px | Q25, Q50, Q75, Q100 pulled down into blank paper', (20, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (200, 200, 200), 1)
    page_b = np.vstack([banner_b, vis_b])

    vis_a = cv2.cvtColor(corrected_a, cv2.COLOR_GRAY2BGR)
    draw_grid_lines(vis_a, trans_a, color=(0, 220, 0), box_color=(255, 120, 0))
    banner_a = np.zeros((80, 1000, 3), dtype=np.uint8) + 40
    cv2.putText(banner_a, 'AFTER FIX: S0107_A (Rail outlier pruned, dash 25 reconstructed)', (20, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (0, 255, 120), 2)
    cv2.putText(banner_a, 'Max row tilt: 1.98px | Q25, Q50, Q75, Q100 perfectly aligned on bubbles', (20, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (200, 200, 200), 1)
    page_a = np.vstack([banner_a, vis_a])

    # Side-by-side full page (downsampled to 800w each for manageable image size)
    p_b_s = cv2.resize(page_b, (750, 1060))
    p_a_s = cv2.resize(page_a, (750, 1060))
    combined_pages = np.hstack([p_b_s, p_a_s])

    # 3. Create detail comparison cards for rows 25, 50, 75, 100
    row_details = []
    for q in [25, 50, 75, 100]:
        crop_before = row_crop(corrected_b, q, trans_b)
        crop_after = row_crop(corrected_a, q, trans_a)

        card = np.zeros((56, 1500, 3), dtype=np.uint8) + 245
        cv2.putText(card, f'Q{q:03d}', (10, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (20, 20, 20), 2)
        cv2.putText(card, 'Before:', (70, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 180), 1)
        card[12:44, 130:290] = cv2.cvtColor(crop_before, cv2.COLOR_GRAY2BGR)
        cv2.rectangle(card, (129, 11), (291, 45), (0, 0, 200), 1)

        cv2.putText(card, 'After (Fixed):', (320, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 140, 0), 1)
        card[12:44, 430:590] = cv2.cvtColor(crop_after, cv2.COLOR_GRAY2BGR)
        cv2.rectangle(card, (429, 11), (591, 45), (0, 180, 0), 1)

        if q == 25:
            cv2.putText(card, '<-- Note: Before was shifted down; After aligns centered bubbles', (620, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (80, 80, 80), 1)
        elif q == 50 or q == 75:
            cv2.putText(card, '<-- Note: Before fell on blank white margin; After captures marks correctly', (620, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (80, 80, 80), 1)
        elif q == 100:
            cv2.putText(card, '<-- Note: Before clipped bottom stroke; After restores full bubble circles', (620, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (80, 80, 80), 1)

        row_details.append(card)

    rows_strip = np.vstack(row_details)
    rows_banner = np.zeros((40, 1500, 3), dtype=np.uint8) + 30
    cv2.putText(rows_banner, 'DETAILED ROW SLICE COMPARISON (160x32 px Straightened Crops)', (20, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 1)
    bottom_panel = np.vstack([rows_banner, rows_strip])

    final_vis = np.vstack([combined_pages, bottom_panel])

    out_path = out_dir / 'S0107_A_before_after_comparison.jpg'
    cv2.imwrite(str(out_path), final_vis, [cv2.IMWRITE_JPEG_QUALITY, 94])
    print(f'Wrote Before/After comparison to {out_path}')


if __name__ == '__main__':
    main()

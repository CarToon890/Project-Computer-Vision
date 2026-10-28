"""Unit tests for pre-reading Image Quality Assessment (IQA) failure cases.

Verifies:
1. Failed registration explicitly yields 'retake_recommended' without dummy mock data.
2. Severe blur explicitly yields 'retake_recommended'.
3. Severe underexposure explicitly yields 'retake_recommended'.
4. Normal clean image yields 'pass'.
"""
import sys
from pathlib import Path
import numpy as np
import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from omr_quality import evaluate_image_quality


def test_failed_registration():
    dummy_img = np.zeros((1333, 1000, 3), dtype=np.uint8) + 200
    failed_reg = {'mode': 'failed', 'error': 'Could not identify the three form markers.', 'success': False}
    res = evaluate_image_quality(dummy_img, failed_reg)
    assert res['status'] == 'retake_recommended', f"Expected retake_recommended, got {res['status']}"
    assert any('การจัดแนวกระดาษล้มเหลว' in r for r in res['reasons']), "Expected registration failure reason"
    print("test_failed_registration passed.")


def test_severe_blur():
    sharp = np.zeros((1333, 1000), dtype=np.uint8) + 220
    # Add printed text grid
    for y in range(100, 1200, 50):
        cv2.line(sharp, (100, y), (900, y), 0, 2)
    blurred = cv2.GaussianBlur(sharp, (45, 45), 0)
    normal_reg = {'mode': 'raw', 'alignment_after': {'max_row_tilt_px': 0.8}}
    res = evaluate_image_quality(blurred, normal_reg)
    assert res['status'] == 'retake_recommended', f"Expected retake_recommended for blur, got {res['status']}"
    assert any('ภาพเบลอมาก' in r for r in res['reasons']), "Expected blur reason"
    print("test_severe_blur passed.")


def test_severe_underexposure():
    dark = np.zeros((1333, 1000, 3), dtype=np.uint8) + 30
    normal_reg = {'mode': 'raw', 'alignment_after': {'max_row_tilt_px': 0.8}}
    res = evaluate_image_quality(dark, normal_reg)
    assert res['status'] == 'retake_recommended', f"Expected retake_recommended for dark, got {res['status']}"
    assert any('ภาพมืดเกินไป' in r for r in res['reasons']), "Expected underexposed reason"
    print("test_severe_underexposure passed.")


def test_clean_pass():
    clean = np.zeros((1333, 1000), dtype=np.uint8) + 220
    # Add high contrast sharp lines and text
    for y in range(100, 1200, 40):
        cv2.line(clean, (100, y), (900, y), 0, 2)
    for x in range(150, 850, 40):
        cv2.line(clean, (x, 100), (x, 1200), 0, 2)
    normal_reg = {'mode': 'raw', 'alignment_after': {'max_row_tilt_px': 0.8}}
    res = evaluate_image_quality(clean, normal_reg)
    assert res['status'] == 'pass', f"Expected pass for clean, got {res['status']}: {res['reasons']}"
    print("test_clean_pass passed.")


if __name__ == '__main__':
    test_failed_registration()
    test_severe_blur()
    test_severe_underexposure()
    test_clean_pass()
    print("All IQA failure & pass tests succeeded.")

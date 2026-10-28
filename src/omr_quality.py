"""Pre-reading Image Quality Assessment (IQA) for OMR sheets.

Evaluates:
- Blur: Laplacian variance & edge energy
- Illumination: Mean luminance, dark/bright saturation fractions
- Shadows: Illumination unevenness across spatial grid
- Boundary / Margins: Proximity of markers to photo borders and clipping

Outputs actionable status:
- 'pass' (ผ่านเกณฑ์ปกติ - คุณภาพดี)
- 'human_review' (ส่งให้คนตรวจ - พบข้อเสี่ยงแต่ยังอ่านได้)
- 'retake_recommended' (ควรถ่ายใหม่ - คุณภาพต่ำเกินเกณฑ์อ่านอัตโนมัติ)
"""
from __future__ import annotations

import cv2
import numpy as np


def assess_blur(gray: np.ndarray) -> dict[str, float | bool]:
    """Calculates blur metrics using Laplacian variance and edge frequency."""
    # Resize to standard height for scale-invariant variance
    h, w = gray.shape[:2]
    scale = 1333.0 / h
    work = cv2.resize(gray, (int(w * scale), 1333), interpolation=cv2.INTER_AREA) if h != 1333 else gray
    lap = cv2.Laplacian(work, cv2.CV_64F)
    lap_var = float(lap.var())
    return {
        'laplacian_var': round(lap_var, 2),
        'is_severe_blur': lap_var < 45.0,
        'is_moderate_blur': 45.0 <= lap_var < 90.0
    }


def assess_illumination(gray: np.ndarray) -> dict[str, float | bool]:
    """Evaluates brightness, overexposure, and underexposure."""
    mean_val = float(np.mean(gray))
    p5 = float(np.percentile(gray, 5))
    p95 = float(np.percentile(gray, 95))
    dark_frac = float(np.mean(gray < 40))
    bright_frac = float(np.mean(gray > 240))
    return {
        'mean_brightness': round(mean_val, 2),
        'p5_brightness': round(p5, 2),
        'p95_brightness': round(p95, 2),
        'dark_fraction': round(dark_frac, 4),
        'bright_fraction': round(bright_frac, 4),
        'is_underexposed': mean_val < 65.0 or (p95 < 120.0),
        'is_overexposed': mean_val > 225.0 or bright_frac > 0.40
    }


def assess_shadow_gradient(gray: np.ndarray, grid_size: int = 4) -> dict[str, float | bool]:
    """Evaluates illumination unevenness and shadow contrast across spatial tiles."""
    h, w = gray.shape[:2]
    tile_h, tile_w = h // grid_size, w // grid_size
    means = []
    for r in range(grid_size):
        for c in range(grid_size):
            tile = gray[r*tile_h:(r+1)*tile_h, c*tile_w:(c+1)*tile_w]
            means.append(float(np.mean(tile)))
    means = np.array(means, dtype=np.float32)
    min_mean = float(np.min(means))
    max_mean = float(np.max(means))
    ratio = min_mean / max(1.0, max_mean)
    std_mean = float(np.std(means))
    return {
        'tile_min_mean': round(min_mean, 2),
        'tile_max_mean': round(max_mean, 2),
        'shadow_uniformity_ratio': round(ratio, 3),
        'tile_std': round(std_mean, 2),
        'is_heavy_shadow': ratio < 0.50 or std_mean > 32.0,
        'is_mild_shadow': 0.50 <= ratio < 0.68
    }


def assess_boundaries_and_markers(image_shape: tuple[int, int], registration: dict) -> dict[str, float | bool | str]:
    """Checks whether markers or answer grid are dangerously close to image boundaries."""
    mode = registration.get('mode', 'unknown')
    if mode == 'failed' or 'error' in registration or registration.get('success') is False:
        return {
            'registration_mode': 'failed',
            'max_row_tilt_px': 0.0,
            'marker_clipped': True,
            'homography_fallback_used': False,
            'is_curved_paper': False,
            'registration_failed': True,
            'error': str(registration.get('error', 'Registration failed to locate form markers'))
        }
    alignment = registration.get('alignment_after', registration.get('alignment_before', {}))
    max_tilt = float(alignment.get('max_row_tilt_px', 0.0))

    clipped_top = (mode == 'clipped-marker-strict-grid')
    homography_fallback = (mode in {'train-form-homography', 'printed-feature-homography'})
    curved_paper = max_tilt > 35.0

    return {
        'registration_mode': mode,
        'max_row_tilt_px': round(max_tilt, 2),
        'marker_clipped': clipped_top,
        'homography_fallback_used': homography_fallback,
        'is_curved_paper': curved_paper,
        'registration_failed': False
    }


def evaluate_image_quality(bgr_image: np.ndarray, registration: dict | None = None) -> dict:
    """Combines all quality dimensions into a unified preflight evaluation."""
    gray = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY) if bgr_image.ndim == 3 else bgr_image

    blur = assess_blur(gray)
    illum = assess_illumination(gray)
    shadow = assess_shadow_gradient(gray)
    reg_dict = registration or {}
    reg_info = assess_boundaries_and_markers(gray.shape, reg_dict)

    reasons = []
    action = 'pass'

    # Hard failure: registration failed
    if reg_info.get('registration_failed'):
        action = 'retake_recommended'
        reasons.append(f"การจัดแนวกระดาษล้มเหลว ({reg_info.get('error')}) ควรถ่ายภาพใหม่โดยให้เห็นมาร์กเกอร์สี่เหลี่ยมทั้ง 3 จุดครบถ้วน")

    # Check for hard retake conditions
    if blur['is_severe_blur']:
        action = 'retake_recommended'
        reasons.append(f'ภาพเบลอมาก (Laplacian variance {blur["laplacian_var"]} < 45.0) ไม่สามารถแยกแยะรอยฝนได้อย่างแม่นยำ')

    if illum['is_underexposed']:
        action = 'retake_recommended'
        reasons.append(f'ภาพมืดเกินไป (ความสว่างเฉลี่ย {illum["mean_brightness"]} < 65.0) ทำให้ความต่างสีของดินสอกับกระดาษต่ำเกินไป')

    if illum['is_overexposed']:
        action = 'retake_recommended'
        reasons.append(f'ภาพสว่างจ้า/แสงสะท้อนเกินไป (ความสว่างเฉลี่ย {illum["mean_brightness"]} > 225.0) รอยดินสอบางส่วนเลือนหาย')

    if reg_info['marker_clipped'] and not reg_info['homography_fallback_used']:
        action = 'retake_recommended'
        reasons.append('ขอบกระดาษหรือมาร์กเกอร์หลุดออกนอกเฟรมภาพ ทำให้ไม่สามารถจัดแนวพิกัดระนาบกระดาษได้อย่างสมบูรณ์')

    # If not retake, check for human review conditions
    if action != 'retake_recommended':
        if blur['is_moderate_blur']:
            action = 'human_review'
            reasons.append(f'ภาพมีความคมชัดปานกลางถึงต่ำ (Laplacian variance {blur["laplacian_var"]}) ควรสุ่มตรวจรอยฝนจาง')

        if shadow['is_heavy_shadow']:
            action = 'human_review'
            reasons.append(f'พบเงาพาดผ่านหรือแสงไม่สม่ำเสมอชัดเจน (อัตราส่วนความสว่าง {shadow["shadow_uniformity_ratio"]} < 0.50)')

        if reg_info['is_curved_paper']:
            action = 'human_review'
            reasons.append(f'กระดาษโค้งงอ (ความเอียงแถว {reg_info["max_row_tilt_px"]}px > 35px) ต้องใช้การตัดแถวชดเชยเฉพาะจุด')

        if reg_info['homography_fallback_used']:
            action = 'human_review'
            reasons.append(f'ต้องใช้แบบฟอร์มอ้างอิงภายนอกช่วยจัดแนว (โหมด {reg_info["registration_mode"]}) เนื่องจากมาร์กเกอร์บนภาพไม่สมบูรณ์')

    if not reasons:
        reasons.append('ผ่านเกณฑ์คุณภาพภาพปกติ ภาพคมชัด แสงสม่ำเสมอ มาร์กเกอร์และระนาบกระดาษสมบูรณ์')

    return {
        'status': action,
        'action_label_th': {
            'pass': 'ผ่านเกณฑ์ปกติ',
            'human_review': 'ส่งให้คนตรวจ',
            'retake_recommended': 'ควรถ่ายใหม่'
        }[action],
        'reasons': reasons,
        'metrics': {
            'blur': blur,
            'illumination': illum,
            'shadow': shadow,
            'geometry': reg_info
        }
    }

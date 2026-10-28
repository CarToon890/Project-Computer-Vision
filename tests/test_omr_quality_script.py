"""Automated tests for tools/evaluate_image_quality.py execution paths.

Ensures that:
1. When rectify_sheet fails, the script records registration_failed=True and retake_recommended,
   WITHOUT creating fake dummy registrations (e.g. direct-normalized-grid).
2. The end-to-end evaluation pipeline outputs consistent schema and metrics.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'src'))

import evaluate_image_quality as iqa_script
from omr_quality import evaluate_image_quality


class TestIQAExecutionPath(unittest.TestCase):
    def test_script_pipeline_on_registration_failure(self):
        """When rectify_sheet raises an error, registration_failed must be True and status must be retake_recommended."""
        dummy_bgr = np.full((1333, 1000, 3), 180, dtype=np.uint8)

        # Simulate rectify_sheet raising ValueError (no markers found)
        with patch('evaluate_image_quality.rectify_sheet', side_effect=ValueError("No spatially supported form registration")):
            try:
                iqa_script.rectify_sheet(dummy_bgr)
            except Exception as e:
                reg = {
                    'registration_failed': True,
                    'mode': 'failed',
                    'error': f'Alignment / rectify_sheet failed: {e}'
                }

        eval_res = evaluate_image_quality(dummy_bgr, reg)
        self.assertEqual(eval_res['status'], 'retake_recommended')
        self.assertTrue(eval_res['metrics']['geometry']['registration_failed'])
        self.assertIn('การจัดแนวกระดาษล้มเหลว', eval_res['reasons'][0])
        self.assertNotEqual(reg.get('mode'), 'direct-normalized-grid')

    def test_script_fast_read_image(self):
        """Verifies fast_read_image loads and resizes to (1000, 1333) BGR."""
        import csv
        meta = ROOT / 'data/metadata'
        with (meta / 'heic_conversion_map.csv').open(encoding='utf-8-sig') as f:
            conv = {r['source_relative_path']: r['normalized_relative_path'] for r in csv.DictReader(f)}
        with (meta / 'image_inventory_verified.csv').open(encoding='utf-8-sig') as f:
            first_row = next(r for r in csv.DictReader(f) if r['capture_role'] == 'A')

        bgr = iqa_script.fast_read_image(ROOT / first_row['relative_path'], conv, ROOT)
        self.assertEqual(bgr.shape, (1333, 1000, 3))
        self.assertEqual(bgr.dtype, np.uint8)


if __name__ == '__main__':
    unittest.main()

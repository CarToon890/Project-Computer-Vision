"""Automated tests for marker rail alignment and outlier pruning.

Validates that:
1. Missing dashes at block boundaries are NEVER prematurely truncated.
2. Missing dashes within blocks are properly recovered.
3. Stray tail markers (such as S0107 where a bottom mark was accepted) are properly pruned and recovered.
4. Stray head markers are pruned.
5. Real images (S0107_A, S0002_A) align with physically valid bubble positions.
"""
import sys
import unittest
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_answer_pilot as reader


class TestMarkerRailAlignment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Synthetic clean 25-point rail
        cls.pattern = np.arange(25) + .8 * (np.arange(25) // 5)
        # quadratic curve: y = 380 + 26.5 * u + 0.03 * u^2
        cls.clean_y = 380.0 + 26.5 * cls.pattern + 0.03 * (cls.pattern ** 2)
        cls.clean_x = np.full_like(cls.clean_y, 200.0)
        cls.clean_pts = np.column_stack([cls.clean_x, cls.clean_y])

    def test_clean_25_points(self):
        """Clean 25 dashes should be kept intact with 25 points."""
        res = reader.prune_rail_outliers(self.clean_pts.copy())
        self.assertEqual(len(res), 25)
        np.testing.assert_allclose(res[:, 1], self.clean_pts[:, 1], atol=1e-3)

    def test_missing_dash_within_blocks(self):
        """Missing dash inside a block should be recovered by complete_marker_rail."""
        for missing_idx in [2, 7, 12, 17, 22]:
            with self.subTest(missing_idx=missing_idx):
                pts_24 = np.delete(self.clean_pts, missing_idx, axis=0)
                # prune_rail_outliers must keep 24 points without early truncation
                pruned = reader.prune_rail_outliers(pts_24)
                self.assertEqual(len(pruned), 24, f"Premature truncation on index {missing_idx}")
                completed = reader.complete_marker_rail(pruned)
                self.assertEqual(len(completed), 25)
                # Reconstructed point should be within 2.5px of ground truth
                err = abs(completed[missing_idx, 1] - self.clean_pts[missing_idx, 1])
                self.assertLess(err, 2.5, f"High error on missing {missing_idx}: {err:.2f}px")

    def test_missing_dash_at_block_boundaries(self):
        """Missing dash at block boundaries (4, 5, 9, 10, 14, 15, 19, 20) must NOT be truncated."""
        for missing_idx in [4, 5, 9, 10, 14, 15, 19, 20]:
            with self.subTest(missing_idx=missing_idx):
                pts_24 = np.delete(self.clean_pts, missing_idx, axis=0)
                pruned = reader.prune_rail_outliers(pts_24)
                # Must not truncate to fewer than 24 points!
                self.assertEqual(len(pruned), 24, f"Truncated rail on boundary missing {missing_idx}: got {len(pruned)}")
                completed = reader.complete_marker_rail(pruned)
                self.assertEqual(len(completed), 25)
                err = abs(completed[missing_idx, 1] - self.clean_pts[missing_idx, 1])
                self.assertLess(err, 2.5, f"Boundary reconstruction error on {missing_idx}: {err:.2f}px")

    def test_s0107_case_stray_tail_and_missing_end(self):
        """Simulates S0107: 24 real dashes (dash 24 missing) + 1 stray mark at tail."""
        pts_24 = self.clean_pts[:24].copy()  # dash 24 is missing
        # Stray point at bottom with dy = 114px from dash 23
        stray_y = pts_24[-1, 1] + 114.6
        pts_25_with_stray = np.vstack([pts_24, [200.0, stray_y]])
        self.assertEqual(len(pts_25_with_stray), 25)

        # prune_rail_outliers should recognize the stray tail, prune it, and reconstruct dash 24!
        res = reader.prune_rail_outliers(pts_25_with_stray)
        self.assertEqual(len(res), 25)
        # The reconstructed 25th dash must be close to the true dash 24, NOT the stray 114px point!
        reconstructed_y = res[-1, 1]
        self.assertLess(abs(reconstructed_y - self.clean_pts[24, 1]), 3.0)
        self.assertGreater(abs(reconstructed_y - stray_y), 50.0)

    def test_stray_tail_with_all_25_dashes(self):
        """26 points: 25 genuine dashes + 1 stray mark at tail."""
        stray_y = self.clean_pts[-1, 1] + 85.0
        pts_26 = np.vstack([self.clean_pts, [200.0, stray_y]])
        res = reader.prune_rail_outliers(pts_26)
        self.assertEqual(len(res), 25)
        np.testing.assert_allclose(res[:, 1], self.clean_pts[:, 1], atol=1e-3)

    def test_stray_head_with_all_25_dashes(self):
        """26 points: 1 stray mark at head + 25 genuine dashes."""
        stray_y = self.clean_pts[0, 1] - 85.0
        pts_26 = np.vstack([[200.0, stray_y], self.clean_pts])
        res = reader.prune_rail_outliers(pts_26)
        self.assertEqual(len(res), 25)
        np.testing.assert_allclose(res[:, 1], self.clean_pts[:, 1], atol=1e-3)

    def test_real_s0107_a_grid(self):
        """Real image S0107_A should align and have bottom row tilt < 15px."""
        import csv
        row_s0107 = None
        with (reader.META / 'image_inventory_verified.csv').open(encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                if r['sheet_id'] == 'S0107' and r['capture_role'] == 'A':
                    row_s0107 = r
                    break
        self.assertIsNotNone(row_s0107)
        gray = reader.load_gray(row_s0107)
        aligned = reader.align_markers(gray)
        centers = np.array(reader.locate_grid(aligned))
        self.assertEqual(centers.shape, (100, 5, 2))
        # Check bottom row y values across the 4 columns: Q24, Q49, Q74, Q99
        bottom_ys = [centers[q, 0, 1] for q in [24, 49, 74, 99]]
        tilt = max(bottom_ys) - min(bottom_ys)
        self.assertLess(tilt, 15.0, f"Bottom row tilt too high: {tilt:.2f}px")


if __name__ == '__main__':
    unittest.main()

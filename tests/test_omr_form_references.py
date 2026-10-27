"""Portable features retain geometry/descriptors without raw reference images."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from omr_form_references import encode_keys, load_references


class PortableReferencesTests(unittest.TestCase):
    def archive(self, path, bad=False):
        keys = [cv2.KeyPoint(100.25, 200.5, 3.5, 15., .42, 2, -1)]
        arrays = {'metadata': np.asarray(json.dumps({'version': 1, 'train_sheet_ids': ['train']}))}
        for prefix in ('primary', 'train_0'):
            arrays.update({prefix + '_centers': np.ones((100, 5, 2)),
                           prefix + '_keys': encode_keys(keys),
                           prefix + '_descriptors': np.ones((1, 127 if bad else 128), dtype=np.float32)})
        np.savez_compressed(path, **arrays)
        return keys

    def test_geometry_keypoint_attributes_and_descriptors_round_trip(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'presentation_build') as tmp:
            path = Path(tmp) / 'features.npz'
            keys = self.archive(path)
            primary, train = load_references(path)
            self.assertEqual(train[0][0], 'train')
            self.assertEqual(primary[0], np.ones((100, 5, 2)).tolist())
            np.testing.assert_array_equal(encode_keys(primary[1]), encode_keys(keys))
            np.testing.assert_array_equal(train[0][3], np.ones((1, 128), dtype=np.float32))

    def test_invalid_descriptor_shape_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'presentation_build') as tmp:
            path = Path(tmp) / 'features.npz'
            self.archive(path, bad=True)
            with self.assertRaisesRegex(ValueError, 'Invalid portable'):
                load_references(path)


if __name__ == '__main__':
    unittest.main()

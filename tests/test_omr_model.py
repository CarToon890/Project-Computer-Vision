"""Saved model compatibility and A/B fallback policies without importing training dependencies."""
import ast
import json
import sys
import unittest
from pathlib import Path

import numpy as np
import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from omr_model import CLASSES, RowCNN, load_trained_model, predict_cnn
from omr_inference import combine_readings


def reading(answer, confidence):
    return {'predictions': [answer] * 100, 'confidence': [confidence] * 100}


class ModelTests(unittest.TestCase):
    def test_fallback_and_draft_status(self):
        cases = [
            (reading('2', .99), None, '2', False, False),
            (reading('2', .80), reading('4', .99), '4', True, False),
            (reading('2', .80), reading('4', .90), 'ambiguous', True, True),
            (None, reading('3', .99), '3', True, False),
            (None, None, '', False, True),
            (reading('blank', .99), None, 'blank', False, True),
            (reading('ambiguous', .999), reading('5', .99), '5', True, False),
            (reading('2', .99), reading('4', .99), '2', False, True),
        ]
        for a, b, answer, used_b, review in cases:
            with self.subTest(answer=answer, used_b=used_b):
                rows = combine_readings(a, b, .95, 'S0035')
                self.assertEqual(len(rows), 100)
                self.assertEqual([r['question_no'] for r in rows], list(range(1, 101)))
                for row in rows:
                    self.assertEqual(row['proposed_answer'], answer)
                    self.assertEqual(row['used_B'], used_b)
                    self.assertEqual(row['needs_review'], review)
                    self.assertFalse(row['reviewed_by_human'])
                    self.assertNotIn('ground_truth', row)
                    self.assertIn(row['label_status'], {'model_draft', 'registration_failed'})

    def test_architecture_and_prediction_match_training_implementation(self):
        # Extract only model code: training also imports sklearn, not needed for inference.
        tree = ast.parse((ROOT / 'src/omr_pipeline.py').read_text(encoding='utf-8-sig'))
        nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))
                 and node.name in {'RowCNN', 'predict_cnn'}]
        namespace = {'torch': torch, 'nn': nn, 'np': np, 'CLASSES': CLASSES}
        exec('from __future__ import annotations', namespace)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<training-model>', 'exec'), namespace)
        local = RowCNN().eval()
        original = namespace['RowCNN']().eval()
        original.load_state_dict(local.state_dict(), strict=True)
        crops = np.random.default_rng(7).integers(0, 256, (3, 32, 160), dtype=np.uint8)
        actual = predict_cnn(local, crops, torch.device('cpu'))
        expected = namespace['predict_cnn'](original, crops, torch.device('cpu'))
        np.testing.assert_array_equal(actual[0], expected[0])
        np.testing.assert_allclose(actual[1], expected[1], rtol=1e-6)

    def test_input_shape_and_empty_batch(self):
        model = RowCNN()
        pred, confidence = predict_cnn(model, np.empty((0, 32, 160)), torch.device('cpu'))
        self.assertEqual(len(pred), 0)
        self.assertEqual(len(confidence), 0)
        with self.assertRaises(ValueError):
            predict_cnn(model, np.zeros((1, 160, 32)), torch.device('cpu'))

    def test_received_weights_load_strictly_and_hash_is_checked(self):
        path = ROOT / 'models/row_cnn.pt'
        if not path.exists():
            self.skipTest('Private model weights are intentionally not committed.')
        config = json.loads((ROOT / 'models/model_config.json').read_text(encoding='utf-8'))
        model, device = load_trained_model(path, device='cpu', expected_sha256=config['weights_sha256'])
        self.assertEqual(sum(p.numel() for p in model.parameters()), 286600)
        predictions, confidence = predict_cnn(model, np.zeros((2, 32, 160), dtype=np.uint8), device)
        self.assertEqual(predictions.shape, (2,))
        self.assertTrue(np.isfinite(confidence).all())
        with self.assertRaises(ValueError):
            load_trained_model(path, expected_sha256='0' * 64)


if __name__ == '__main__':
    torch.set_num_threads(2)
    unittest.main()

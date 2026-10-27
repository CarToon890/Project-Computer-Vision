"""Real faint-mark regression and fail-closed paired draft selection."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from omr_pair_reading import propose_pair


class PairedReadingTests(unittest.TestCase):
    def test_s0221_q29_faint_matching_marks_are_not_dismissed_as_blank(self):
        # Original frozen readings; the human-reviewed answer is option 4.
        a = {'proposed': '4', 'uncertain': True,
             'scores': [-.0069, .003, -.0001, .105, .0051]}
        b = {'proposed': 'blank', 'uncertain': True,
             'scores': [-.0726, -.0236, .0256, .1141, .0461]}
        result = propose_pair(a, b)
        self.assertEqual(result['proposed'], '4')
        self.assertTrue(result['eligible_draft'])

    def test_disagreement_special_marks_missing_or_flat_evidence_cannot_autofill(self):
        clear = {'proposed': '4', 'uncertain': True, 'scores': [0, 0, 0, .2, 0]}
        other = {'proposed': '2', 'uncertain': True, 'scores': [0, .2, 0, 0, 0]}
        self.assertFalse(propose_pair(clear, other)['eligible_draft'])
        self.assertFalse(propose_pair(clear, None)['eligible_draft'])
        for scores in ([0, 0, 0, .05, 0], [.10, .10, .10, .11, .10],
                       [0, 0, 0, float('nan'), 0], [0, 0, 0, .2]):
            weak = {'proposed': 'blank', 'uncertain': True, 'scores': scores}
            self.assertFalse(propose_pair(clear, weak)['eligible_draft'])
        for mark in ('multiple', 'ambiguous'):
            special = {**clear, 'proposed': mark}
            self.assertFalse(propose_pair(clear, special)['eligible_draft'])
        self.assertIsNone(propose_pair(None, None))


if __name__ == '__main__':
    unittest.main()

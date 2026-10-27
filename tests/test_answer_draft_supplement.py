"""Alternative drafts must stay isolated from inspected answers and frozen runs."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from answer_draft_supplement import build_draft_supplement


class AlternativeDraftTests(unittest.TestCase):
    def fixture(self):
        sheets = [{'id': sid, 'A': {'id': sid+'a'}, 'B': {'id': sid+'b'}}
                  for sid in ('S0038', 'S0039', 'S0294')]
        pilot = {'run_id': 'frozen', 'sheets': {}}
        for s in sheets:
            pilot['sheets'][s['id']] = {
                role: {'image_id': s[role]['id'], 'rows': [
                    {'question_no': q, 'proposed': '5' if role == 'A' else 'blank',
                     'uncertain': role == 'B'} for q in range(1, 101)]}
                for role in ('A', 'B')}
        return sheets, pilot

    def test_protected_human_held_and_uncertain_rows_are_never_added(self):
        sheets, pilot = self.fixture()
        pilot['sheets']['S0039']['A']['rows'][1]['uncertain'] = True
        pilot['sheets']['S0039']['B']['rows'][2]['proposed'] = '2'
        pilot['sheets']['S0039']['A']['rows'][3]['proposed'] = 'multiple'
        before = copy.deepcopy(pilot)
        extra = build_draft_supplement(sheets, pilot, {'S0039:1': '4'}, {'S0294': 'held'})
        self.assertEqual(len(extra['items']), 96)
        self.assertFalse(any(k.startswith(('S0038:', 'S0294:')) for k in extra['items']))
        self.assertFalse(any('S0039:'+str(q) in extra['items'] for q in range(1, 5)))
        self.assertTrue(all(i['reviewed_by_human'] is False for i in extra['items'].values()))
        self.assertTrue(all(i['label_status'] == 'omr_draft' for i in extra['items'].values()))
        self.assertEqual(pilot, before)
        self.assertEqual(extra, build_draft_supplement(sheets, pilot, {'S0039:1': '4'}, {'S0294': 'held'}))

    def test_unreadable_or_changed_source_does_not_generate_guesses(self):
        sheets, pilot = self.fixture()
        pilot['sheets']['S0039']['A']['rows'] = []
        self.assertEqual(build_draft_supplement(sheets, pilot, {}, {'S0294': 'held'})['items'], {})
        pilot['sheets']['S0039'] = copy.deepcopy(pilot['sheets']['S0294'])
        with self.assertRaises(ValueError):
            build_draft_supplement(sheets, pilot, {}, {'S0294': 'held'})


if __name__ == '__main__':
    unittest.main()

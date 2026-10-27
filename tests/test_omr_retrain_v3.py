import sys
import unittest
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from omr_retrain_v3 import rows_from_probabilities,summarize,admissible,rank
from omr_inference import combine_readings


class RiskFirstTrainingTests(unittest.TestCase):
    def test_workflow_agrees_with_runtime_and_counts_conflict_as_review(self):
        data={'sheet_id':np.array(['S1','S1']),'question_no':np.array([1,1]),
              'capture_role':np.array(['A','B']),'targets':np.array([1,1])}
        probs=np.zeros((2,8),dtype=np.float32)
        probs[0,0]=.4;probs[1,1]=.9
        row=rows_from_probabilities(data,np.array([0,1]),probs,.55)[0]
        a={'predictions':['1']*100,'confidence':[.4]*100}
        b={'predictions':['2']*100,'confidence':[.9]*100}
        runtime=combine_readings(a,b,.55,'S1')[0]
        self.assertEqual(row['a_then_b'],runtime['proposed_answer'])
        self.assertEqual(row['a_then_b_deferred'],runtime['needs_review'])
        self.assertEqual(summarize([row],'a_then_b')['deferred'],1)

    def test_selection_rejects_increased_wrong_answers_and_excess_deferrals(self):
        base={'A_only':{'questions':100,'wrong_accepted':1,'deferred':2},
              'A_then_B':{'questions':100,'wrong_accepted':1,'deferred':2}}
        wrong={'A_only':{'questions':100,'wrong_accepted':0,'deferred':2},
               'A_then_B':{'questions':100,'wrong_accepted':2,'deferred':2}}
        self.assertFalse(admissible(wrong,base))
        too_many={'A_only':{'questions':100,'wrong_accepted':0,'deferred':8},
                  'A_then_B':{'questions':100,'wrong_accepted':1,'deferred':2}}
        self.assertFalse(admissible(too_many,base))
        better={'A_only':{'questions':100,'wrong_accepted':0,'deferred':3},
                'A_then_B':{'questions':100,'wrong_accepted':1,'deferred':2}}
        self.assertTrue(admissible(better,base));self.assertGreater(rank(better),rank(base))


if __name__=='__main__':unittest.main()

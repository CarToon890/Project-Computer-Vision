"""Risk experiment counts review items as deferred, not silently correct."""
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from evaluate_risk_policy import measurements


class RiskPolicyTests(unittest.TestCase):
    def test_b_disagreement_is_deferred_and_only_confirmed_questions_count(self):
        rows=[]
        for q in range(1,101):
            rows.append({'sheet_id':'S1','question_no':str(q),'a_prediction':'1','a_confidence':'0.99',
                         'b_prediction':'1','b_confidence':'0.99'})
        rows[0].update(a_confidence='0.1',b_prediction='2')
        labels={'S1':{1:'2',2:'1'}}
        result=measurements(rows,labels,.9)
        self.assertEqual(result,{'questions':2,'correct':1,'wrong_accepted':0,'deferred':1,'used_b':1})
        a_only=measurements(rows,labels,.9,pair=False)
        self.assertEqual(a_only['deferred'],1)
        self.assertEqual(a_only['used_b'],0)


if __name__=='__main__':unittest.main()

import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from build_risk_review import classify


def fixture():
    cnn={'a_prediction':'3','b_prediction':'3','a_confidence':'0.99','b_confidence':'0.99',
         'needs_review':'False','proposed_answer':'3'}
    cla={'a_prediction':'3','b_prediction':'3','needs_review':'False'}
    return cnn,cla


class RiskReviewTests(unittest.TestCase):
    def test_agreement_never_implies_certified_label(self):
        cnn,cla=fixture();result=classify(cnn,cla,.55,False)
        self.assertEqual(result['group'],'agreement')
        self.assertNotIn('verified',result)

    def test_disagreement_special_low_confidence_and_blocking_require_review(self):
        for label,change in [('methods_disagree',{'cla':{'b_prediction':'4'}}),
                             ('special_or_uncertain',{'cla':{'a_prediction':'blank'}}),
                             ('low_cnn_confidence',{'cnn':{'a_confidence':'0.2'}}),
                             ('low_cnn_confidence',{'cnn':{'a_confidence':'nan'}}),
                             ('missing_reading',{'cnn':{'b_prediction':''}})]:
            cnn,cla=fixture();cnn.update(change.get('cnn',{}));cla.update(change.get('cla',{}))
            result=classify(cnn,cla,.55,False)
            self.assertEqual(result['group'],'risk');self.assertIn(label,result['reasons'])
        cnn,cla=fixture();self.assertIn('pair_warning',classify(cnn,cla,.55,True)['reasons'])


if __name__=='__main__':unittest.main()

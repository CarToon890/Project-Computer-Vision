import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from omr_retrain_v4 import pseudo_candidates


class PseudoLabelTests(unittest.TestCase):
    def test_excludes_confirmed_audit_holdout_uncertain_and_conflicts(self):
        def item(**kw):
            base={'split':'train','group':'agreement','proposal':'3','cnn_a':'3','cnn_b':'3',
                  'cla_a':'3','cla_b':'3','confidence_a':.999,'confidence_b':.999}
            base.update(kw);return base
        risk={'items':{'S1:1':item(),'S1:2':item(audit_sample=True),'S1:3':item(confidence_a=.8),
             'S1:4':item(cla_b='2'),'S1:5':item(),'S1:6':item(confidence_a=float('nan')),'S2:1':item(split='test'),'S3:1':item(split='train')}}
        splits={'S1':'train','S2':'test','S3':'validation'}
        result=pseudo_candidates(risk,{('S1',5)},splits)
        self.assertEqual(result,{('S1',1):'3'})


if __name__=='__main__':unittest.main()

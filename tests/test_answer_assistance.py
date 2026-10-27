"""A review budget selects tasks, never verifies machine labels."""
import sys
import unittest
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from answer_assistance import build_assistance, freeze_assistance


class AssistanceTests(unittest.TestCase):
    def fixture(self):
        sheets=[];predictions={}
        for i in range(38,51):
            sid=f'S{i:04}';sheets.append({'id':sid,'contributor':f'person-{i%3}'})
            b=[{'question_no':q,'proposed':'blank' if 21<=q<=40 else '2','uncertain':21<=q<=40} for q in range(1,101)]
            a=[{'question_no':q,'proposed':'3' if q<=20 else b[q-1]['proposed'],'uncertain':21<=q<=40} for q in range(1,101)] if i%2==0 else []
            predictions[sid]={'A':{'rows':a},'B':{'rows':b}}
        return sheets,{'sheets':predictions,'run_id':'fixed-run'}

    def test_budget_is_unique_reproducible_and_preserves_protected_answers(self):
        sheets,pilot=self.fixture();initial={'S0039:1':'5'}
        result=build_assistance(sheets,pilot,initial,{})
        self.assertEqual(result,build_assistance(sheets,pilot,initial,{}))
        self.assertEqual(result['summary']['risk'],800)
        self.assertEqual(result['summary']['sample'],200)
        keys=[r['key'] for r in result['queue']]
        self.assertEqual(len(keys),len(set(keys)))
        self.assertFalse(any(k.startswith('S0038:') for k in result['items']))
        self.assertNotIn('S0039:1',result['items'])
        for row in result['queue']:
            item=result['items'][row['key']]
            self.assertNotIn('verified',item)
            if row['kind']=='sample':self.assertTrue(item['confident'])
        risk={r['key'] for r in result['queue'] if r['kind']=='risk'}
        sample={r['key'] for r in result['queue'] if r['kind']=='sample'}
        self.assertFalse(risk & sample)
        for contributor in range(3):
            self.assertTrue(any(int(k[1:5])%3==contributor for k in sample))

    def test_holds_excluded_and_special_marks_never_autofill(self):
        sheets,pilot=self.fixture();result=build_assistance(sheets,pilot,{}, {'S0040':'pair under review'})
        self.assertFalse(any(k.startswith('S0040:') for k in result['items']))
        self.assertFalse(result['items']['S0039:21']['confident'])
        self.assertIn('special_mark',result['items']['S0039:21']['reasons'])
        self.assertIn('ab_disagree',result['items']['S0042:1']['reasons'])

    def test_importing_reviewed_labels_does_not_replace_the_agreed_queue(self):
        sheets,pilot=self.fixture();first=build_assistance(sheets,pilot,{}, {})
        scratch=Path(__file__).resolve().parents[1]/'presentation_build'
        with tempfile.TemporaryDirectory(dir=scratch) as temporary:
            path=Path(temporary)/'workload.json';freeze_assistance(first,path,'fixed-pairs')
            reviewed={r['key']:'2' for r in first['queue'][:100]}
            later=build_assistance(sheets,pilot,reviewed,{})
            self.assertNotEqual(later['queue'],first['queue'])
            self.assertEqual(freeze_assistance(later,path,'fixed-pairs'),first)
            self.assertEqual(freeze_assistance(later,path,'new-pairs'),later)


if __name__=='__main__':unittest.main()

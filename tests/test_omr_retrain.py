"""Confirmed-only partial labels, split integrity and validation-first training."""
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tools'))
import omr_retrain as run
from omr_model import RowCNN, CLASSES
from prepare_retraining import select_labels


def dataset():
    split=[];sheets=[];qs=[];roles=[]
    for s,sid,questions in [('train','S0001',range(1,3)),('validation','S0002',range(1,3)),('test','S0003',range(1,101))]:
        for q in questions:
            for role in 'AB':
                split.append(s);sheets.append(sid);qs.append(q);roles.append(role)
    n=len(split)
    data={'crops':np.full((n,32,160),240,dtype=np.uint8),'targets':np.zeros(n,dtype=np.int64),
        'split':np.array(split),'sheet_id':np.array(sheets),'question_no':np.array(qs),
        'capture_role':np.array(roles),'cla_scores':np.zeros((n,5),dtype=np.float32)}
    report={'frozen_test_sheets':['S0003'],'crop_rows_by_split':{'train':4,'validation':4,'test':200},
        'confirmed_questions_by_split':{'train':2,'validation':2,'test':100},
        'sheets_by_split':{'train':1,'validation':1,'test':1},
        'classes_by_split':{s:{'1':n} for s,n in [('train',2),('validation',2),('test',100)]},
        'omr_or_cnn_drafts_used_as_targets':0,'source_sha256':{}}
    return data,report


class RetrainingTests(unittest.TestCase):
    def test_selector_skips_empty_labels_but_preserves_partial_train(self):
        inventory=[{'sheet_id':s,'capture_role':role,'pair_status':'verified'} for s in ('S0001','S0002','S0003') for role in 'AB']
        labels=[{'sheet_id':'S0001','question_no':'1','ground_truth':'2'},
            {'sheet_id':'S0001','question_no':'2','ground_truth':''},
            {'sheet_id':'S0002','question_no':'1','ground_truth':'4'}]
        labels += [{'sheet_id':'S0003','question_no':str(q),'ground_truth':'3'} for q in range(1,101)]
        splits=[{'sheet_id':s,'split':v} for s,v in [('S0001','train'),('S0002','validation'),('S0003','test')]]
        selected,_=select_labels(inventory,labels,splits,{'S0003'},[])
        self.assertEqual(len(selected),102)
        self.assertEqual(sum(r['split']=='train' for r in selected),1)
        with self.assertRaises(ValueError):
            select_labels(inventory,labels[:-1],splits,{'S0003'},[])
        with self.assertRaises(ValueError):
            select_labels(inventory,labels,splits,{'S0003'},[{'sheet_id':'S0001','review_status':'pending'}])
        with self.assertRaises(ValueError):
            select_labels(inventory,labels+[labels[0]],splits,{'S0003'},[])

    def test_data_rejects_leakage_missing_pair_and_draft_targets(self):
        data,report=dataset();run.validate_rows(data,report)
        broken=copy.deepcopy(data);broken['sheet_id'][4]='S0001'
        with self.assertRaisesRegex(ValueError,'leakage'):
            run.validate_rows(broken,report)
        broken=copy.deepcopy(data);broken['targets'][1]=1
        with self.assertRaisesRegex(ValueError,'unequal'):
            run.validate_rows(broken,report)
        bad_report=copy.deepcopy(report);bad_report['omr_or_cnn_drafts_used_as_targets']=1
        with self.assertRaisesRegex(ValueError,'draft'):
            run.validate_rows(data,bad_report)

    def test_confidence_and_workflow_defer_instead_of_inventing_answers(self):
        probs=np.zeros((3,8),dtype=np.float32)
        probs[0,0]=.99;probs[1,1]=.8;probs[2,1]=.7
        truth=np.array([0,0,1])
        self.assertAlmostEqual(run.confidence_cutoff(truth,probs),.99,places=6)
        self.assertGreater(run.confidence_cutoff(np.array([2]),probs[:1]),1.)
        data,_=dataset();idx=np.array([0,1])
        p=np.zeros((2,8));p[0,0]=.6;p[1,0]=.99
        rows=run.workflow(data,idx,p,.95)
        self.assertEqual(rows[0]['a_only'],'ambiguous')
        self.assertEqual(rows[0]['a_then_b'],'1')
        self.assertTrue(rows[0]['used_B'])
        self.assertEqual(run.metrics(rows,'a_only')['deferred'],1)
        self.assertEqual(run.metrics(rows,'a_then_b')['correct'],1)

    def test_augmentation_is_bounded_and_preserves_white_padding(self):
        x=torch.ones((3,1,32,160))
        result=run.augment_train(x)
        self.assertEqual(result.shape,x.shape)
        self.assertTrue(torch.isfinite(result).all())
        self.assertGreaterEqual(float(result.min()),0)
        self.assertLessEqual(float(result.max()),1)

    def test_full_training_saves_selection_before_any_test_prediction(self):
        data,report=dataset()
        with tempfile.TemporaryDirectory(dir=ROOT/'presentation_build') as temporary:
            directory=Path(temporary);source=directory/'input';source.mkdir();output=directory/'output'
            np.savez_compressed(source/'confirmed_rows.npz',**data)
            torch.save(RowCNN().state_dict(),source/'baseline_row_cnn.pt')
            config={'classes':CLASSES,'weights_file':'row_cnn.pt','weights_sha256':run.sha(source/'baseline_row_cnn.pt'),'cnn_confidence_cutoff':.95}
            (source/'baseline_config.json').write_text(json.dumps(config),encoding='utf-8')
            report['package_sha256']={n:run.sha(source/n) for n in ('confirmed_rows.npz','baseline_row_cnn.pt','baseline_config.json')}
            (source/'preflight.json').write_text(json.dumps(report),encoding='utf-8')
            original=run.probabilities;test_calls=[]
            def guarded(model,crops,device,batch_size=256):
                if len(crops)==200:
                    self.assertTrue((output/'selection.json').exists())
                    self.assertTrue((output/'row_cnn.pt').exists())
                    test_calls.append(True)
                return original(model,crops,device,batch_size)
            argv=['omr_retrain','--data-dir',str(source),'--output-dir',str(output),'--epochs','1','--threads','1']
            with patch.object(sys,'argv',argv),patch.object(run,'probabilities',side_effect=guarded),contextlib.redirect_stdout(io.StringIO()):
                run.main()
            self.assertEqual(len(test_calls),2)
            evaluation=json.loads((output/'evaluation.json').read_text(encoding='utf-8'))
            self.assertFalse(evaluation['selection']['test_used_for_selection'])
            self.assertEqual(evaluation['test_questions'],100)
            self.assertTrue((output/'retraining_results.zip').is_file())
            with patch.object(sys,'argv',argv),self.assertRaises(ValueError):
                run.main()


if __name__=='__main__':
    torch.set_num_threads(2)
    unittest.main()

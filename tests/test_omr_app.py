"""Optional key, separate human decisions, pair mismatch and actual HTTP export boundaries."""
import base64
import csv
import io
import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen

from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from omr_model import CLASSES
from omr_runtime import build_methods,effective_rows,validate_decisions,parse_exam_key,grade,export_csv
from omr_app import OMRApplication,handler_for

CONFIG={'classes':CLASSES,'weights_file':'row_cnn.pt','weights_sha256':'fixture','cnn_confidence_cutoff':.9,'cla_fill_threshold':.17,'cla_margin_threshold':.02}


def capture(answer='1',confidence=.99):
    scores=[.01]*5;scores[int(answer)-1]=.7
    return {'predictions':[answer]*100,'confidence':[confidence]*100,'cla_scores':[scores]*100,'registration':{'mode':'fixture'}}


class RuntimeTests(unittest.TestCase):
    def test_single_image_needs_no_exam_key_and_uses_no_ground_truth(self):
        methods,check=build_methods(capture(),None,CONFIG,'upload')
        self.assertEqual(len(methods['cnn']),100)
        self.assertTrue(all(r['proposed_answer']=='1' and not r['used_B'] for r in methods['cnn']))
        self.assertTrue(all('ground_truth' not in r and not r['reviewed_by_human'] for r in methods['cnn']))

    def test_incompatible_pair_cannot_replace_low_confidence_answers(self):
        a=capture('1');b=capture('2');a['confidence'][0]=.2
        methods,check=build_methods(a,b,CONFIG,'upload')
        self.assertTrue(check['blocked'])
        self.assertEqual(methods['cnn'][0]['proposed_answer'],'ambiguous')
        self.assertFalse(any(r['used_B'] for r in methods['cnn']))
        a=capture('1',.2)
        methods,check=build_methods(a,b,CONFIG,'upload')
        self.assertFalse(check['blocked']);self.assertEqual(methods['cnn'][0]['proposed_answer'],'2')

    def test_b_replacement_with_conflicting_a_requires_review(self):
        a=capture('1');b=capture('1')
        a['confidence'][0]=.2
        b['predictions'][0]='2'
        methods,_=build_methods(a,b,CONFIG,'upload')
        row=methods['cnn'][0]
        self.assertTrue(row['used_B'])
        self.assertEqual(row['proposed_answer'],'2')
        self.assertIn('ab_disagree',row['review_reasons'])
        self.assertTrue(effective_rows(methods['cnn'],{})[0]['unresolved'])
        self.assertEqual(grade(effective_rows(methods['cnn'],{}),['2']*100,'custom')['status'],'provisional')

    def test_review_does_not_overwrite_model_and_unresolved_score_is_a_range(self):
        rows=build_methods(capture(),None,CONFIG,'x')[0]['cnn']
        rows[0]['needs_review']=True
        before=effective_rows(rows,{})
        key=['1']*100
        self.assertEqual(grade(before,key,'demo')['unresolved'],1)
        decisions=validate_decisions([{'question_no':1,'answer':'blank','reviewed':True}])
        after=effective_rows(rows,decisions);result=grade(after,key,'demo')
        self.assertTrue(result['demo']);self.assertEqual(result['correct'],99);self.assertEqual(result['unresolved'],0)
        self.assertEqual(rows[0]['proposed_answer'],'1');self.assertEqual(after[0]['model_answer'],'1')
        self.assertEqual(after[0]['final_answer'],'blank');self.assertFalse(rows[0]['reviewed_by_human'])
        data=list(csv.DictReader(io.StringIO(export_csv(after,'cnn',{'source':'demo','key':key}).decode('utf-8-sig'))))
        self.assertTrue(all(r['exam_key_source']=='demo' for r in data))
        self.assertEqual(data[0]['model_answer'],'1');self.assertEqual(data[0]['final_answer'],'blank')

    def test_key_and_review_validation(self):
        self.assertEqual(len(parse_exam_key('demo')),100)
        with self.assertRaises(ValueError):parse_exam_key('custom','1 '*99)
        with self.assertRaises(ValueError):parse_exam_key('custom','6 '*100)
        with self.assertRaises(ValueError):validate_decisions([{'question_no':1,'answer':'2','reviewed':False}])
        with self.assertRaises(ValueError):validate_decisions([{'question_no':101,'answer':'2','reviewed':True}])
        text='question_no,answer\n'+'\n'.join(f'{q},{q%5+1}' for q in range(1,101))
        self.assertEqual(len(parse_exam_key('custom',text)),100)

    def test_default_model_prefers_v3_and_explicit_override_still_works(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'presentation_build') as temporary:
            root=Path(temporary);meta=root/'data/metadata';meta.mkdir(parents=True)
            (meta/'image_inventory_verified.csv').write_text('sheet_id,capture_role,pair_status,relative_path\n')
            for name in ('retrained_v3_verified','retrained_v2_perspective'):
                folder=root/'models'/name;folder.mkdir(parents=True)
                (folder/'model_config.json').write_text(json.dumps(CONFIG))
            with patch('omr_app.load_trained_model',return_value=(None,'cpu')):
                app=OMRApplication(root,root/'runs')
                self.assertEqual(app.model_dir,root/'models/retrained_v3_verified')
                app.executor.shutdown(wait=True)
                app=OMRApplication(root,root/'runs2',root/'models/retrained_v2_perspective')
                self.assertEqual(app.model_dir,root/'models/retrained_v2_perspective')
                app.executor.shutdown(wait=True)


class HTTPTests(unittest.TestCase):
    def test_upload_read_review_demo_score_export_and_invalid_image(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'presentation_build') as temporary:
            root=Path(temporary);meta=root/'data/metadata';meta.mkdir(parents=True)
            model=root/'model';model.mkdir();(model/'model_config.json').write_text(json.dumps(CONFIG))
            (meta/'image_inventory_verified.csv').write_text('sheet_id,capture_role,pair_status,relative_path\n')
            with patch('omr_app.load_trained_model',return_value=(None,'cpu')):
                app=OMRApplication(root,root/'runs',model)
            server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            def request(path,payload=None):
                req=Request(base+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json'})
                with urlopen(req,timeout=10) as response:return response.read()
            try:
                image=io.BytesIO();Image.new('RGB',(40,60),'white').save(image,format='JPEG')
                upload={'name':'example.jpg','data':base64.b64encode(image.getvalue()).decode()}
                with patch('omr_app.read_role',return_value=capture()):
                    submitted=json.loads(request('/api/read',{'image_a':upload}))
                    for _ in range(100):
                        job=json.loads(request('/api/jobs/'+submitted['id']))
                        if job['status'] in {'complete','error'}:break
                        time.sleep(.02)
                self.assertEqual(job['status'],'complete');self.assertFalse(job['result']['exam_key_required'])
                self.assertIsNone(job['grading']);job_id=submitted['id']
                request(f'/api/jobs/{job_id}/review',{'method':'cnn','decisions':[{'question_no':1,'answer':'5','reviewed':True}]})
                score=json.loads(request(f'/api/jobs/{job_id}/score',{'method':'cnn','key_mode':'demo'}))
                self.assertTrue(score['demo'])
                exported=list(csv.DictReader(io.StringIO(request(f'/api/jobs/{job_id}/export?method=cnn').decode('utf-8-sig'))))
                self.assertEqual(len(exported),100);self.assertEqual(exported[0]['model_answer'],'1');self.assertEqual(exported[0]['final_answer'],'5')
                self.assertTrue(all(r['exam_key_source']=='demo' for r in exported))
                with patch('omr_app.read_role',return_value=capture()):
                    repeat=json.loads(request('/api/read',{'previous_job':job_id}))
                    for _ in range(100):
                        repeated=json.loads(request('/api/jobs/'+repeat['id']))
                        if repeated['status'] in {'complete','error'}:break
                        time.sleep(.02)
                self.assertEqual(repeated['status'],'complete')
                self.assertEqual(repeated['result']['previous_job'],job_id)
                self.assertFalse(repeated['reviews']['cnn'])
                preserved=json.loads(request('/api/jobs/'+job_id))
                self.assertEqual(preserved['reviews']['cnn']['1']['answer'],'5')
                with self.assertRaises(HTTPError) as caught:request('/api/read',{})
                self.assertEqual(caught.exception.code,400)
                bad=json.loads(request('/api/read',{'image_a':{'name':'bad.jpg','data':base64.b64encode(b'not an image').decode()}}))
                for _ in range(100):
                    failed=json.loads(request('/api/jobs/'+bad['id']))
                    if failed['status']=='error':break
                    time.sleep(.02)
                self.assertEqual(failed['status'],'error')
                with patch('omr_app.read_role',side_effect=ValueError('registration failed')):
                    submitted=json.loads(request('/api/read',{'image_a':upload}))
                    for _ in range(100):
                        failed=json.loads(request('/api/jobs/'+submitted['id']))
                        if failed['status']=='error':break
                        time.sleep(.02)
                self.assertEqual(failed['status'],'error')
                self.assertIn('แบบฟอร์ม 100 ข้อ',failed['error'])
                self.assertIn('จุดอ้างอิง',failed['error'])
            finally:server.shutdown();server.server_close();app.executor.shutdown(wait=True)


if __name__=='__main__':unittest.main()

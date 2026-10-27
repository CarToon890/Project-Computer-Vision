"""Local OMR application: image reading without an exam key, optional demo grading."""
import argparse
import base64
import binascii
import hashlib
import json
import mimetypes
import re
import shutil
import subprocess
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2
import torch
from PIL import Image, ImageOps, UnidentifiedImageError

from omr_model import CLASSES, load_trained_model
from omr_inference import read_csv, read_role
from omr_runtime import build_methods, effective_rows, validate_decisions, parse_exam_key, grade, export_csv

ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'web'
RUNS=ROOT/'output/app_runs'
HEIF=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/libheif/libheif/bin/heif-convert.exe'
MAX_BODY=100*1024*1024


def save_json(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


class OMRApplication:
    def __init__(self,root=ROOT,runs=RUNS,model_dir=None):
        self.root=Path(root);self.runs=Path(runs);self.runs.mkdir(parents=True,exist_ok=True)
        preferred=self.root/'models/retrained_v2_perspective'
        self.model_dir=Path(model_dir or (preferred if preferred.is_dir() else self.root/'models/retrained_v2'))
        self.config=json.loads((self.model_dir/'model_config.json').read_text(encoding='utf-8'))
        if self.config['classes']!=CLASSES:raise ValueError('Model class order is incompatible.')
        torch.set_num_threads(2)
        self.model,self.device=load_trained_model(self.model_dir/self.config['weights_file'],expected_sha256=self.config['weights_sha256'])
        inventory=read_csv(self.root/'data/metadata/image_inventory_verified.csv')
        self.pairs={}
        for row in inventory:
            if row['pair_status']=='verified':self.pairs.setdefault(row['sheet_id'],{})[row['capture_role']]=row
        holds=self.root/'data/metadata/pairing_review_holds.csv'
        blocked={r['sheet_id'] for r in read_csv(holds) if r['review_status']=='pending'} if holds.exists() else set()
        self.pairs={s:p for s,p in self.pairs.items() if set(p)=={'A','B'} and s not in blocked}
        mapping=self.root/'data/metadata/heic_conversion_map.csv'
        self.conversions={r['source_relative_path']:r['normalized_relative_path'] for r in read_csv(mapping)} if mapping.exists() else {}
        self.jobs={};self.lock=threading.RLock();self.executor=ThreadPoolExecutor(max_workers=1)

    def info(self):
        examples=[s for s in ('S0035','S0022','S0106','S0042','S0268') if s in self.pairs]
        return {'service':'local-omr','model_version':self.config.get('model_version','RowCNN'),
            'preprocessing_version':self.config.get('preprocessing_version','legacy-registration'),
            'model_sha256':self.config['weights_sha256'],'device':str(self.device),'examples':examples,
            'verified_pairs':len(self.pairs),'exam_key_required':False,'can_reread':True}

    def get_job(self,job_id):
        if not re.fullmatch(r'[a-f0-9]{32}',job_id):raise ValueError('รหัสงานไม่ถูกต้อง')
        with self.lock:
            if job_id not in self.jobs:
                stored=self.runs/job_id/'result.json'
                if not stored.is_file():raise FileNotFoundError('ไม่พบงานนี้ กรุณาเริ่มอ่านภาพใหม่')
                self.jobs[job_id]={'id':job_id,'status':'complete','progress':'อ่านเสร็จแล้ว','result':json.loads(stored.read_text(encoding='utf-8'))}
            job=dict(self.jobs[job_id])
            if job['status']=='complete':
                reviews=self.runs/job_id/'reviews.json';grading=self.runs/job_id/'grading.json'
                job['reviews']=json.loads(reviews.read_text(encoding='utf-8')) if reviews.exists() else {'cnn':{},'cla':{}}
                job['grading']=json.loads(grading.read_text(encoding='utf-8')) if grading.exists() else None
            return job

    def upload(self,value,folder,role):
        if not isinstance(value,dict) or not isinstance(value.get('data'),str):raise ValueError('กรุณาเลือกไฟล์ภาพ A')
        suffix=Path(str(value.get('name',''))).suffix.lower()
        if suffix not in {'.jpg','.jpeg','.png','.heic','.heif'}:raise ValueError('รองรับ JPG, PNG และ HEIC เท่านั้น')
        try:content=base64.b64decode(value['data'],validate=True)
        except (ValueError,binascii.Error):raise ValueError('ข้อมูลไฟล์ภาพไม่สมบูรณ์')
        if not content or len(content)>45*1024*1024:raise ValueError('ไฟล์ภาพต้องมีขนาดไม่เกิน 45 MB ต่อภาพ')
        source=folder/f'{role}_source{suffix}';source.write_bytes(content)
        provenance={'name':Path(str(value.get('name','image'))).name[:120],'original_sha256':hashlib.sha256(content).hexdigest()}
        if suffix in {'.heic','.heif'}:
            if not HEIF.is_file():raise ValueError('เครื่องนี้ยังไม่มีตัวแปลง HEIC กรุณาส่ง JPG แทน')
            converted=folder/f'{role}_converted.jpg'
            process=subprocess.run([str(HEIF),str(source),str(converted)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess,'CREATE_NO_WINDOW') else 0,timeout=90)
            if process.returncode or not converted.is_file():raise ValueError('แปลงภาพ HEIC ไม่สำเร็จ กรุณาลองส่ง JPG')
            source=converted
        # Verify decoding and composite transparent PNGs onto white before inference.
        try:
            with Image.open(source) as im:
                im=ImageOps.exif_transpose(im)
                if 'A' in im.getbands():
                    rgba=im.convert('RGBA');background=Image.new('RGBA',rgba.size,'white');background.alpha_composite(rgba)
                    source=folder/f'{role}_opaque.jpg';background.convert('RGB').save(source,quality=98)
                else:im.load()
        except (UnidentifiedImageError,OSError,ValueError) as error:
            raise ValueError('เปิดไฟล์ภาพไม่ได้ กรุณาเลือกภาพที่สมบูรณ์') from error
        return source,provenance

    def submit(self,payload):
        if not isinstance(payload,dict):raise ValueError('รูปแบบคำขอไม่ถูกต้อง')
        sample=payload.get('sample_sheet')
        previous=payload.get('previous_job')
        if previous and self.get_job(previous)['status']!='complete':raise ValueError('งานเดิมยังอ่านไม่เสร็จ')
        if sample and sample not in self.pairs:raise ValueError('เลือกแผ่นตัวอย่างที่จับคู่ยืนยันแล้ว')
        if not sample and not payload.get('image_a') and not previous:raise ValueError('กรุณาเลือกภาพ A ก่อน')
        with self.lock:
            if sum(j['status'] in {'queued','running'} for j in self.jobs.values())>=4:raise ValueError('มีงานรออยู่ กรุณารอให้อ่านงานก่อนหน้าเสร็จ')
            job_id=uuid.uuid4().hex;folder=self.runs/job_id;folder.mkdir()
            self.jobs[job_id]={'id':job_id,'status':'queued','progress':'กำลังรออ่านภาพ'}
        self.executor.submit(self.run_job,job_id,payload)
        return {'id':job_id,'status':'queued'}

    def run_job(self,job_id,payload):
        folder=self.runs/job_id;sample=payload.get('sample_sheet');started=time.perf_counter()
        captures={};errors={};sources={};provenance={}
        def progress(message):
            with self.lock:self.jobs[job_id].update(status='running',progress=message)
        try:
            progress('กำลังเตรียมภาพ')
            previous=self.get_job(payload['previous_job'])['result'] if payload.get('previous_job') else None
            if previous and previous.get('sheet_id'):
                sample=previous['sheet_id']
                if sample not in self.pairs:raise ValueError('แผ่นตัวอย่างนี้ไม่อยู่ในชุดที่ยืนยันแล้ว')
                payload={**payload,'a_only':'B' not in previous['sources']}
            if sample:
                for role,row in self.pairs[sample].items():
                    sources[role]=self.root/row['relative_path'];provenance[role]={'name':Path(row['relative_path']).name,'dataset_sheet':sample}
                if payload.get('a_only'):sources.pop('B',None);provenance.pop('B',None)
            else:
                if previous:
                    for role,info in previous['sources'].items():
                        originals=list((self.runs/payload['previous_job']).glob(f'{role}_source.*'))
                        if len(originals)!=1:raise ValueError('ไม่พบไฟล์ต้นฉบับของงานเดิม กรุณาเลือกภาพใหม่')
                        value={'name':info['name'],'data':base64.b64encode(originals[0].read_bytes()).decode()}
                        sources[role],provenance[role]=self.upload(value,folder,role)
                else:
                    sources['A'],provenance['A']=self.upload(payload['image_a'],folder,'A')
                    if payload.get('image_b'):sources['B'],provenance['B']=self.upload(payload['image_b'],folder,'B')
            for role,source in sources.items():
                progress(f'กำลังจัดแนวและอ่านภาพ {role}')
                try:
                    captures[role]=read_role(self.model,self.device,source,self.root,self.conversions,folder,sample,role)
                except (ValueError,OSError,RuntimeError,cv2.error) as error:
                    captures[role]=None;errors[role]=str(error)
            if not any(captures.values()):raise ValueError('จัดแนวภาพไม่ได้ กรุณาใช้แบบฟอร์ม 100 ข้อของระบบ ถ่ายให้เห็นกระดาษและจุดอ้างอิงครบทั้งแผ่น วางกล้องเหนือกระดาษ และหลีกเลี่ยงเงาหรือภาพเบลอ แล้วลองใหม่')
            methods,pair=build_methods(captures.get('A'),captures.get('B'),self.config,sample or f'upload-{job_id[:8]}')
            result={'id':job_id,'sheet_id':sample,'created_at':datetime.now().astimezone().isoformat(),
                'model_version':self.config.get('model_version'),'model_sha256':self.config['weights_sha256'],
                'previous_job':payload.get('previous_job'),
                'preprocessing_version':self.config.get('preprocessing_version','legacy-registration'),
                'sources':provenance,'methods':methods,'pair_check':pair,'errors':errors,
                'assets':{role:{'input':f'/runs/{job_id}/{role}_input.jpg','registered':f'/runs/{job_id}/{role}_registered.jpg','rows':f'/runs/{job_id}/{role}_rows.jpg'}
                    for role,reading in captures.items() if reading},
                'registration':{role:r['registration'] for role,r in captures.items() if r},
                'elapsed_seconds':time.perf_counter()-started,'canonical_labels_written':False,'exam_key_required':False,
                'cla_policy':'existing fill/margin thresholds; B requested for blank/multiple/ambiguous'}
            save_json(folder/'result.json',result)
            with self.lock:self.jobs[job_id].update(status='complete',progress='อ่านภาพเสร็จแล้ว',result=result)
        except Exception as error:
            with self.lock:self.jobs[job_id].update(status='error',progress='อ่านภาพไม่สำเร็จ',error=str(error))
            save_json(folder/'error.json',{'error':str(error),'created_at':datetime.now().astimezone().isoformat()})

    def review(self,job_id,payload):
        job=self.get_job(job_id);method=payload.get('method')
        if job['status']!='complete' or method not in {'cnn','cla'}:raise ValueError('งานนี้ยังไม่พร้อมบันทึกคำตอบ')
        decisions=validate_decisions(payload.get('decisions'))
        with self.lock:
            reviews=self.get_job(job_id)['reviews'];reviews[method].update(decisions)
            save_json(self.runs/job_id/'reviews.json',reviews)
        return {'reviews':reviews}

    def score(self,job_id,payload):
        job=self.get_job(job_id);method=payload.get('method')
        if job['status']!='complete' or method not in {'cnn','cla'}:raise ValueError('งานนี้ยังไม่พร้อมคำนวณคะแนน')
        source=payload.get('key_mode');key=parse_exam_key(source,payload.get('key_text',''))
        rows=effective_rows(job['result']['methods'][method],job['reviews'][method])
        summary=grade(rows,key,source)
        save_json(self.runs/job_id/'grading.json',{'source':source,'key':key})
        return summary


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass

        def send(self,status,body,kind='application/json; charset=utf-8',extra=None):
            if isinstance(body,(dict,list)):body=json.dumps(body,ensure_ascii=False).encode('utf-8')
            if isinstance(body,str):body=body.encode('utf-8')
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            for name,value in (extra or {}).items():self.send_header(name,value)
            self.end_headers();self.wfile.write(body)

        def body(self):
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=MAX_BODY:raise ValueError('ไฟล์หรือคำขอมีขนาดเกินที่รองรับ')
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('รองรับคำขอแบบ JSON เท่านั้น')
            return json.loads(self.rfile.read(length))

        def do_GET(self):
            try:
                url=urlparse(self.path);path=url.path
                static={'/':'app.html','/app.js':'app.js','/style.css':'style.css'}
                if path in static:
                    file=WEB/static[path];self.send(200,file.read_bytes(),mimetypes.guess_type(file.name)[0]+'; charset=utf-8');return
                if path=='/api/info':self.send(200,app.info());return
                match=re.fullmatch(r'/api/jobs/([a-f0-9]{32})(?:/(export|backup))?',path)
                if match:
                    job=app.get_job(match[1]);action=match[2]
                    if not action:self.send(200,job);return
                    if job['status']!='complete':raise ValueError('กรุณารอให้อ่านภาพเสร็จ')
                    if action=='backup':
                        self.send(200,job,extra={'Content-Disposition':f'attachment; filename="omr_{job["id"]}_backup.json"'});return
                    method=parse_qs(url.query).get('method',['cnn'])[0]
                    if method not in {'cnn','cla'}:raise ValueError('วิธีอ่านไม่ถูกต้อง')
                    rows=effective_rows(job['result']['methods'][method],job['reviews'][method])
                    self.send(200,export_csv(rows,method,job['grading']),'text/csv; charset=utf-8',
                        {'Content-Disposition':f'attachment; filename="omr_{method}_{job["id"][:8]}.csv"'});return
                match=re.fullmatch(r'/runs/([a-f0-9]{32})/([AB]_(?:input|registered|rows)\.jpg)',path)
                if match:
                    file=app.runs/match[1]/match[2]
                    if not file.is_file():raise FileNotFoundError('ไม่พบภาพผลลัพธ์')
                    self.send(200,file.read_bytes(),'image/jpeg');return
                self.send(404,{'error':'ไม่พบหน้าที่ต้องการ'})
            except FileNotFoundError as error:self.send(404,{'error':str(error)})
            except (ValueError,KeyError) as error:self.send(400,{'error':str(error)})
            except Exception:self.send(500,{'error':'ระบบไม่สามารถเปิดผลได้ กรุณาลองใหม่'})

        def do_POST(self):
            try:
                origin=self.headers.get('Origin')
                if origin and origin not in {f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'}:
                    self.send(403,{'error':'คำขอต้องมาจากหน้าเว็บระบบบนเครื่องนี้'});return
                payload=self.body();path=urlparse(self.path).path
                if path=='/api/read':self.send(202,app.submit(payload));return
                match=re.fullmatch(r'/api/jobs/([a-f0-9]{32})/(review|score)',path)
                if not match:self.send(404,{'error':'ไม่พบคำสั่ง'});return
                self.send(200,app.review(match[1],payload) if match[2]=='review' else app.score(match[1],payload))
            except FileNotFoundError as error:self.send(404,{'error':str(error)})
            except (ValueError,KeyError,TypeError) as error:self.send(400,{'error':str(error)})
            except Exception:self.send(500,{'error':'ระบบบันทึกผลไม่สำเร็จ กรุณาลองใหม่'})
    return Handler


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--open-browser',action='store_true')
    args=parser.parse_args()
    app=OMRApplication()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler_for(app))
    url=f'http://127.0.0.1:{server.server_port}'
    print(json.dumps({'url':url,**app.info()},ensure_ascii=False),flush=True)
    if args.open_browser:webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();app.executor.shutdown(wait=False,cancel_futures=True)


if __name__=='__main__':main()

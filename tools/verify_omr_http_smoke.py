"""Exercise real local model, HTTP, upload, review, scoring and export."""
import base64
import csv
import io
import json
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from omr_app import OMRApplication,handler_for


def main():
    output=ROOT/'presentation_build/omr_risk_policy_20261027/http_smoke.json'
    if output.exists():raise SystemExit('Existing report preserved')
    with tempfile.TemporaryDirectory(dir=ROOT/'presentation_build') as tmp:
        app=OMRApplication(ROOT,Path(tmp))
        image=app.pairs['S0035']['A']
        source=ROOT/image['relative_path']
        payload={'image_a':{'name':source.name,'data':base64.b64encode(source.read_bytes()).decode()}}
        server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(app))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_port}'
        def request(path,body=None):
            data=json.dumps(body).encode() if body is not None else None
            req=Request(base+path,data=data,headers={'Content-Type':'application/json'})
            with urlopen(req,timeout=30) as response:return response.read()
        try:
            jid=json.loads(request('/api/read',payload))['id']
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                job=json.loads(request('/api/jobs/'+jid))
                if job['status'] in {'error','complete'}:break
                time.sleep(.2)
            if job['status']!='complete':raise RuntimeError(f"Reading did not complete: {job.get('error',job['status'])}")
            original=job['result']['methods']['cnn'][0]['proposed_answer']
            request(f'/api/jobs/{jid}/review',{'method':'cnn','decisions':[{'question_no':1,'answer':'1','reviewed':True}]})
            score=json.loads(request(f'/api/jobs/{jid}/score',{'method':'cnn','key_mode':'demo'}))
            csv_rows=list(csv.DictReader(io.StringIO(request(f'/api/jobs/{jid}/export?method=cnn').decode('utf-8-sig'))))
            if len(csv_rows)!=100 or csv_rows[0]['model_answer']!=original or csv_rows[0]['final_answer']!='1' or not score['demo']:
                raise AssertionError('Upload/review/export assertions failed')
            result={'real_model':True,'image_upload':True,'read_100_questions':True,'review_preserves_original':True,
                    'demo_score':True,'csv_export_rows':len(csv_rows),'model_version':job['result']['model_version'],
                    'sample_note':'S0035 is a development sample; this is functional verification, not accuracy.'}
            output.write_text(json.dumps(result,indent=2),encoding='utf-8')
            print(json.dumps(result,indent=2))
        finally:
            server.shutdown();server.server_close();app.executor.shutdown(wait=True)


if __name__=='__main__':main()

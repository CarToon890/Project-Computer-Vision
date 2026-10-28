"""Recompute per-class, per-question and selective metrics on saved Image-A test crops."""
import csv
import hashlib
import html
import json
import sys
import time
from datetime import datetime
from pathlib import Path
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from omr_model import CLASSES, load_trained_model

def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def ratio(n, d): return n/d if d else None
def main():
    sys.stdout.reconfigure(encoding='utf-8')
    out = ROOT/'presentation_build'/('cnn_metrics_image_a_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
    out.mkdir(parents=True, exist_ok=False)
    inp = ROOT/'presentation_build/retraining_v4_single_a_20261029/fresh_image_a_crops_and_scores.npz'
    with np.load(inp, allow_pickle=False) as z:
        ids=np.flatnonzero(z['split']=='test')
        crops=z['crops'][ids]; truths=z['targets'][ids]; qs=z['question_no'][ids]
        geometry=str(z['geometry_hash'])
    paths={'CNN รุ่นแรก':ROOT/'models/row_cnn.pt', 'CNN v2':ROOT/'models/retrained_v2_perspective/row_cnn.pt',
           'CNN v3':ROOT/'models/retrained_v3_verified/row_cnn.pt',
           'v4 Candidate':ROOT/'presentation_build/retraining_v4_single_a_20261029/candidate_single_a.pt',
           'v4 Final':ROOT/'presentation_build/retraining_v4_single_a_20261029/final_model/row_cnn.pt'}
    cfgs={'CNN รุ่นแรก':ROOT/'models/model_config.json','CNN v2':ROOT/'models/retrained_v2_perspective/model_config.json','CNN v3':ROOT/'models/retrained_v3_verified/model_config.json'}
    torch.set_num_threads(4)
    result={}; per_question=[]; predictions={}
    for name,path in paths.items():
        model,_=load_trained_model(path,device='cpu'); start=time.perf_counter(); probs=[]
        with torch.inference_mode():
            for pos in range(0,len(crops),256):
                batch=torch.from_numpy(crops[pos:pos+256,None].astype(np.float32)/255.)
                probs.append(torch.softmax(model(batch),dim=1).numpy())
        seconds=time.perf_counter()-start
        p=np.concatenate(probs); pred=p.argmax(axis=1); conf=p.max(axis=1)
        config=json.loads(cfgs[name].read_text(encoding='utf8')) if name in cfgs else json.loads(cfgs['CNN v3'].read_text(encoding='utf8'))
        cutoff=config['cnn_confidence_cutoff']
        accepted=np.array([CLASSES[int(v)] in ('1','2','3','4','5') and c>=cutoff for v,c in zip(pred,conf)])
        mat=np.zeros((len(CLASSES),len(CLASSES)),dtype=int)
        for t,pr in zip(truths,pred):mat[int(t),int(pr)]+=1
        per_class=[]
        for j,label in enumerate(CLASSES):
            tp=int(mat[j,j]); support=int(mat[j,:].sum()); predicted=int(mat[:,j].sum())
            precision=ratio(tp,predicted); recall=ratio(tp,support)
            f1=2*tp/(support+predicted) if support+predicted else None
            per_class.append({'class':label,'support':support,'predicted':predicted,'precision':precision,'recall':recall,'f1':f1})
        # Macro over classes with truth support; predicted classes with no truth are identified separately.
        supported=[x for x in per_class if x['support']>0]
        means={k:sum((x[k] or 0) for x in supported)/len(supported) for k in ('precision','recall','f1')}
        ok=int(np.sum((pred==truths)&accepted)); wrong=int(np.sum((pred!=truths)&accepted)); deferred=int((~accepted).sum())
        result[name]={'model_sha256':digest(path),'n':len(truths),'raw_correct':int((pred==truths).sum()),
          'raw_accuracy':float((pred==truths).mean()), 'confusion_matrix':mat.tolist(),'per_class':per_class,'macro_supported':means,
          'cutoff':cutoff,'decision_correct':ok,'decision_wrong':wrong,'decision_deferred':deferred,
          'decision_accuracy':ratio(ok,ok+wrong),'decision_yield':ratio(ok,len(truths)),
          'inference_batch_seconds':seconds}
        predictions[name]=pred
        for q in range(1,101):
            mask=qs==q;n=int(mask.sum());raw=int(np.sum((pred==truths)&mask));auto=int(np.sum((pred==truths)&accepted&mask));err=int(np.sum((pred!=truths)&accepted&mask));waiting=int(np.sum((~accepted)&mask))
            per_question.append({'model':name,'question':q,'n':n,'raw_correct':raw,'raw_accuracy':ratio(raw,n),'correct_auto':auto,'wrong_auto':err,'review':waiting,'auto_correct_share':ratio(auto,n)})
    with (out/'accuracy_by_question.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(per_question[0]));w.writeheader();w.writerows(per_question)
    payload={'n':len(truths),'geometry_hash':geometry,'input_sha256':digest(inp),'classes':CLASSES,'models':result,'per_question':per_question,
      'limitations':'Assisted retrospective test, not independent. Confusion matrix and PRF use raw argmax, not review policy. Retake rate unavailable. Images processed successfully only; no failures measured by this script.'}
    (out/'metrics.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    # Standalone interactive analysis; no network or raw student images embedded.
    data=json.dumps(payload,ensure_ascii=False).replace('</','<\\/')
    doc='''<!doctype html><html lang="th"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>เปรียบเทียบ CNN ภาพ A</title><style>body{font:15px system-ui;max-width:1200px;margin:24px auto;padding:0 18px;color:#202a35}h1{font-size:24px}h2{font-size:19px;margin-top:30px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid #ddd;padding:7px;text-align:right}th:first-child,td:first-child{text-align:left}th{background:#f3f5f7}select{font-size:16px;padding:6px}small{color:#4b5964}.scroll{overflow:auto}.note{padding:12px;background:#f3f5f7;line-height:1.6}</style><h1>ผลเปรียบเทียบ CNN จากภาพ A</h1><p class="note">Test เดิม 1,129 ข้อ · การทดสอบย้อนหลัง ไม่ใช่ชุดอิสระ · Accuracy ดิบและ Confusion Matrix ใช้คำตอบที่ CNN ทำนายก่อนส่งตรวจ · ไม่ทราบอัตราถ่ายซ้ำจริง</p><label>เลือกโมเดล <select id="model"></select></label><div id="body"></div><script>const data=DATA;const pct=x=>x==null?'ไม่มีข้อมูล':(100*x).toFixed(2)+'%';const sel=document.getElementById('model');Object.keys(data.models).forEach(x=>{const o=document.createElement('option');o.value=o.textContent=x;sel.appendChild(o)});sel.value='CNN v3';function draw(){const n=sel.value,m=data.models[n];let s=`<h2>ผลรวม: ${n}</h2><p>Accuracy ดิบ ${m.raw_correct}/${m.n} = <b>${pct(m.raw_accuracy)}</b> · Precision / Recall / F1 แบบ macro (เฉลี่ยคลาสที่มีตัวอย่างจริง) ${pct(m.macro_supported.precision)} / ${pct(m.macro_supported.recall)} / ${pct(m.macro_supported.f1)}</p><p>เกณฑ์ confidence ${m.cutoff.toFixed(3)}: ระบบตอบเองถูก ${m.decision_correct}, ตอบเองผิด ${m.decision_wrong}, รอตรวจ ${m.decision_deferred} · ถูกจากทั้งหมด ${pct(m.decision_yield)}</p><p>เวลา CNN แบบ batch บน CPU ${m.inference_batch_seconds.toFixed(3)} วินาที สำหรับ 1,129 ภาพตัด ไม่รวมจัดแนว/โหลดภาพ/เว็บ · วัดครั้งเดียว</p><h2>Precision / Recall / F1 รายชนิดคำตอบ</h2><div class="scroll"><table><tr><th>ชนิดคำตอบจริง</th><th>จำนวนจริง</th><th>จำนวนที่โมเดลทำนาย</th><th>Precision</th><th>Recall</th><th>F1</th></tr>${m.per_class.map(x=>`<tr><td>${x.class}</td><td>${x.support}</td><td>${x.predicted}</td><td>${pct(x.precision)}</td><td>${pct(x.recall)}</td><td>${pct(x.f1)}</td></tr>`).join('')}</table></div><h2>Confusion Matrix — ผลทำนายดิบ</h2><p>แถว = คำตอบจริง · คอลัมน์ = คำตอบที่โมเดลทำนาย · หน่วย: ข้อ</p><div class="scroll"><table><tr><th>จริง / ทำนาย</th>${data.classes.map(x=>`<th>${x}</th>`).join('')}</tr>${m.confusion_matrix.map((row,i)=>`<tr><td>${data.classes[i]}</td>${row.map(v=>`<td>${v}</td>`).join('')}</tr>`).join('')}</table></div><h2>Accuracy รายข้อสอบ (ข้อ 1–100)</h2><p>ดิบ = ทำนายถูก / จำนวนตัวอย่างของข้อนั้น · ระบบตอบเองถูก/ผิดและรอตรวจใช้เกณฑ์ confidence ของแต่ละรุ่น</p><div class="scroll"><table><tr><th>ข้อ</th><th>จำนวนตัวอย่าง</th><th>ทำนายถูกดิบ</th><th>Accuracy ดิบ</th><th>ระบบตอบเองถูก</th><th>ระบบตอบเองผิด</th><th>รอตรวจ</th></tr>${data.per_question.filter(x=>x.model===n).map(x=>`<tr><td>${x.question}</td><td>${x.n}</td><td>${x.raw_correct}</td><td>${pct(x.raw_accuracy)}</td><td>${x.correct_auto}</td><td>${x.wrong_auto}</td><td>${x.review}</td></tr>`).join('')}</table></div><h2>ข้อจำกัด</h2><p>คำตอบเว้นว่างมี 3 ตัวอย่าง ฝนหลายช่อง 1 ตัวอย่าง ไม่มี ambiguous จึงยังสรุปความสามารถในกรณีพิเศษไม่ได้; ข้อสอบแต่ละข้อมีตัวอย่างจำกัด; คะแนน softmax ไม่ใช่ความน่าจะเป็นว่าถูกจริง และยังไม่มีข้อมูลถ่ายซ้ำจริง</p>`;document.getElementById('body').innerHTML=s}sel.onchange=draw;draw()</script></html>'''.replace('DATA',data)
    (out/'index.html').write_text(doc,encoding='utf-8')
    print('output',out)
    for n,m in result.items():print(n,'raw',m['raw_correct'],m['n'],m['raw_accuracy'],'macro',m['macro_supported'],'decision',m['decision_correct'],m['decision_wrong'],m['decision_deferred'],'seconds',m['inference_batch_seconds'])
if __name__=='__main__':main()

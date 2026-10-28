"""Recompute frozen Test metrics and render an evidence-based summary image."""
import json,sys,hashlib
from pathlib import Path
import numpy as np, torch
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from omr_model import load_trained_model
from omr_retrain_v3 import evaluate
work=ROOT/'presentation_build/retraining_v3_20261028'; selection=json.loads((work/'verified_only/selection.json').read_text(encoding='utf8'))
source=work/'input/confirmed_rows.npz'
if hashlib.sha256(source.read_bytes()).hexdigest()!=selection['data_sha256']:raise SystemExit('Test data checksum differs from frozen selection')
with np.load(source,allow_pickle=False) as f:data={k:f[k] for k in f.files}
idx=np.flatnonzero(data['split']=='test');torch.set_num_threads(2);results={};allrows={}
for name,folder in [('v2',ROOT/'models/retrained_v2_perspective'),('v3',ROOT/'models/retrained_v3_verified')]:
 config=json.loads((folder/'model_config.json').read_text(encoding='utf8'));model,dev=load_trained_model(folder/'row_cnn.pt','cpu',config['weights_sha256'])
 results[name],allrows[name]=evaluate(model,data,idx,dev,config['cnn_confidence_cutoff'])
saved=json.loads((work/'verified_only/evaluation.json').read_text(encoding='utf8'))['results']['all_confirmed_test']
assert results['v2']['A_only']==saved['v2']['A_only'] and results['v2']['A_then_B']==saved['v2']['A_then_B']
assert results['v3']['A_only']==saved['selected']['A_only'] and results['v3']['A_then_B']==saved['selected']['A_then_B']
labels=['1','2','3','4','5','blank','multiple'];cols=labels+['review'];matrix=np.zeros((7,8),dtype=int)
for r in allrows['v3']:
 out='review' if r['a_then_b_deferred'] else r['a_then_b'];matrix[labels.index(r['ground_truth']),cols.index(out)]+=1
support=matrix.sum(1);predicted=matrix.sum(0)[:7];tp=np.diag(matrix[:,:7]);precision=np.divide(tp,predicted,out=np.zeros(7),where=predicted!=0);recall=np.divide(tp,support,out=np.zeros(7),where=support!=0);f1=np.divide(2*precision*recall,precision+recall,out=np.zeros(7),where=(precision+recall)!=0)
weighted=lambda x:100*float(np.average(x,weights=support))
metrics={'accuracy':100*sum(tp)/len(allrows['v3']),'precision':weighted(precision),'recall':weighted(recall),'weighted_f1':weighted(f1),'macro_f1':100*float(np.mean(f1))}
N=2400;H=3100;im=Image.new('RGB',(N,H),'#f5f7f6');d=ImageDraw.Draw(im)
def font(n,b=False):return ImageFont.truetype('C:/Windows/Fonts/'+('tahomabd.ttf' if b else 'tahoma.ttf'),n)
f18,f22,f26,f30,f34,f42,f54,f70=font(18),font(22),font(26),font(30),font(34),font(42,True),font(54,True),font(70,True)
navy='#102d40';ink='#17313e';muted='#526b74';green='#087c68';blue='#366f9a';amber='#9d651b';line='#d9e5e0';white='#ffffff'
def txt(x,y,t,f=f30,c=ink):d.text((x,y),t,font=f,fill=c)
def center(cx,y,t,f=f30,c=ink):box=d.textbbox((0,0),t,font=f);d.text((cx-(box[2]-box[0])/2,y),t,font=f,fill=c)
def box(x,y,w,h,fill=white,stroke=line,rad=24):d.rounded_rectangle((x,y,x+w,y+h),radius=rad,fill=fill,outline=stroke,width=2)
# Header
d.rectangle((0,0,N,292),fill=navy)
txt(88,50,'สรุปผลการอ่านกระดาษคำตอบ',f70,'#ffffff')
txt(91,143,'CNN v3 เทียบ CNN v2  •  ภาพ A และ A+B  •  28 ตุลาคม 2026',f34,'#d4e8e2')
txt(91,209,'ผลทดสอบระหว่างพัฒนา ยังไม่ใช่การทดสอบอิสระ',font(32,True),'#ffd994')
# sample context
box(70,318,2260,130,fill='#e8f2ee',stroke='#d5e7df')
txt(105,337,'ชุด Test: 35 แผ่น  /  70 ภาพ A–B  /  1,129 ข้อที่คนตรวจยืนยัน',font(40,True),green)
txt(108,397,'10 แผ่นตรวจครบ 100 ข้อ และอีก 25 แผ่นตรวจเพียงบางข้อ',f26,muted)
# v3 A+B headline
center(1200,482,'ผลหลัก CNN v3  |  A+B',font(45,True),ink)
items=[('Accuracy รวม',metrics['accuracy']),('Precision',metrics['precision']),('Recall',metrics['recall']),('Weighted F1',metrics['weighted_f1'])]
for i,(name,val) in enumerate(items):
 x=70+i*575;box(x,558,535,200);txt(x+28,582,name,f30,muted);txt(x+28,632,f'{val:.2f}%',font(60,True),green)
box(70,784,2260,128,fill='#fff6e6',stroke='#f1dbb5')
txt(103,803,f"Macro F1  {metrics['macro_f1']:.2f}%",font(40,True),amber)
txt(565,811,'เฉลี่ยเท่ากัน 7 คลาส • เว้นว่าง 3 ตัวอย่าง / หลายช่อง 1 ตัวอย่าง',f30,ink)
# grouped comparison
box(70,944,2260,738)
txt(107,970,'เปรียบเทียบภาพ A กับ A+B บนข้อชุดเดียวกัน',font(42,True),ink)
txt(110,1025,'Accuracy = ถูกและยอมรับ ÷ 1,129 ข้อ  |  แกนกราฟแสดงช่วง 95–100%',f26,muted)
x0,x1=590,1465; top=1110; span=x1-x0
for p in range(95,101):
 x=x0+(p-95)*span/5;d.line((x,top-10,x,top+452),fill='#e2eae6',width=2);center(x,top+462,str(p)+'%',f22,muted)
for i,(name,method,model) in enumerate([('CNN v2  •  A','A_only','v2'),('CNN v2  •  A+B','A_then_B','v2'),('CNN v3  •  A','A_only','v3'),('CNN v3  •  A+B','A_then_B','v3')]):
 y=top+i*104;r=results[model][method];a=100*r['correct_accepted']/r['questions'];color=blue if model=='v2' else green
 txt(110,y+8,name,font(30,True),ink);d.rounded_rectangle((x0,y+12,x1,y+54),radius=10,fill='#eef3f0');end=x0+max(0,min(1,(a-95)/5))*span;d.rounded_rectangle((x0,y+12,end,y+54),radius=10,fill=color)
 txt(x1+24,y+4,f'{a:.2f}%',font(35,True),color);txt(1655,y+9,f"ถูก {r['correct_accepted']:,}   ผิด {r['wrong_accepted']}   รอ {r['deferred']}",f30,ink)
txt(110,1640,'หมายเหตุ: จำนวนผิดคือคำตอบที่ระบบยอมรับผิด • จำนวนรอคือข้อที่ส่งให้คนตรวจ',f26,muted)
# matrix
box(70,1716,2260,1095)
txt(108,1745,'Confusion Matrix  |  CNN v3 A+B',font(42,True),ink)
txt(110,1803,'แถว = คำตอบอ้างอิงจากคนตรวจ     คอลัมน์ = ผลที่ระบบยอมรับ / รอตรวจ',f26,muted)
headers=['1','2','3','4','5','เว้นว่าง','หลายช่อง','รอตรวจ'];actual=['1','2','3','4','5','เว้นว่าง','ฝนหลายช่อง']
mx=540; cw=208; ch=103; my=1900
center(277,my+4,'คำตอบจริง',font(30,True),muted)
for j,h in enumerate(headers):center(mx+j*cw+cw/2,my+4,h,font(26,True),muted)
for i,label in enumerate(actual):
 y=my+56+i*ch;center(277,y+28,label,font(30,True),ink)
 for j in range(8):
  n=int(matrix[i,j]);x=mx+j*cw
  fill=('#126d5d' if n>=100 else '#b8dfd0' if n>2 else '#ffe8bb' if n>0 else '#f2f5f3')
  d.rounded_rectangle((x+4,y+4,x+cw-4,y+ch-4),radius=10,fill=fill)
  center(x+cw/2,y+22,str(n),font(34,n>0),'#ffffff' if n>=100 else ink if n else '#a1b0a9')
txt(110,2690,'คอลัมน์รอตรวจรวมข้อที่ระบบยังไม่ยอมรับคำตอบอัตโนมัติ',f26,muted)
txt(110,2740,'2 ข้อที่ยอมรับผิด: เว้นว่างถูกอ่านเป็น 1 และฝนหลายช่องถูกอ่านเป็น 4',f26,amber)
# Footer
box(70,2844,2260,185,fill='#e8f2ee',stroke='#d5e7df')
txt(105,2869,'วิธีนับ: ข้อรอตรวจรวมอยู่ในตัวหาร Accuracy และ Recall',font(30,True),ink)
txt(105,2915,'Precision / Recall / F1 แบบถ่วงน้ำหนักตามจำนวนตัวอย่าง • Macro เฉลี่ย 7 คลาสเท่ากัน',f26,muted)
txt(105,2955,'การประเมิน A+B เป็นนโยบายรายข้อ และไม่ได้ใช้ตัวตรวจความขัดแย้ง A/B ทั้งแผ่น',f26,muted)
path=ROOT/'output/accuracy_test_v3/omr_main_results_v3_vs_v2.png';im.save(path,optimize=True)
print('METRICS',json.dumps(metrics));print('MATRIX',matrix.tolist());print('IMAGE',path)

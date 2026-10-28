"""Create print-ready source for the CNN report from previously saved results."""
from pathlib import Path
import html, json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'output/pdf'
OUT.mkdir(parents=True,exist_ok=True)
metrics=json.loads((ROOT/'presentation_build/cnn_metrics_image_a_20261029_032056/metrics.json').read_text(encoding='utf8'))
abv=json.loads((ROOT/'presentation_build/retraining_v3_20261028/verified_only/evaluation.json').read_text(encoding='utf8'))['results']['all_confirmed_test']
ab4=json.loads((ROOT/'presentation_build/v4_comparison_retry_20261028/test_evaluation.json').read_text(encoding='utf8'))['results']['all_confirmed_test']
pol=json.loads((ROOT/'presentation_build/retraining_v4_single_a_20261029/rigorous_single_a_evaluation_fresh_geometry.json').read_text(encoding='utf8'))['evaluation_results']['v4_candidate']['cohorts']['test_all_confirmed_1129']['policies']
names=list(metrics['models']); labels=['1','2','3','4','5','ว่าง','หลาย','กำกวม']
H=html.escape
def pct(x): return '—' if x is None else f'{x*100:.2f}%'
def table(head,rows,cls=''):
 return '<table class="'+cls+'"><thead><tr>'+''.join('<th>'+str(x)+'</th>' for x in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table>'
def page(title,kicker,body):
 return '<section class="page"><header><div class="kicker">'+kicker+'</div><h1>'+title+'</h1></header>'+body+'</section>'

metrics_rows=[]; selection_rows=[]
for name in names:
 m=metrics['models'][name]; a=m['macro_supported']
 assert sum(map(sum,m['confusion_matrix']))==1129 and m['decision_correct']+m['decision_wrong']+m['decision_deferred']==1129
 metrics_rows.append([name,f"{m['raw_correct']}/1,129",pct(m['raw_accuracy']),pct(a['precision']),pct(a['recall']),pct(a['f1'])])
 selection_rows.append([name,f"{m['cutoff']:.3f}",m['decision_correct'],m['decision_wrong'],m['decision_deferred'],pct(m['decision_accuracy']),pct(m['decision_yield'])])
profile=[['รุ่นแรก','26 ต.ค. 2026*','38 แผ่น / 3,800 คำตอบในชุดตั้งต้น','ข้อดี: รุ่นพื้นฐานไว้เปรียบเทียบ; ข้อจำกัด: ข้อมูลฝึกน้อย เกณฑ์เดิมส่งตรวจมาก'],['v2 + perspective','26 ต.ค. 2026*','Train 3,259; Validation 400','ข้อดี: ใช้ข้อมูลยืนยันเพิ่ม; ข้อจำกัด: ผล A ใน Test มีข้อผิดที่ตอบเองมากกว่า v3'],['v3','28 ต.ค. 2026 00:18','Train 5,591; Validation 433','ข้อดี: ผลทำนายดิบรวมสูงสุดในชุดนี้; ข้อจำกัด: ตัวอย่างรอยพิเศษยังน้อย ใช้จริงในระบบ'],['v4 Candidate','29 ต.ค. 2026 01:28','ฝึก Train 5,591 ข้อ','ข้อดี: ทดลองเกณฑ์ร่วม CLA ได้; ข้อจำกัด: ผลดิบรวมต่ำกว่า v3 ในชุดนี้ ยังเป็นรุ่นทดลอง'],['v4 Final','29 ต.ค. 2026 01:32','Train + Validation 6,024 ข้อ','ข้อดี: ใช้คำตอบยืนยันฝึกเพิ่ม; ข้อจำกัด: Validation เป็นข้อมูลฝึก ยังเป็นรุ่นทดลอง']]
first=page('สรุปผลการทดลอง CNN','ภาพ A • Test 1,129 ข้อ • 29 ตุลาคม 2026',
 '<div class="intro">ผลทดสอบก่อนคนแก้ ใช้ภาพ A ของ 35 แผ่น; ข้อมูลชุดนี้เคยใช้ประเมินระหว่างพัฒนา</div>'+
 '<h2>ผลทำนายดิบก่อนใช้เกณฑ์ส่งตรวจ</h2>'+table(['โมเดล','ตรง / ทั้งหมด','Accuracy','Precision','Recall','F1'],metrics_rows)+
 '<p class="muted">Precision / Recall / F1 เป็น macro เฉลี่ยเท่ากันเฉพาะ 7 ประเภทที่มีคำตอบจริง; Accuracy = ผลทำนายตรง ÷ 1,129</p>'+
 '<h2>ประวัติโมเดลและลักษณะเด่น</h2>'+table(['รุ่น','อัปเดตน้ำหนัก','ข้อมูลฝึก / เลือก','สถานะและข้อสังเกต'],profile)+
 '<p class="muted">* วันที่รุ่นแรกและ v2 อ้างอิงจากบันทึกการฝึก; รุ่นอื่นเป็นเวลาที่ไฟล์น้ำหนักถูกแก้ไขบนเครื่อง ไม่จำเป็นต้องเท่ากับเวลาฝึก</p>'+
 '<div class="box">ข้อจำกัดร่วม: Test มีคำตอบเว้นว่างเพียง 3 ข้อ ฝนหลายช่อง 1 ข้อ และไม่มีตัวอย่างกำกวม จึงยังวัดกรณีพิเศษได้ไม่เพียงพอ</div>')
definitions='<p>ทุกวิธีเริ่มจากผล CNN หาก CNN อ่านว่าเว้นว่าง หลายช่อง หรือกำกวม ให้คนตรวจในผลทดลองนี้</p><ul><li><b>CNN อย่างเดียว:</b> ตอบเองเมื่อคะแนนความมั่นใจถึงเกณฑ์</li><li><b>CNN + CLA agreement:</b> ต้องมั่นใจและ CNN ตอบตรงกับ CLA</li><li><b>CNN + CLA margin:</b> ต้องมั่นใจและคะแนน CLA ผ่านเกณฑ์ความต่าง</li><li><b>CNN + CLA hybrid:</b> ใช้ความมั่นใจ ความตรงกัน และความต่างร่วมกัน โดยยืดหยุ่นบางเงื่อนไขเมื่อ CNN มีคะแนนสูง</li></ul>'
prow=[]
for key,label in [('cnn_cutoff_only','CNN อย่างเดียว'),('cnn_cla_agreement','เห็นตรงกับ CLA'),('cnn_cla_margin','ใช้ความต่าง CLA'),('cnn_cla_hybrid','Hybrid')]:
 v=pol[key];prow.append([label,v['correct_accepted'],v['wrong_accepted'],v['deferred']])
abrows=[]
for label,v in [('v2',abv['v2']['A_then_B']),('v3',abv['selected']['A_then_B']),('v4 verified_long',ab4['verified_long']['A_then_B'])]:
 assert sum(v[k] for k in ['correct_accepted','wrong_accepted','deferred'])==1129
 abrows.append([label,'1,129',v['correct_accepted'],v['wrong_accepted'],v['deferred'],v['used_b']])
abrows += [['CNN รุ่นแรก','1,000','993','0','7','66'],['v4 Candidate / Final','—','ไม่มีผล','ไม่มีผล','ไม่มีผล','ไม่มีผล']]
second=page('ผลหลังตัดสินและการใช้ภาพ B','เกณฑ์ตัดสิน • ตัวเลขก่อนคนแก้',
 '<h2>ภาพ A: แต่ละโมเดลใช้ cutoff ของตน</h2>'+table(['รุ่น','cutoff','ตอบเองถูก','ตอบเองผิด','รอตรวจ','ถูก/ที่ตอบเอง','ถูก/ทั้งหมด'],selection_rows)+
 '<p class="muted">สองคอลัมน์เปอร์เซ็นต์ใช้ตัวหารต่างกัน รุ่นแรกใช้ cutoff เดิมของตน; v4 ใช้ cutoff v3</p>'+
 '<h2>ทดลองวิธีตัดสินต่างกันบน v4 Candidate และภาพ A ชุดเดียวกัน</h2>'+table(['วิธีตัดสิน','ตอบเองถูก','ตอบเองผิด','รอตรวจ'],prow)+definitions+
 '<h2>ภาพ A แล้วใช้ B ช่วย (A-then-B)</h2>'+table(['รุ่น','จำนวนข้อ','ตอบเองถูก','ตอบเองผิด','รอตรวจ','ใช้ B (ข้อ)'],abrows)+
 '<p class="muted">v2/v3/v4 verified_long ใช้ Test 1,129 ข้อและวิธีรายข้อ ไม่รวม gate ทั้งแผ่น; v4 verified_long เป็นคนละน้ำหนักกับ Candidate/Final ภาพ A. รุ่นแรกใช้ Test 1,000 ข้อในรอบก่อน จึงไม่เทียบตรงกับแถว 1,129 ข้อ</p>'+
 '<h2>เวลาที่มีบันทึก</h2><p>เวลา CNN แบบ batch สำหรับ 1,129 ภาพตัด บน CPU วัดครั้งเดียว: '+', '.join(H(n)+' '+f"{metrics['models'][n]['inference_batch_seconds']:.3f}"+' วินาที' for n in names)+'. ไม่รวมอ่านภาพ จัดแนว อัปโหลดหรือเว็บ; จำนวนภาพ B คือจำนวนข้อที่ใช้ B ไม่ใช่จำนวนครั้งถ่ายใหม่จริง</p>')

pages=[first,second]
for name in names:
 m=metrics['models'][name]; mat=m['confusion_matrix'];assert sum(map(sum,mat))==1129
 matrix=table(['จริง \\ ทำนาย']+labels,[[labels[i]]+row for i,row in enumerate(mat)],'matrix')
 classes=[]
 for c in m['per_class']:
  classes.append([{'blank':'เว้นว่าง','multiple':'หลายช่อง','ambiguous':'กำกวม'}.get(c['class'],c['class']),c['support'],c['predicted'],pct(c['precision']),pct(c['recall']),pct(c['f1'])])
 pages.append(page('Confusion Matrix • '+H(name),'ภาพ A • ผลทำนายดิบก่อนส่งตรวจ',
  '<p>แถวคือคำตอบอ้างอิงจากคนตรวจ คอลัมน์คือผล CNN หน่วยเป็นจำนวนข้อ; สีเข้มแสดงตัวเลขในแนวทแยงเมื่อทำนายตรง</p>'+matrix+
  '<h2>ตัวชี้วัดแยกตามชนิดคำตอบ</h2>'+table(['คำตอบ','จำนวนจริง','จำนวนทำนาย','Precision','Recall','F1'],classes)+
  '<p class="muted">Precision = ทำนายประเภทนั้นถูก ÷ จำนวนที่ทำนายเป็นประเภทนั้น; Recall = ทำนายประเภทนั้นถูก ÷ จำนวนจริง; F1 = 2PR/(P+R). เครื่องหมาย — หมายถึงตัวหารเป็นศูนย์; ใน macro สำหรับประเภทที่มีคำตอบจริงแต่ไม่มีผลทำนาย ใช้ precision = 0</p>'))
 entries=[r for r in metrics['per_question'] if r['model']==name]
 assert len(entries)==100 and sum(r['n'] for r in entries)==1129
 blocks=[]
 for start in range(0,100,25):
  rows=[]
  for r in entries[start:start+25]:
   rows.append([r['question'],r['n'],f"{r['raw_correct']}/{r['n']}",pct(r['raw_accuracy'])])
  blocks.append('<div>'+table(['ข้อ','จำนวน','ตรง','Accuracy'],rows,'qtable')+'</div>')
 pages.append(page('Accuracy รายข้อ • '+H(name),'ภาพ A • ผลทำนายดิบก่อนส่งตรวจ',
  '<p>จำนวนคือจำนวนคำตอบอ้างอิงของข้อสอบข้อนั้น; ตรงคือจำนวนที่ CNN ทำนายตรงกับคำตอบอ้างอิง</p><div class="qgrid">'+''.join(blocks)+'</div><p class="muted">ตัวอย่างแต่ละข้อมีจำนวนน้อย ผลรายข้อจึงอาจเปลี่ยนได้มากเมื่อมีข้อมูลเพิ่ม</p>'))

css='''@page{size:A4;margin:12mm 12mm 14mm}*{box-sizing:border-box}body{font-family:"Leelawadee UI",Tahoma,sans-serif;color:#172c3c;font-size:10pt;line-height:1.38}section.page{break-after:page}section.page:last-child{break-after:auto}header{border-bottom:2px solid #087c70;padding-bottom:6px;margin-bottom:12px}.kicker{font-size:9pt;color:#087c70;font-weight:bold}h1{font-size:20pt;margin:3px 0 1px}h2{font-size:13pt;color:#087c70;margin:14px 0 6px}p{margin:5px 0 8px}ul{margin:3px 0 8px;padding-left:20px}.intro,.box{background:#e8f4f0;padding:9px;border-radius:6px}.box{margin-top:12px}.muted{font-size:8.5pt;color:#526977}table{width:100%;border-collapse:collapse;font-size:9pt;line-height:1.25}th{background:#12354b;color:white;text-align:left;font-weight:bold}th,td{padding:5px 6px;border-bottom:1px solid #d8e2e3}tbody tr:nth-child(even){background:#f5f8f8}.matrix th,.matrix td{text-align:center;padding:7px 5px}.matrix tbody tr:nth-child(1) td:nth-child(2),.matrix tbody tr:nth-child(2) td:nth-child(3),.matrix tbody tr:nth-child(3) td:nth-child(4),.matrix tbody tr:nth-child(4) td:nth-child(5),.matrix tbody tr:nth-child(5) td:nth-child(6),.matrix tbody tr:nth-child(6) td:nth-child(7),.matrix tbody tr:nth-child(7) td:nth-child(8),.matrix tbody tr:nth-child(8) td:nth-child(9){background:#d4eee7;font-weight:bold}.qgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.qtable{font-size:8pt}.qtable th,.qtable td{padding:4px 3px;text-align:center}.qtable th:first-child,.qtable td:first-child{text-align:left}'''
doc='<!doctype html><html lang="th"><meta charset="utf-8"><head><title>รายงานเปรียบเทียบ CNN OMR</title><style>'+css+'</style></head><body>'+''.join(pages)+'</body></html>'
(OUT/'cnn_experiment_report_source.html').write_text(doc,encoding='utf8')
print('Created print source, expected pages:',len(pages))

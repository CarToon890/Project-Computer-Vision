"""Create an isolated Test-39 snapshot after explicit user bulk confirmation.

Never modifies dataset 1, its browser state, model files, or historical results.
Bulk confirmation records approval, not a claim of individual visual inspection.
"""
import csv
import hashlib
import json
import os
import re
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
META=ROOT/'data/metadata'
DEST=ROOT/'data/dataset_v2_test39'
BACKUP=Path('C:/Users/USER/Downloads/answer_review_backup (3).json')

def read_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def write_json(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def write_csv(path,rows,fields):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)

def main():
    if DEST.exists():raise FileExistsError('Dataset 2 already exists; preserve it and explicitly version subsequent updates.')
    protected=[META/n for n in ['answer_labels.csv','sheet_splits.csv','image_inventory_verified.csv','answer_review.html']]
    protected += list((ROOT/'models').rglob('*.pt'))+[BACKUP]
    before={str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p):sha(p) for p in protected}
    labels=read_csv(META/'answer_labels.csv');splits=read_csv(META/'sheet_splits.csv')
    test={r['sheet_id'] for r in splits if r['split']=='test'}
    assert len(test)==39
    text=(META/'answer_review.html').read_text(encoding='utf-8')
    pattern=r'(<script id="annotation-data" type="application/json">)(.*?)(</script>)'
    data=json.loads(re.search(pattern,text,re.S).group(2));saved=json.loads(BACKUP.read_text(encoding='utf-8-sig'))
    assert saved['fingerprint']==data['fingerprint']
    checked=Counter(r['sheet_id'] for r in labels if r['ground_truth'].strip())
    original_complete={s for s in test if checked[s]==100}
    assert len(original_complete)==10
    remaining=test-original_complete
    out=[];provenance=[];bulk_keys=[];answer_meta={}
    for row in labels:
        sid=row['sheet_id']
        if sid not in test:continue
        q=int(row['question_no']);key=f'{sid}:{q}';existing=row['ground_truth'].strip()
        draft=saved['answers'].get(key,'').strip()
        is_bulk=not existing and sid in remaining and bool(draft)
        answer=existing or (draft if is_bulk else '')
        assert answer in {'','1','2','3','4','5','blank','multiple','ambiguous'}
        out.append({'sheet_id':sid,'question_no':q,'ground_truth':answer})
        method='user_bulk_confirmation' if is_bulk else 'previously_confirmed' if existing else 'unanswered'
        original=deepcopy(saved.get('answerMeta',{}).get(key,{}))
        provenance.append({'sheet_id':sid,'question_no':q,'answer':answer,'status':'human_verified' if answer else 'unanswered',
            'confirmation_method':method,'individual_visual_inspection_recorded':False if is_bulk else None,
            'original_answer_metadata':original,'eligible_for_independent_accuracy':False})
        if answer:
            answer_meta[key]={**original,'mark':answer,'source':'human' if is_bulk else original.get('source','official'),
                'verified':True,'via':'user_bulk_confirmation' if is_bulk else original.get('via','official'),
                'confirmation_method':method,'dataset_version':2}
        if is_bulk:bulk_keys.append(key)
    assert len(out)==3900 and len(bulk_keys)==2402
    assert sum(bool(r['ground_truth']) for r in out)==3531
    inventory=[r for r in read_csv(META/'image_inventory_verified.csv') if r['sheet_id'] in test and r['pair_status']=='verified']
    assert len(inventory)==78 and all(sorted(r['capture_role'] for r in inventory if r['sheet_id']==s)==['A','B'] for s in test)
    data=deepcopy(data);data['sheets']=[s for s in data['sheets'] if s['id'] in test]
    data['initial']={f"{r['sheet_id']}:{r['question_no']}":r['ground_truth'] for r in out}
    # Include explicit empty answers so previous confidence rules cannot silently fill the 369 missing slots.
    data['fingerprint']=hashlib.sha256(json.dumps({'dataset_version':2,'sheets':data['sheets']},sort_keys=True).encode()).hexdigest()[:16]
    data['dataset_version']=2;data['corrections']=[];data['drafts']={'answers':{},'sheets':{}}
    data['pairing_holds']={};data['pairing_migrations']=[];data['risk_review']=None
    data['repair_sheet']='';data['repair_url']=''
    def wanted(k):return k.split(':')[0] in test
    pilot=data['pilot'];pilot['sheets']={s:v for s,v in pilot['sheets'].items() if s in test};pilot['sheet_ids']=sorted(test)
    pilot['batches']=[{**b,'sheet_ids':[s for s in b['sheet_ids'] if s in test]} for b in pilot['batches'] if any(s in test for s in b['sheet_ids'])]
    pilot['active_batch']=pilot['batches'][0]['id']
    data['assistance']['items']={k:v for k,v in data['assistance']['items'].items() if wanted(k)}
    data['assistance']['queue']=[r for r in data['assistance']['queue'] if wanted(r['key'])]
    data['assistance']['start']=min(test)
    if data.get('draft_supplement'):
        data['draft_supplement']['items']={k:v for k,v in data['draft_supplement']['items'].items() if wanted(k)}
    def rebase(node):
        if isinstance(node,dict):
            for k,v in node.items():
                if k in {'url','sprite','overlay','thumbnail_a','thumbnail_b','A','B'} and isinstance(v,str) and v and not urlparse(v).scheme:
                    target=(META/unquote(v)).resolve()
                    node[k]=quote(Path(os.path.relpath(target,DEST)).as_posix(),safe='/')
                else:rebase(v)
        elif isinstance(node,list):
            for v in node:rebase(v)
    rebase(data)
    for s in data['sheets']:
        for role in ['A','B']:assert (DEST/unquote(s[role]['url'])).resolve().is_file()
    data['confirmation_metadata']=answer_meta
    completed={s:True for s in test if sum(bool(r['ground_truth']) for r in out if r['sheet_id']==s)==100}
    data['initial_reviewed']=completed
    payload=json.dumps(data,ensure_ascii=False).replace('</','<\\/')
    html=re.sub(pattern,lambda m:m.group(1)+payload+m.group(3),text,count=1,flags=re.S)
    seed="""installAssistance();
if(!state.datasetV2ConfirmationApplied){
 for(const [k,m] of Object.entries(DATA.confirmation_metadata||{})){
  if(state.answers[k]===m.mark && (!state.answerMeta[k]?.verified || state.answerMeta[k]?.via==='official'))state.answerMeta[k]={...m};
 }
 for(const s of Object.keys(DATA.initial_reviewed||{}))if(count(s)===100)state.reviewed[s]=true;
 state.datasetV2ConfirmationApplied=true;
}
state.datasetVersion=2;"""
    assert html.count('installAssistance();')==1
    html=html.replace('installAssistance();',seed)
    html=html.replace('<title>','<title>ชุดข้อมูลที่ 2 · ',1)
    DEST.mkdir(parents=True)
    write_csv(DEST/'answer_labels.csv',out,['sheet_id','question_no','ground_truth'])
    write_csv(DEST/'sheet_splits.csv',[r for r in splits if r['sheet_id'] in test],list(splits[0]))
    write_csv(DEST/'image_inventory_verified.csv',inventory,list(inventory[0]))
    write_json(DEST/'label_provenance.json',provenance)
    write_json(DEST/'answer_review_backup_dataset2.json',{'version':1,'fingerprint':data['fingerprint'],'answers':data['initial'],
        'answerMeta':answer_meta,'reviewed':completed,'sheet':min(test),'question':1,'assistanceInitialized':True,
        'datasetVersion':2,'datasetV2ConfirmationApplied':True})
    (DEST/'answer_review.html').write_text(html,encoding='utf-8')
    manifest={'dataset_version':2,'created_at':datetime.now(ZoneInfo('Asia/Bangkok')).isoformat(),
        'scope':'All existing 39 Test sheets, including the previous 10-sheet evaluation cohort.',
        'sheet_ids':sorted(test),'sheet_count':39,'image_count':78,'question_slots':3900,
        'previously_confirmed':1129,'user_bulk_confirmed':2402,'confirmed_total':3531,'unanswered':369,
        'fully_answered_sheets':len(completed),'new_training_run':False,'all_splits':'test',
        'source_image_root':'../..','source_images_copied':False,'dataset1_unchanged':True,
        'independent_evaluation':False,'prior_evaluation_sheet_overlap':sorted(original_complete),
        'bulk_confirmation_note':'User explicitly requested the normal human-verified status. Confirmation was performed in bulk; per-question visual inspection is not asserted.',
        'bulk_question_keys':bulk_keys,'source_sha256':before,'browser_fingerprint':data['fingerprint']}
    write_json(DEST/'manifest.json',manifest)
    (DEST/'README.md').write_text('''# ชุดข้อมูลที่ 2: Test 39 แผ่น

ชุดนี้แยกไฟล์คำตอบและหน้าตรวจจากชุดข้อมูลที่ 1 ไม่เปลี่ยนไฟล์เดิมหรือโมเดลเดิม
มี 39 แผ่น 78 ภาพ 3,900 ข้อ ทุกแผ่นคง split เป็น test
ไฟล์ภาพอ้างถึงต้นฉบับในโปรเจกต์ตาม image_inventory_verified.csv ไม่ได้ทำสำเนาภาพเพิ่ม
เปิด answer_review.html เพื่อตรวจชุดนี้ มีพื้นที่บันทึกในเบราว์เซอร์แยกจากชุดที่ 1

สถานะคนตรวจแล้วรวม 3,531 ข้อ: เดิมยืนยัน 1,129 ข้อ และผู้ใช้รับร่างเป็นกลุ่ม 2,402 ข้อ
เหลือว่าง 369 ข้อ มีคำตอบครบ 100 ข้อจำนวน 19 แผ่น
ประวัติรายข้ออยู่ใน label_provenance.json และไฟล์สำรอง answer_review_backup_dataset2.json
การรับร่างเป็นกลุ่มไม่ได้บันทึกว่ามีการตรวจเทียบภาพรายข้อ

ชุดนี้รวม 10 แผ่นที่เคยประเมินแล้ว และมีคำตอบจากโมเดลที่ผู้ใช้รับเป็นกลุ่ม
จึงไม่ใช่ชุดทดสอบอิสระใหม่ การแยกโฟลเดอร์ไม่ลบความซ้ำของภาพหรือทำให้คำตอบเป็นการตรวจอิสระ
ไม่ควรนำความตรงกันกับคำตอบรับร่างมาอ้างเป็นความแม่นยำอิสระ
ไม่มีการนำคำตอบชุดนี้ไปฝึกโมเดลหรือเขียนทับผลประเมินเก่าในขั้นตอนนี้
''',encoding='utf-8')
    after={str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p):sha(p) for p in protected}
    assert before==after,'Dataset 1 or source/model files changed during snapshot creation.'
    print(json.dumps({k:v for k,v in manifest.items() if k in ['dataset_version','sheet_count','image_count','question_slots','previously_confirmed','user_bulk_confirmed','confirmed_total','unanswered','fully_answered_sheets','dataset1_unchanged']},ensure_ascii=False))

if __name__=='__main__':main()

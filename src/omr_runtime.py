"""Application policies shared by local UI and dataset tests; no label-table writes."""
import csv
import io
import re

from omr_inference import combine_readings

ANSWERS = {'1','2','3','4','5','blank','multiple','ambiguous'}


def cla_reading(capture, config):
    if capture is None:
        return None
    predictions,confidence=[],[]
    fill=config['cla_fill_threshold'];margin=config['cla_margin_threshold']
    for scores in capture['cla_scores']:
        order=sorted(range(5),key=lambda i:scores[i],reverse=True)
        active=[i for i,s in enumerate(scores) if s>=fill]
        gap=scores[order[0]]-scores[order[1]]
        if not active:answer='blank';score=max(0.,fill-scores[order[0]])
        elif len(active)>1:answer='multiple';score=scores[order[1]]-fill
        elif gap<margin:answer='ambiguous';score=gap
        else:answer=str(order[0]+1);score=gap
        predictions.append(answer);confidence.append(float(score))
    return {'predictions':predictions,'confidence':confidence}


def pair_consistency(a,b,cutoff):
    """Flag large answer-pattern conflicts; this is a heuristic, not identity proof."""
    if a is None or b is None:
        return {'status':'unavailable','comparable':0,'conflicts':0,'blocked':False}
    comparisons=[(ap,bp) for ap,ac,bp,bc in zip(a['predictions'],a['confidence'],b['predictions'],b['confidence'])
        if ap in '12345' and len(ap)==1 and bp in '12345' and len(bp)==1 and ac>=cutoff and bc>=cutoff]
    conflicts=sum(ap!=bp for ap,bp in comparisons)
    blocked=len(comparisons)>=30 and conflicts>=8 and conflicts/len(comparisons)>.15
    return {'status':'suspected_mismatch' if blocked else 'no_large_conflict' if len(comparisons)>=30 else 'insufficient_evidence',
        'comparable':len(comparisons),'conflicts':conflicts,'blocked':blocked,
        'policy':'heuristic: >=30 comparable, >=8 conflicts and >15% conflicts'}


def cla_workflow(a,b,sheet_id):
    rows=[]
    for i in range(100):
        ap=a['predictions'][i] if a else '';bp=b['predictions'][i] if b else ''
        ac=float(a['confidence'][i]) if a else 0.;bc=float(b['confidence'][i]) if b else 0.
        used_b=bool(b and (not a or ap in {'blank','multiple','ambiguous'}))
        answer=bp if used_b else ap or 'ambiguous'
        reasons=[]
        if not a and not b:answer='';reasons.append('registration_failed')
        elif answer in {'blank','multiple','ambiguous'}:reasons.append('special_or_uncertain_mark')
        if ap in {'1','2','3','4','5'} and bp in {'1','2','3','4','5'} and ap!=bp:
            reasons.append('ab_disagree')
        rows.append({'sheet_id':sheet_id,'question_no':i+1,'proposed_answer':answer,
            'a_prediction':ap,'a_confidence':ac,'b_prediction':bp,'b_confidence':bc,
            'selected_confidence':bc if used_b else ac,'used_B':used_b,'needs_review':bool(reasons),
            'review_reasons':';'.join(reasons),'label_status':'model_draft' if answer else 'registration_failed',
            'reviewed_by_human':False})
    return rows


def build_methods(a,b,config,sheet_id,block_mismatch=True):
    check=pair_consistency(a,b,config['cnn_confidence_cutoff'])
    safe_b=None if block_mismatch and check['blocked'] else b
    methods={'cnn':combine_readings(a,safe_b,config['cnn_confidence_cutoff'],sheet_id),
        'cla':cla_workflow(cla_reading(a,config),cla_reading(safe_b,config),sheet_id)}
    return methods,check


def validate_decisions(decisions):
    if not isinstance(decisions,list) or len(decisions)>100:
        raise ValueError('รายการตรวจต้องมีไม่เกิน 100 ข้อ')
    result={}
    for row in decisions:
        q=row.get('question_no');answer=row.get('answer')
        if type(q) is not int or not 1<=q<=100 or str(q) in result or answer not in ANSWERS:
            raise ValueError('หมายเลขข้อหรือคำตอบไม่ถูกต้อง')
        if row.get('reviewed') is not True:
            raise ValueError('การบันทึกยืนยันต้องเกิดจากผู้ตรวจ')
        result[str(q)]={'answer':answer,'reviewed':True}
    return result


def effective_rows(rows,reviews):
    output=[]
    for raw in rows:
        reviewed=reviews.get(str(raw['question_no']))
        row={**raw,'model_answer':raw['proposed_answer'],'final_answer':reviewed['answer'] if reviewed else raw['proposed_answer'],
            'reviewed_by_human':bool(reviewed),'label_status':'human_reviewed_app_result' if reviewed else raw['label_status']}
        row['unresolved']=row['final_answer'] not in {'1','2','3','4','5','blank','multiple'} or bool(raw['needs_review'] and not reviewed)
        output.append(row)
    return output


def parse_exam_key(mode,text=''):
    if mode=='demo':
        return [str(i%5+1) for i in range(100)]
    if mode!='custom':raise ValueError('เลือกเฉลยตัวอย่างหรือเฉลยที่กรอกเอง')
    text=text.strip().lstrip('\ufeff')
    if text.startswith('question_no,answer'):
        data=list(csv.DictReader(io.StringIO(text)))
        if len(data)!=100:raise ValueError('เฉลย CSV ต้องมี 100 ข้อ')
        values={}
        for row in data:
            try:q=int(row['question_no'])
            except (ValueError,KeyError):raise ValueError('หมายเลขข้อในเฉลยไม่ถูกต้อง')
            if q in values or not 1<=q<=100:raise ValueError('เฉลยมีหมายเลขข้อซ้ำหรือเกิน 1–100')
            values[q]=row.get('answer','').strip()
        key=[values[i] for i in range(1,101)]
    else:key=[v for v in re.split(r'[\s,;]+',text) if v]
    if len(key)!=100 or any(k not in {'1','2','3','4','5'} for k in key):
        raise ValueError('เฉลยต้องมี 100 คำตอบ และใช้ตัวเลือก 1–5 เท่านั้น')
    return key


def grade(rows,key,key_source):
    if len(rows)!=100 or len(key)!=100:raise ValueError('ต้องมีคำตอบและเฉลยครบ 100 ข้อ')
    unresolved=sum(r['unresolved'] for r in rows)
    correct=sum(not r['unresolved'] and r['final_answer']==key[r['question_no']-1] for r in rows)
    return {'correct':correct,'unresolved':unresolved,'incorrect':100-correct-unresolved,'total':100,
        'score_min':correct,'score_max':correct+unresolved,'status':'provisional' if unresolved else 'automatic_result',
        'key_source':key_source,'demo':key_source=='demo'}


def export_csv(rows,method,grading=None):
    key=grading.get('key') if grading else None
    output=io.StringIO(newline='')
    fields=['question_no','method','model_answer','final_answer','reviewed_by_human','label_status',
        'unresolved','a_prediction','b_prediction','used_B','selected_confidence','review_reasons','exam_key_source','exam_key','correct']
    writer=csv.DictWriter(output,fieldnames=fields);writer.writeheader()
    for r in rows:
        writer.writerow({**{k:r[k] for k in fields if k in r},'method':method,
            'exam_key_source':grading['source'] if grading else '',
            'exam_key':key[r['question_no']-1] if key else '',
            'correct':r['final_answer']==key[r['question_no']-1] if key and not r['unresolved'] else ''})
    return ('\ufeff'+output.getvalue()).encode('utf-8')

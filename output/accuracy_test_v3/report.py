"""Re-evaluate confirmed Test rows using the frozen v3 model; no training or label writes."""
import csv, hashlib, json, sys
from pathlib import Path
from collections import Counter, defaultdict
import numpy as np
import torch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from omr_model import load_trained_model
from omr_retrain_v3 import evaluate

def main():
    work=ROOT/'presentation_build/retraining_v3_20261028'
    model_dir=ROOT/'models/retrained_v3_verified'
    config=json.loads((model_dir/'model_config.json').read_text(encoding='utf8'))
    selection=json.loads((work/'verified_only/selection.json').read_text(encoding='utf8'))
    source=work/'input/confirmed_rows.npz'
    if hashlib.sha256(source.read_bytes()).hexdigest()!=selection['data_sha256']:
        raise SystemExit('ERROR: test input differs from frozen selection')
    with np.load(source,allow_pickle=False) as archive:data={k:archive[k] for k in archive.files}
    indices=np.flatnonzero(data['split']=='test')
    torch.set_num_threads(2)
    model,device=load_trained_model(model_dir/'row_cnn.pt','cpu',config['weights_sha256'])
    summary,rows=evaluate(model,data,indices,device,config['cnn_confidence_cutoff'])
    target=summary['A_then_B']
    saved=json.loads((work/'verified_only/evaluation.json').read_text(encoding='utf8'))['results']['all_confirmed_test']['selected']['A_then_B']
    if target!=saved:raise SystemExit('ERROR: result differs from recorded evaluation')
    per=defaultdict(Counter)
    for r in rows:
        c=per[int(r['question_no'])]; c['total']+=1
        if r['a_then_b_deferred']:c['review']+=1
        elif r['a_then_b']==r['ground_truth']:c['correct']+=1
        else:c['wrong']+=1
    out=Path(__file__).parent/'accuracy_by_question.csv'
    with out.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['question_no','confirmed_answers','correct_accepted','wrong_accepted','needs_review','accuracy_percent_including_review'])
        for q in range(1,101):
            c=per[q];n=c['total'];w.writerow([q,n,c['correct'],c['wrong'],c['review'],f"{100*c['correct']/n:.2f}" if n else ''])
    print('CNN v3  |  A-then-B  |  Confirmed Test answers')
    print('='*83)
    print(f"OVERALL: {target['correct_accepted']}/{target['questions']} = {100*target['correct_accepted']/target['questions']:.2f}%")
    print(f"Correct: {target['correct_accepted']}    Wrong accepted: {target['wrong_accepted']}    Needs review: {target['deferred']}")
    print('Per-question accuracy: correct/confirmed (review included in denominator)')
    print('-'*83)
    for start in range(1,101,5):
        parts=[]
        for q in range(start,start+5):
            c=per[q]; n=c['total']; value=f"{100*c['correct']/n:5.1f}%" if n else '  N/A '
            parts.append(f"{q:03} {c['correct']:02}/{n:02} {value}")
        print(' | '.join(parts))
    print('-'*83)
    print('Assisted development retest; not independent. No sheet-level A/B gate.')
    print('CSV: output/accuracy_test_v3/accuracy_by_question.csv')
if __name__=='__main__':main()

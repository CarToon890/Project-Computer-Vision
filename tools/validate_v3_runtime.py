"""Check a frozen candidate on Validation using complete sheets and production policies."""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from omr_batch import read_capture
from omr_model import load_trained_model
from omr_runtime import build_methods,effective_rows
from omr_retrain_v3 import admissible,rank


def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def evaluate(captures,truth,config):
    result={m:{'questions':0,'correct_accepted':0,'wrong_accepted':0,'deferred':0} for m in ('A_only','A_then_B')}
    for sid,labels in truth.items():
        a,b=captures[(sid,'A')],captures[(sid,'B')]
        for mode,second in [('A_only',None),('A_then_B',b)]:
            methods,_=build_methods(a,second,config,sid)
            for row in effective_rows(methods['cnn'],{}):
                if row['question_no'] not in labels:continue
                output=result[mode];output['questions']+=1;output['deferred']+=int(row['unresolved'])
                if not row['unresolved']:
                    output['correct_accepted']+=int(row['final_answer']==labels[row['question_no']])
                    output['wrong_accepted']+=int(row['final_answer']!=labels[row['question_no']])
    return result


def main():
    work=ROOT/'presentation_build/retraining_v3_20261028';out=work/'runtime_validation.json'
    if out.exists():raise SystemExit('Existing runtime validation preserved')
    policy=json.loads((work/'validation_gate_policy.json').read_text(encoding='utf-8'))
    if not policy['frozen_before_test']:raise ValueError('Validation gate not predeclared')
    selection=json.loads((work/'verified_only/selection.json').read_text(encoding='utf-8'))
    if selection['selected_epoch']==0:raise SystemExit('No candidate selected')
    meta=ROOT/'data/metadata';splits={r['sheet_id']:r['split'] for r in read(meta/'sheet_splits.csv')}
    truth=defaultdict(dict)
    for r in read(meta/'answer_labels.csv'):
        if splits.get(r['sheet_id'])=='validation' and r['ground_truth'].strip():truth[r['sheet_id']][int(r['question_no'])]=r['ground_truth'].strip()
    if sum(map(len,truth.values()))!=selection['baseline_validation']['A_only']['questions']:raise ValueError('Validation cohort changed')
    inventory=[r for r in read(meta/'image_inventory_verified.csv') if r['sheet_id'] in truth and r['pair_status']=='verified']
    if len(inventory)!=2*len(truth):raise ValueError('Validation image pairs incomplete')
    conv={r['source_relative_path']:r['normalized_relative_path'] for r in read(meta/'heic_conversion_map.csv')}
    folder=ROOT/'models/retrained_v2_perspective';config=json.loads((folder/'model_config.json').read_text(encoding='utf-8'))
    cv2.setNumThreads(2);torch.set_num_threads(2)
    baseline,device=load_trained_model(folder/'row_cnn.pt',expected_sha256=config['weights_sha256'])
    candidate,_=load_trained_model(work/'verified_only/candidate.pt',device=device)
    captures={'v2':{},'candidate':{}}
    for n,image in enumerate(inventory,1):
        key=(image['sheet_id'],image['capture_role'])
        for name,model in [('v2',baseline),('candidate',candidate)]:
            captures[name][key]=read_capture(image,model,device,conv,ROOT/'presentation_build/registered_row_cache',config['geometry_sha256'])
        if n%20==0 or n==len(inventory):print(f'Validation runtime images {n}/{len(inventory)}',flush=True)
    base=evaluate(captures['v2'],truth,config);chosen=evaluate(captures['candidate'],truth,config)
    promote=admissible(chosen,base) and rank(chosen)>rank(base)
    result={'gate_predeclared_before_test':True,'test_used_for_runtime_gate':False,'selected_epoch':selection['selected_epoch'],
            'baseline':base,'candidate':chosen,'activate_candidate':promote,
            'scope':'All confirmed Validation questions, full-sheet A/B predictions, production pair mismatch gate.',
            'caution':'Human-inspected model-assisted Validation; not independent.'}
    out.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()

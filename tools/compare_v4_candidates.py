"""Freeze the v4 choice on full-sheet Validation before candidate Test evaluation."""
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import torch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tools'))
from omr_batch import read_capture
from omr_model import load_trained_model
from omr_retrain import sha
from omr_retrain_v3 import admissible,rank
from validate_v3_runtime import read,evaluate


def main():
    candidates={'verified_only':ROOT/'presentation_build/retraining_v4_verified_20261028',
                'verified_long':ROOT/'presentation_build/retraining_v4_verified_long_20261028',
                'mixed_pseudo':ROOT/'presentation_build/retraining_v4_20261028'}
    out=ROOT/'presentation_build/v4_comparison_retry_20261028';target=out/'selection.json'
    if target.exists():raise SystemExit('Frozen selection already exists')
    selections={name:json.loads((path/'selection.json').read_text(encoding='utf-8')) for name,path in candidates.items()}
    if any(x['test_used_for_selection'] for x in selections.values()):raise ValueError('Candidate selection used Test')
    meta=ROOT/'data/metadata'
    for sel in selections.values():
        for name in ('answer_labels.csv','sheet_splits.csv','image_inventory_verified.csv'):
            rel=str((meta/name).relative_to(ROOT))
            if sha(meta/name)!=sel['source_sha256'][rel]:raise ValueError('Validation data changed: '+name)
    available=[name for name,sel in selections.items() if sel['selected_epoch']]
    if not available:
        decision={'selected_model':'v3','reason':'Neither candidate improved the predeclared Validation objective',
                  'test_used_for_selection':False,'candidate_selections':selections}
    else:
        splits={r['sheet_id']:r['split'] for r in read(meta/'sheet_splits.csv')};truth=defaultdict(dict)
        for r in read(meta/'answer_labels.csv'):
            if splits.get(r['sheet_id'])=='validation' and r['ground_truth'].strip():truth[r['sheet_id']][int(r['question_no'])]=r['ground_truth'].strip()
        if any(sum(map(len,truth.values()))!=s['baseline_validation']['A_only']['questions'] for s in selections.values()):raise ValueError('Validation cohort changed')
        inventory=[r for r in read(meta/'image_inventory_verified.csv') if r['sheet_id'] in truth and r['pair_status']=='verified']
        if len(inventory)!=2*len(truth):raise ValueError('Validation image pairs incomplete')
        conv={r['source_relative_path']:r['normalized_relative_path'] for r in read(meta/'heic_conversion_map.csv')}
        model_dir=ROOT/'models/retrained_v3_verified';cfg=json.loads((model_dir/'model_config.json').read_text(encoding='utf-8'))
        torch.set_num_threads(2);cv2.setNumThreads(2)
        baseline,device=load_trained_model(model_dir/'row_cnn.pt',expected_sha256=cfg['weights_sha256'])
        models={'v3':baseline}
        for name in available:models[name]=load_trained_model(candidates[name]/'candidate.pt',device=device)[0]
        captures={name:{} for name in models}
        for n,image in enumerate(inventory,1):
            key=(image['sheet_id'],image['capture_role'])
            for name,model in models.items():captures[name][key]=read_capture(image,model,device,conv,ROOT/'presentation_build/registered_row_cache',cfg['geometry_sha256'])
            if n%20==0 or n==len(inventory):print(f'Runtime Validation images {n}/{len(inventory)}',flush=True)
        metrics={name:evaluate(capture,truth,cfg) for name,capture in captures.items()}
        eligible=[name for name in available if admissible(metrics[name],metrics['v3']) and rank(metrics[name])>rank(metrics['v3'])]
        # Stable order prefers the verified-only candidate when scores are identical.
        chosen=max(eligible,key=lambda name:(rank(metrics[name]),name!='mixed_pseudo',name=='verified_only')) if eligible else 'v3'
        decision={'selected_model':chosen,'reason':'Full-sheet Validation, risk-first predeclared gate',
                  'test_used_for_selection':False,'metrics':metrics,'candidate_selections':selections,
                  'policy':'No increased accepted errors in either workflow; max 5% extra deferrals; minimize combined errors then deferrals; ties prefer verified-only',
                  'scope':'All confirmed Validation questions, complete A/B and production pair gate; assisted development data'}
    decision['selection_sha256']={name:sha(path/'selection.json') for name,path in candidates.items()}
    decision['candidate_sha256']={name:sha(path/'candidate.pt') for name,path in candidates.items() if selections[name]['selected_epoch']}
    out.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(decision,indent=2),encoding='utf-8')
    print(json.dumps(decision,indent=2),flush=True)


if __name__=='__main__':main()

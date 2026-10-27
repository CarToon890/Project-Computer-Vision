"""Evaluate frozen v4 candidates on assisted Test without changing the choice."""
import json
import sys
from collections import Counter,defaultdict
from pathlib import Path

import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from omr_model import CLASSES,load_trained_model
from omr_retrain import sha
from omr_retrain_v3 import evaluate


def classes(rows):
    result=defaultdict(Counter)
    for row in rows:
        c=result[row['ground_truth']];c['support']+=1;c['deferred']+=int(row['a_then_b_deferred'])
        if not row['a_then_b_deferred']:
            c['correct_accepted']+=int(row['a_then_b']==row['ground_truth'])
            c['wrong_accepted']+=int(row['a_then_b']!=row['ground_truth'])
    return {name:{field:result[name][field] for field in ('support','correct_accepted','wrong_accepted','deferred')} for name in CLASSES}


def main():
    work=ROOT/'presentation_build/v4_comparison_retry_20261028';selection_path=work/'selection.json';out=work/'test_evaluation.json'
    if out.exists():raise SystemExit('Existing Test report preserved')
    selection=json.loads(selection_path.read_text(encoding='utf-8'))
    if selection['test_used_for_selection']:raise ValueError('Selection was not frozen before Test')
    folders={'verified_only':ROOT/'presentation_build/retraining_v4_verified_20261028',
             'verified_long':ROOT/'presentation_build/retraining_v4_verified_long_20261028',
             'mixed_pseudo':ROOT/'presentation_build/retraining_v4_20261028'}
    for name,folder in folders.items():
        if sha(folder/'selection.json')!=selection['selection_sha256'][name]:raise ValueError('Candidate selection changed')
        if name in selection['candidate_sha256'] and sha(folder/'candidate.pt')!=selection['candidate_sha256'][name]:raise ValueError('Candidate weights changed')
    package=ROOT/'presentation_build/retraining_v3_20261028/input/confirmed_rows.npz'
    if any(sha(package)!=sel['confirmed_package_sha256'] for sel in selection['candidate_selections'].values()):raise ValueError('Confirmed package differs')
    with np.load(package,allow_pickle=False) as z:data={k:z[k] for k in z.files}
    preflight=json.loads((package.parent/'preflight.json').read_text(encoding='utf-8'))
    folder=ROOT/'models/retrained_v3_verified';cfg=json.loads((folder/'model_config.json').read_text(encoding='utf-8'))
    torch.set_num_threads(2);base,device=load_trained_model(folder/'row_cnn.pt',expected_sha256=cfg['weights_sha256'])
    models={'v3':base}
    for name in selection['candidate_sha256']:models[name]=load_trained_model(folders[name]/'candidate.pt',device=device)[0]
    results={};by_class={}
    for cohort,idx in [('all_confirmed_test',np.flatnonzero(data['split']=='test')),
                       ('frozen_ten_sheets',np.flatnonzero((data['split']=='test') & np.isin(data['sheet_id'],preflight['frozen_test_sheets'])) )]:
        results[cohort]={}
        for name,model in models.items():
            metrics,rows=evaluate(model,data,idx,device,cfg['cnn_confidence_cutoff']);results[cohort][name]=metrics
            if cohort=='all_confirmed_test':by_class[name]=classes(rows)
    result={'independent_evaluation':False,'type':'assisted development retest','selection_sha256':sha(selection_path),
            'results':results,'test_by_class_a_then_b':by_class,
            'note':'Per-question A/B policy; full-sheet pair mismatch gate not applied. Test never used for model selection.'}
    out.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()

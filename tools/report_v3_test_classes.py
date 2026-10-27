"""Report class support and review/error counts after the v3 selection is frozen."""
import json
import sys
from collections import Counter,defaultdict
from pathlib import Path

import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from omr_model import CLASSES,load_trained_model
from omr_retrain_v3 import evaluate
from omr_retrain import sha


def main():
    work=ROOT/'presentation_build/retraining_v3_20261028';selection=work/'verified_only/selection.json'
    if not selection.is_file():raise ValueError('Selection must be frozen first')
    decision=json.loads(selection.read_text(encoding='utf-8'));folder=ROOT/'models/retrained_v2_perspective'
    config=json.loads((folder/'model_config.json').read_text(encoding='utf-8'))
    data_file=work/'input/confirmed_rows.npz'
    if sha(data_file)!=decision['data_sha256']:raise ValueError('Dataset differs from frozen selection')
    with np.load(data_file,allow_pickle=False) as archive:data={k:archive[k] for k in archive.files}
    test=np.flatnonzero(data['split']=='test');torch.set_num_threads(2)
    base,device=load_trained_model(folder/'row_cnn.pt',expected_sha256=config['weights_sha256'])
    candidate=base if not decision['selected_epoch'] else load_trained_model(work/'verified_only/candidate.pt',device=device)[0]
    result={}
    for name,model in [('v2',base),('selected',candidate)]:
        _,rows=evaluate(model,data,test,device,config['cnn_confidence_cutoff'])
        classes=defaultdict(Counter)
        for r in rows:
            c=classes[r['ground_truth']];c['support']+=1
            c['deferred']+=int(r['a_then_b_deferred'])
            if not r['a_then_b_deferred']:
                c['accepted_correct']+=int(r['a_then_b']==r['ground_truth'])
                c['accepted_wrong']+=int(r['a_then_b']!=r['ground_truth'])
        result[name]={k:{field:classes[k][field] for field in ('support','accepted_correct','accepted_wrong','deferred')} for k in CLASSES}
    output={'selection_sha256':sha(selection),'independent_evaluation':False,
            'note':'All confirmed Test questions, A/B per-question policy; sheet-level gate not applied. Sparse classes do not establish reliability.',
            'results':result}
    target=work/'test_class_diagnostics.json'
    if target.exists():raise ValueError('Existing report preserved')
    target.write_text(json.dumps(output,indent=2),encoding='utf-8');print(json.dumps(output,indent=2))


if __name__=='__main__':main()

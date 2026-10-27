"""Train v4 experimentally with confirmed labels and conservative Train-only pseudo labels."""
import copy
import csv
import hashlib
import json
import math
import random
import time
from collections import Counter,defaultdict
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader,TensorDataset
from omr_model import CLASSES,load_trained_model,predict_cnn
from omr_retrain import augment_train,sha,validate_rows
from omr_retrain_v3 import evaluate,admissible,rank

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'presentation_build/retraining_v4_20261028'


def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def pseudo_candidates(risk,labels,splits):
    result={}
    for key,item in risk['items'].items():
        sid,qtext=key.split(':');q=int(qtext)
        if (sid,q) in labels or splits.get(sid)!='train' or item.get('split')!='train':continue
        if item.get('audit_sample') or item.get('group')!='agreement':continue
        if item.get('proposal') not in {'1','2','3','4','5'}:continue
        if any(item.get(k)!=item['proposal'] for k in ('cnn_a','cnn_b','cla_a','cla_b')):continue
        if any(not isinstance(item.get(k),(int,float)) or not math.isfinite(item[k]) or not .99<=item[k]<=1 for k in ('confidence_a','confidence_b')):continue
        result[(sid,q)]=item['proposal']
    return result


def load_pseudo_crops(risk,labels,splits,model,device,geometry):
    candidates=pseudo_candidates(risk,labels,splits)
    groups=defaultdict(dict)
    for (sid,q),answer in candidates.items():groups[sid][q]=answer
    inventory=read(ROOT/'data/metadata/image_inventory_verified.csv')
    images={(r['sheet_id'],r['capture_role']):r for r in inventory if r['pair_status']=='verified'}
    conv={r['source_relative_path']:r['normalized_relative_path'] for r in read(ROOT/'data/metadata/heic_conversion_map.csv')}
    cache=ROOT/'presentation_build/registered_row_cache';crops=[];targets=[];provenance=[]
    for n,(sid,qs) in enumerate(sorted(groups.items()),1):
        both=[]
        for role in ('A','B'):
            r=images[(sid,role)];source=ROOT/r['relative_path'];normalized=ROOT/conv.get(Path(r['relative_path']).as_posix(),r['relative_path'])
            source_sha,normalized_sha=sha(source),sha(normalized)
            fp=hashlib.sha256((source_sha+normalized_sha+geometry).encode()).hexdigest()
            path=cache/f'{sid}_{role}_{fp[:20]}.npz';info=path.with_suffix('.json')
            if not path.exists() or not info.exists():raise ValueError('Missing registered image cache for '+sid+' '+role)
            metadata=json.loads(info.read_text(encoding='utf-8'))
            if (metadata['source_sha256'],metadata['normalized_sha256'],metadata['geometry_hash'])!=(source_sha,normalized_sha,geometry):raise ValueError('Registered cache provenance mismatch')
            with np.load(path,allow_pickle=False) as z:
                arr=z['crops']
                if arr.shape!=(100,32,160) or arr.dtype!=np.uint8:raise ValueError('Invalid row cache')
                both.append(arr.copy())
        ordered=sorted(qs); stacked=np.stack([both[role][q-1] for q in ordered for role in range(2)])
        indices,confidence=predict_cnn(model,stacked,device)
        for i,q in enumerate(ordered):
            expected=CLASSES.index(qs[q])
            if all(int(indices[2*i+r])==expected and float(confidence[2*i+r])>=.99 for r in range(2)):
                crops.extend((stacked[2*i],stacked[2*i+1]));targets.extend((expected,expected));provenance.append((sid,q,qs[q]))
        if n%25==0 or n==len(groups):print(f'Pseudo-label Train sheets {n}/{len(groups)}; selected questions {len(provenance)}',flush=True)
    if not crops:raise ValueError('No eligible pseudo labels')
    return np.stack(crops),np.asarray(targets,dtype=np.int64),provenance,len(candidates)


def main():
    if WORK.exists():raise ValueError('Use a new experiment directory; existing work is preserved')
    WORK.mkdir(parents=True)
    source=ROOT/'presentation_build/retraining_v3_20261028/input';report=json.loads((source/'preflight.json').read_text(encoding='utf-8'))
    package=source/'confirmed_rows.npz'
    if sha(package)!=report['package_sha256']['confirmed_rows.npz']:raise ValueError('Confirmed package changed')
    with np.load(package,allow_pickle=False) as z:data={k:z[k] for k in z.files}
    validate_rows(data,report)
    meta=ROOT/'data/metadata';risk_file=ROOT/'presentation_build/risk_review_20261027_v3/risk_review.json'
    risk=json.loads(risk_file.read_text(encoding='utf-8'))
    protected=[meta/'answer_labels.csv',meta/'sheet_splits.csv',meta/'image_inventory_verified.csv',
               ROOT/'models/retrained_v3_verified/row_cnn.pt',ROOT/'models/retrained_v3_verified/model_config.json',risk_file]
    source_hashes={str(p.relative_to(ROOT)):sha(p) for p in protected}
    for name in ('answer_labels.csv','sheet_splits.csv','image_inventory_verified.csv'):
        if source_hashes[str((meta/name).relative_to(ROOT))]!=report['source_sha256']['data/metadata/'+name]:raise ValueError('Confirmed labels, split or inventory changed since v3 preparation')
    for name in ('sheet_splits.csv','image_inventory_verified.csv'):
        if risk['source_sha256'].get(str(Path('data/metadata')/name))!=sha(meta/name):raise ValueError('Pseudo-label inventory or split changed')
    v2cfg=json.loads((ROOT/'models/retrained_v2_perspective/model_config.json').read_text(encoding='utf-8'))
    if risk['model_sha256']!=v2cfg['weights_sha256'] or risk['geometry_sha256']!=v2cfg['geometry_sha256']:
        raise ValueError('Pseudo-label model provenance differs')
    splits={r['sheet_id']:r['split'] for r in read(meta/'sheet_splits.csv')}
    labels={(r['sheet_id'],int(r['question_no'])) for r in read(meta/'answer_labels.csv') if r['ground_truth'].strip()}
    cfg=json.loads((ROOT/'models/retrained_v3_verified/model_config.json').read_text(encoding='utf-8'))
    if cfg['geometry_sha256']!=report['geometry_sha256'] or cfg['classes']!=CLASSES:raise ValueError('Model/preprocessing mismatch')
    random.seed(20261028);np.random.seed(20261028);torch.manual_seed(20261028);torch.set_num_threads(4)
    model,device=load_trained_model(ROOT/'models/retrained_v3_verified/row_cnn.pt',expected_sha256=cfg['weights_sha256'])
    pseudo_x,pseudo_y,pseudo_meta,considered=load_pseudo_crops(risk,labels,splits,model,device,cfg['geometry_sha256'])
    # Provenance is saved separately and explicitly not merged into ground truth.
    (WORK/'pseudo_provenance.json').write_text(json.dumps({'considered_questions':considered,'selected_questions':len(pseudo_meta),
        'selected_by_class':dict(Counter(x[2] for x in pseudo_meta)),'questions':pseudo_meta,'confidence_floor':.99,
        'source':'v2 CNN A/B + CLA A/B agreement, v3 CNN agrees on both','confirmed_targets_untouched':True,
        'train_only':True,'excluded_frozen_audit_sample':True,'source_sha256':source_hashes},indent=2),encoding='utf-8')
    train=np.flatnonzero(data['split']=='train');val=np.flatnonzero(data['split']=='validation');cutoff=cfg['cnn_confidence_cutoff']
    baseline,_=evaluate(model,data,val,device,cutoff);best=baseline;best_epoch=0;best_state=copy.deepcopy(model.state_dict())
    counts=np.bincount(data['targets'][train],minlength=len(CLASSES));weights=np.ones(len(CLASSES),dtype=np.float32)
    weights[counts>0]=np.minimum(np.sqrt(counts.max()/counts[counts>0]),8)
    criterion=torch.nn.CrossEntropyLoss(weight=torch.tensor(weights,device=device))
    opt=torch.optim.Adam(model.parameters(),lr=.00003)
    human=TensorDataset(torch.from_numpy(data['crops'][train,None].astype(np.float32)/255.),torch.from_numpy(data['targets'][train]))
    pseudo=TensorDataset(torch.from_numpy(pseudo_x[:,None].astype(np.float32)/255.),torch.from_numpy(pseudo_y))
    hloader=DataLoader(human,batch_size=128,shuffle=True,generator=torch.Generator().manual_seed(20261028))
    ploader=DataLoader(pseudo,batch_size=128,shuffle=True,generator=torch.Generator().manual_seed(20261029))
    history=[];stale=0;started=time.perf_counter()
    print('Baseline Validation:',json.dumps(baseline),flush=True)
    for epoch in range(1,7):
        model.train();pt=iter(ploader);total=0.
        for hx,hy in hloader:
            try:px,py=next(pt)
            except StopIteration:pt=iter(ploader);px,py=next(pt)
            hx,hy,px,py=hx.to(device),hy.to(device),px.to(device),py.to(device)
            opt.zero_grad(set_to_none=True)
            loss=criterion(model(augment_train(hx)),hy)+.25*criterion(model(augment_train(px)),py)
            if not torch.isfinite(loss):raise ValueError('Non-finite loss')
            loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5);opt.step();total+=float(loss.detach())*len(hx)
        metrics,_=evaluate(model,data,val,device,cutoff)
        history.append({'epoch':epoch,'loss':total/len(human),'validation':metrics})
        if admissible(metrics,baseline) and rank(metrics)>rank(best):
            best=metrics;best_epoch=epoch;best_state=copy.deepcopy(model.state_dict());stale=0;torch.save(best_state,WORK/'candidate.pt')
        else:stale+=1
        (WORK/'history.json').write_text(json.dumps(history,indent=2),encoding='utf-8')
        print(f'Epoch {epoch}: {json.dumps(metrics)}; selected={best_epoch}',flush=True)
        if stale>=3:break
    result={'baseline_model':'v3','selected_epoch':best_epoch,'selected_model':'candidate' if best_epoch else 'v3',
        'baseline_validation':baseline,'selected_validation':best,'training_seconds':time.perf_counter()-started,
        'policy':'No increased accepted errors in either workflow; max 5% additional deferrals; then minimize errors and deferrals',
        'test_used_for_selection':False,'pseudo_weight':.25,'learning_rate':.00003,'source_sha256':source_hashes,
        'confirmed_package_sha256':sha(package),'pseudo_questions':len(pseudo_meta),'cutoff':cutoff,
        'runtime_gate':'Compare full-sheet production pair gate on Validation before Test; same risk policy.',
        'warning':'Pseudo labels are not human confirmed and are numeric only; special-mark quality remains limited. Validation is assisted.'}
    (WORK/'selection.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    for path,expected in source_hashes.items():
        if sha(ROOT/path)!=expected:raise RuntimeError('Protected source changed: '+path)
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()

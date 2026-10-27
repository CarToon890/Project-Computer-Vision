"""Compare v3 against a low-rate candidate trained only on confirmed Train labels."""
import argparse
import copy
import json
import random
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader,TensorDataset
from omr_model import CLASSES,load_trained_model
from omr_retrain import augment_train,sha,validate_rows
from omr_retrain_v3 import evaluate,admissible,rank

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'presentation_build/retraining_v4_verified_20261028'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=OUT)
    parser.add_argument('--epochs',type=int,default=6)
    parser.add_argument('--patience',type=int,default=3)
    parser.add_argument('--seed',type=int,default=20261029)
    args=parser.parse_args();output=args.output
    if args.epochs<1 or args.patience<1:raise ValueError('Invalid training configuration')
    if output.exists():raise ValueError('Existing experiment preserved')
    output.mkdir(parents=True)
    source=ROOT/'presentation_build/retraining_v3_20261028/input';package=source/'confirmed_rows.npz'
    report=json.loads((source/'preflight.json').read_text(encoding='utf-8'))
    if sha(package)!=report['package_sha256']['confirmed_rows.npz']:raise ValueError('Confirmed package changed')
    with np.load(package,allow_pickle=False) as z:data={k:z[k] for k in z.files}
    validate_rows(data,report)
    folder=ROOT/'models/retrained_v3_verified';cfg=json.loads((folder/'model_config.json').read_text(encoding='utf-8'))
    if cfg['geometry_sha256']!=report['geometry_sha256'] or cfg['classes']!=CLASSES:raise ValueError('Model/preprocessing mismatch')
    protected=[ROOT/'data/metadata/answer_labels.csv',ROOT/'data/metadata/sheet_splits.csv',ROOT/'data/metadata/image_inventory_verified.csv',folder/'row_cnn.pt',folder/'model_config.json']
    hashes={str(p.relative_to(ROOT)):sha(p) for p in protected}
    for name in ('answer_labels.csv','sheet_splits.csv','image_inventory_verified.csv'):
        if hashes[str(Path('data/metadata')/name)]!=report['source_sha256']['data/metadata/'+name]:raise ValueError('Data changed since v3 preparation')
    random.seed(args.seed);np.random.seed(args.seed);torch.manual_seed(args.seed);torch.set_num_threads(4)
    model,device=load_trained_model(folder/'row_cnn.pt',expected_sha256=cfg['weights_sha256'])
    train=np.flatnonzero(data['split']=='train');val=np.flatnonzero(data['split']=='validation');cutoff=cfg['cnn_confidence_cutoff']
    baseline,_=evaluate(model,data,val,device,cutoff);best=baseline;best_epoch=0;best_state=copy.deepcopy(model.state_dict())
    counts=np.bincount(data['targets'][train],minlength=len(CLASSES));weights=np.ones(len(CLASSES),dtype=np.float32)
    weights[counts>0]=np.minimum(np.sqrt(counts.max()/counts[counts>0]),8)
    criterion=torch.nn.CrossEntropyLoss(weight=torch.tensor(weights,device=device));opt=torch.optim.Adam(model.parameters(),lr=.00003)
    ds=TensorDataset(torch.from_numpy(data['crops'][train,None].astype(np.float32)/255.),torch.from_numpy(data['targets'][train]))
    loader=DataLoader(ds,batch_size=128,shuffle=True,generator=torch.Generator().manual_seed(args.seed))
    history=[];stale=0;started=time.perf_counter()
    print('Verified-only baseline:',json.dumps(baseline),flush=True)
    for epoch in range(1,args.epochs+1):
        model.train();total=0.
        for x,y in loader:
            x,y=x.to(device),y.to(device);opt.zero_grad(set_to_none=True)
            loss=criterion(model(augment_train(x)),y)
            if not torch.isfinite(loss):raise ValueError('Non-finite loss')
            loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5);opt.step();total+=float(loss.detach())*len(x)
        metrics,_=evaluate(model,data,val,device,cutoff)
        history.append({'epoch':epoch,'loss':total/len(ds),'validation':metrics})
        if admissible(metrics,baseline) and rank(metrics)>rank(best):
            best=metrics;best_epoch=epoch;best_state=copy.deepcopy(model.state_dict());stale=0;torch.save(best_state,output/'candidate.pt')
        else:stale+=1
        (output/'history.json').write_text(json.dumps(history,indent=2),encoding='utf-8')
        print(f'Verified-only epoch {epoch}: {json.dumps(metrics)}; selected={best_epoch}',flush=True)
        if stale>=args.patience:break
    selection={'baseline_model':'v3','selected_epoch':best_epoch,'selected_model':'candidate' if best_epoch else 'v3',
               'baseline_validation':baseline,'selected_validation':best,'test_used_for_selection':False,'pseudo_labels_used':False,
               'source_sha256':hashes,'confirmed_package_sha256':sha(package),'learning_rate':.00003,'seed':args.seed,
               'training_seconds':time.perf_counter()-started,'warning':'Per-question A/B selection; full-sheet validation gate still required. Assisted data.'}
    (output/'selection.json').write_text(json.dumps(selection,indent=2),encoding='utf-8')
    for name,digest in hashes.items():
        if sha(ROOT/name)!=digest:raise ValueError('Protected input changed: '+name)
    print(json.dumps(selection,indent=2),flush=True)


if __name__=='__main__':main()

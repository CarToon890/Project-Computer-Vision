"""Risk-first validation experiment using existing confirmed crops and v2 weights."""
import copy
import json
import random
import sys
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from omr_model import CLASSES, load_trained_model
from omr_retrain import augment_train, probabilities, validate_rows, sha
from omr_inference import combine_readings
from omr_runtime import effective_rows


def assess(model,data,indices,device,cutoff):
    probs=probabilities(model,data['crops'][indices],device)
    grouped={}
    for i,p in zip(indices,probs):
        sid=str(data['sheet_id'][i]);q=int(data['question_no'][i]);role=str(data['capture_role'][i])
        grouped.setdefault(sid,{}).setdefault(role,{})[q]=(CLASSES[int(p.argmax())],float(p.max()),CLASSES[int(data['targets'][i])])
    result={'questions':0,'correct':0,'wrong_accepted':0,'deferred':0}
    for sid,roles in grouped.items():
        for q in sorted(roles['A']):
            ap,ac,truth=roles['A'][q];bp,bc,bt=roles['B'][q]
            if truth!=bt:raise ValueError('Paired targets differ')
            # The policy operates on 100 rows; repeat this observation to isolate it.
            a={'predictions':[ap]*100,'confidence':[ac]*100}
            b={'predictions':[bp]*100,'confidence':[bc]*100}
            row=effective_rows(combine_readings(a,b,cutoff,sid),{})[0]
            result['questions']+=1;result['deferred']+=int(row['unresolved'])
            if not row['unresolved']:
                result['correct']+=int(row['final_answer']==truth)
                result['wrong_accepted']+=int(row['final_answer']!=truth)
    return result


def main():
    source=ROOT/'presentation_build/retraining_v2'
    output=ROOT/'presentation_build/omr_augmentation_validation_20261027'
    if output.exists():raise SystemExit('Existing run preserved')
    output.mkdir(parents=True)
    report=json.loads((source/'preflight.json').read_text(encoding='utf-8'))
    with np.load(source/'confirmed_rows.npz',allow_pickle=False) as z:data={k:z[k] for k in z.files}
    validate_rows(data,report)
    config=json.loads((ROOT/'models/retrained_v2_perspective/model_config.json').read_text(encoding='utf-8'))
    random.seed(20261027);np.random.seed(20261027);torch.manual_seed(20261027);torch.set_num_threads(4)
    model,device=load_trained_model(ROOT/'models/retrained_v2_perspective/row_cnn.pt',expected_sha256=config['weights_sha256'])
    train=np.flatnonzero(data['split']=='train');val=np.flatnonzero(data['split']=='validation')
    baseline=assess(model,data,val,device,config['cnn_confidence_cutoff'])
    best=baseline;best_epoch=0;best_state=copy.deepcopy(model.state_dict());history=[]
    count=np.bincount(data['targets'][train],minlength=len(CLASSES));weights=np.ones(len(CLASSES),dtype=np.float32)
    weights[count>0]=np.minimum(np.sqrt(count.max()/count[count>0]),8)
    criterion=torch.nn.CrossEntropyLoss(weight=torch.tensor(weights,device=device))
    optim=torch.optim.Adam(model.parameters(),lr=.00005)
    ds=TensorDataset(torch.from_numpy(data['crops'][train,None].astype(np.float32)/255),torch.from_numpy(data['targets'][train]))
    loader=DataLoader(ds,batch_size=128,shuffle=True,generator=torch.Generator().manual_seed(20261027))
    for epoch in range(1,5):
        model.train();loss_sum=0
        for x,y in loader:
            x,y=x.to(device),y.to(device);optim.zero_grad(set_to_none=True)
            loss=criterion(model(augment_train(x)),y)
            if not torch.isfinite(loss):raise ValueError('Non-finite loss')
            loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5);optim.step();loss_sum+=float(loss.detach())*len(x)
        current=assess(model,data,val,device,config['cnn_confidence_cutoff'])
        history.append({'epoch':epoch,'loss':loss_sum/len(train),'validation':current})
        if (current['deferred']<=baseline['deferred']+int(.05*baseline['questions']) and
            (current['wrong_accepted'],current['deferred'])<(best['wrong_accepted'],best['deferred'])):
            best=current;best_epoch=epoch;best_state=copy.deepcopy(model.state_dict())
        print(json.dumps(history[-1]),flush=True)
    # This package uses legacy extracted crops, so a candidate cannot be deployed
    # without re-evaluation under current perspective preprocessing.
    decision={'baseline':baseline,'best_validation':best,'selected_epoch':best_epoch,'test_used':False,
              'runtime_promoted':False,'reason':'Legacy crop geometry; current perspective pipeline must be evaluated before deployment.',
              'training_questions':int(len(train)/2),'validation_questions':int(len(val)/2),
              'training_data_sha256':sha(source/'confirmed_rows.npz'),'initial_weights_sha256':config['weights_sha256'],
              'augmentation':'existing bounded brightness/contrast and small affine, train only',
              'history':history,'limitation':'Question-level A/B assessment does not apply the sheet-level pair mismatch gate.'}
    (output/'selection.json').write_text(json.dumps(decision,indent=2),encoding='utf-8')
    if best_epoch:torch.save(best_state,output/'candidate.pt')
    print(json.dumps(decision,indent=2),flush=True)


if __name__=='__main__':main()

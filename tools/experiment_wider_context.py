"""Train a wider-row candidate from existing images; Validation only, no dataset writes."""
import copy
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tools'))
from omr_geometry import read_image,rectify_sheet,row_crop
from omr_model import CLASSES,load_trained_model
from omr_retrain import augment_train,validate_rows,sha
from experiment_augmentation import assess
from compare_preprocessing_validation import wider_row


def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def main():
    source=ROOT/'presentation_build/retraining_v2'
    out=ROOT/'presentation_build/omr_wider_context_20261027'
    if out.exists():raise SystemExit('Existing experiment preserved')
    out.mkdir(parents=True)
    report=json.loads((source/'preflight.json').read_text(encoding='utf-8'))
    with np.load(source/'confirmed_rows.npz',allow_pickle=False) as z:data={k:z[k] for k in z.files}
    validate_rows(data,report)
    keep=np.flatnonzero(np.isin(data['split'],['train','validation']))
    groups=defaultdict(list)
    for i in keep:groups[(str(data['sheet_id'][i]),str(data['capture_role'][i]))].append(i)
    meta=ROOT/'data/metadata'
    images={(r['sheet_id'],r['capture_role']):r for r in read(meta/'image_inventory_verified.csv') if r['pair_status']=='verified'}
    conv={r['source_relative_path']:r['normalized_relative_path'] for r in read(meta/'heic_conversion_map.csv')}
    # Allocate only existing confirmed Train/Validation examples, not Test labels or images.
    shape=(len(keep),32,160);current=np.empty(shape,dtype=np.uint8);wide=np.empty(shape,dtype=np.uint8)
    remap={old:new for new,old in enumerate(keep)}
    torch.set_num_threads(4);cv2.setNumThreads(2)
    for number,((sid,role),indices) in enumerate(sorted(groups.items()),1):
        r=images[(sid,role)]
        img=read_image(ROOT/r['relative_path'],conv,ROOT)
        gray,centers,_=rectify_sheet(img,source_sheet_id=sid)
        for old in indices:
            q=int(data['question_no'][old]);i=remap[old]
            current[i]=row_crop(gray,q,centers);wide[i]=wider_row(gray,centers[q-1])
        if number%20==0 or number==len(groups):print(f'Wider context images {number}/{len(groups)}',flush=True)
    subset={k:v[keep] for k,v in data.items() if k!='crops'}
    subset['crops']=current
    config=json.loads((ROOT/'models/retrained_v2_perspective/model_config.json').read_text(encoding='utf-8'))
    random.seed(20261027);np.random.seed(20261027);torch.manual_seed(20261027)
    model,device=load_trained_model(ROOT/'models/retrained_v2_perspective/row_cnn.pt',expected_sha256=config['weights_sha256'])
    tr=np.flatnonzero(subset['split']=='train');val=np.flatnonzero(subset['split']=='validation')
    baseline=assess(model,subset,val,device,config['cnn_confidence_cutoff'])
    subset['crops']=wide
    initial=assess(model,subset,val,device,config['cnn_confidence_cutoff'])
    counts=np.bincount(subset['targets'][tr],minlength=len(CLASSES));weight=np.ones(len(CLASSES),dtype=np.float32)
    weight[counts>0]=np.minimum(np.sqrt(counts.max()/counts[counts>0]),8)
    criterion=torch.nn.CrossEntropyLoss(weight=torch.tensor(weight,device=device))
    opt=torch.optim.Adam(model.parameters(),lr=.00005)
    ds=TensorDataset(torch.from_numpy(wide[tr,None].astype(np.float32)/255),torch.from_numpy(subset['targets'][tr]))
    loader=DataLoader(ds,batch_size=128,shuffle=True,generator=torch.Generator().manual_seed(20261027))
    best=None;best_epoch=0;state=None;history=[]
    for epoch in range(1,5):
        model.train();total=0.
        for x,y in loader:
            x,y=x.to(device),y.to(device);opt.zero_grad(set_to_none=True)
            loss=criterion(model(augment_train(x)),y)
            if not torch.isfinite(loss):raise ValueError('Non-finite training loss')
            loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5);opt.step();total+=float(loss.detach())*len(x)
        result=assess(model,subset,val,device,config['cnn_confidence_cutoff'])
        history.append({'epoch':epoch,'loss':total/len(tr),'validation':result})
        if result['deferred']<=baseline['deferred']+int(.05*baseline['questions']) and (best is None or (result['wrong_accepted'],result['deferred'])<(best['wrong_accepted'],best['deferred'])):
            best=result;best_epoch=epoch;state=copy.deepcopy(model.state_dict())
        print(json.dumps(history[-1]),flush=True)
    # Risk-first promotion requires strictly fewer accepted errors than current baseline.
    promote=bool(best and best['wrong_accepted']<baseline['wrong_accepted'])
    decision={'baseline_current_geometry':baseline,'wide_before_training':initial,'wide_best_validation':best,
              'selected_epoch':best_epoch,'promote_candidate':promote,'test_used':False,
              'runtime_promoted':False,'input':'160x32 with 22px horizontal and 20px vertical margins in registered coordinates',
              'training_data_sha256':sha(source/'confirmed_rows.npz'),'initial_weights_sha256':config['weights_sha256'],
              'history':history,'note':'No blank/multiple/ambiguous validation support; question-level assessment omits the sheet-level A/B mismatch gate; candidate needs held-out verification and runtime integration.'}
    (out/'selection.json').write_text(json.dumps(decision,indent=2),encoding='utf-8')
    if state is not None:torch.save(state,out/'candidate.pt')
    print(json.dumps(decision,indent=2),flush=True)


if __name__=='__main__':main()

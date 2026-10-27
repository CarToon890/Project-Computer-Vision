"""Risk-first fine-tuning from v2 using confirmed labels and fixed Test cohorts."""
import argparse
import copy
import hashlib
import json
import random
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader,TensorDataset

from omr_model import CLASSES,load_trained_model
from omr_retrain import augment_train,probabilities,sha,validate_rows

ROOT=Path(__file__).resolve().parents[1]


def rows_from_probabilities(data,indices,probs,cutoff):
    grouped={}
    for i,p in zip(indices,probs):
        sid,q,role=str(data['sheet_id'][i]),int(data['question_no'][i]),str(data['capture_role'][i])
        grouped.setdefault((sid,q),{})[role]=(CLASSES[int(p.argmax())],float(p.max()),CLASSES[int(data['targets'][i])])
    rows=[]
    for (sid,q),pair in sorted(grouped.items()):
        if set(pair)!={'A','B'} or pair['A'][2]!=pair['B'][2]:raise ValueError('Paired labels differ')
        ap,ac,truth=pair['A'];bp,bc,_=pair['B']
        a_ok=ap!='ambiguous' and ac>=cutoff
        a=ap if a_ok else 'ambiguous'
        a_defer=a in {'ambiguous','blank','multiple'}
        used_b=not a_ok
        ab=ap if a_ok else bp if bc>=cutoff else 'ambiguous'
        disagree=ap!='ambiguous' and bp!='ambiguous' and ap!=bp and bc>=cutoff
        ab_defer=ab in {'ambiguous','blank','multiple'} or disagree
        rows.append({'sheet_id':sid,'question_no':q,'ground_truth':truth,'a_prediction':ap,'b_prediction':bp,
                     'a_confidence':ac,'b_confidence':bc,'a_only':a,'a_only_deferred':a_defer,
                     'a_then_b':ab,'a_then_b_deferred':ab_defer,'used_b':used_b,'ab_disagree':disagree})
    return rows


def summarize(rows,field):
    result={'questions':len(rows),'correct_accepted':0,'wrong_accepted':0,'deferred':0,'used_b':0}
    for r in rows:
        deferred=r[field+'_deferred']
        result['deferred']+=int(deferred)
        if not deferred:
            result['correct_accepted']+=int(r[field]==r['ground_truth'])
            result['wrong_accepted']+=int(r[field]!=r['ground_truth'])
        if field=='a_then_b':result['used_b']+=int(r['used_b'])
    return result


def evaluate(model,data,indices,device,cutoff):
    probs=probabilities(model,data['crops'][indices],device)
    rows=rows_from_probabilities(data,indices,probs,cutoff)
    loss=float(-np.log(np.clip(probs[np.arange(len(indices)),data['targets'][indices]],1e-12,1)).mean())
    return {'A_only':summarize(rows,'a_only'),'A_then_B':summarize(rows,'a_then_b'),'loss':loss},rows


def admissible(candidate,baseline):
    modes=('A_only','A_then_B')
    return all(candidate[k]['wrong_accepted']<=baseline[k]['wrong_accepted'] and
               candidate[k]['deferred']<=baseline[k]['deferred']+int(.05*baseline[k]['questions']) for k in modes)


def rank(metrics):
    modes=('A_only','A_then_B')
    return (-sum(metrics[k]['wrong_accepted'] for k in modes),-sum(metrics[k]['deferred'] for k in modes))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir',type=Path,required=True);parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--epochs',type=int,default=12);parser.add_argument('--patience',type=int,default=3)
    args=parser.parse_args();source=args.data_dir;out=args.output_dir
    if out.exists() and any(out.iterdir()):raise ValueError('Use a new empty output directory')
    out.mkdir(parents=True,exist_ok=True)
    report=json.loads((source/'preflight.json').read_text(encoding='utf-8'))
    if not report.get('include_all_confirmed_test'):raise ValueError('Expected all confirmed Test labels')
    if sha(source/'confirmed_rows.npz')!=report['package_sha256']['confirmed_rows.npz']:raise ValueError('Training package changed')
    with np.load(source/'confirmed_rows.npz',allow_pickle=False) as archive:data={k:archive[k] for k in archive.files}
    validate_rows(data,report)
    model_dir=ROOT/'models/retrained_v2_perspective';config=json.loads((model_dir/'model_config.json').read_text(encoding='utf-8'))
    if config['classes']!=CLASSES or config['geometry_sha256']!=report['geometry_sha256']:raise ValueError('Model or preprocessing differs')
    protected={str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'data/metadata/answer_labels.csv',ROOT/'data/metadata/sheet_splits.csv',ROOT/'data/metadata/image_inventory_verified.csv',model_dir/'row_cnn.pt',model_dir/'model_config.json']}
    random.seed(20261028);np.random.seed(20261028);torch.manual_seed(20261028);torch.set_num_threads(4)
    model,device=load_trained_model(model_dir/'row_cnn.pt',expected_sha256=config['weights_sha256'])
    train=np.flatnonzero(data['split']=='train');val=np.flatnonzero(data['split']=='validation');cutoff=config['cnn_confidence_cutoff']
    baseline,_=evaluate(model,data,val,device,cutoff)
    best=baseline;best_epoch=0;best_state=copy.deepcopy(model.state_dict());history=[]
    counts=np.bincount(data['targets'][train],minlength=len(CLASSES));weights=np.ones(len(CLASSES),dtype=np.float32)
    weights[counts>0]=np.minimum(np.sqrt(counts.max()/counts[counts>0]),8)
    criterion=torch.nn.CrossEntropyLoss(weight=torch.tensor(weights,device=device))
    optimizer=torch.optim.Adam(model.parameters(),lr=.0001)
    dataset=TensorDataset(torch.from_numpy(data['crops'][train,None].astype(np.float32)/255.),torch.from_numpy(data['targets'][train]))
    loader=DataLoader(dataset,batch_size=128,shuffle=True,num_workers=0,generator=torch.Generator().manual_seed(20261028))
    stale=0;started=time.perf_counter()
    print('Baseline Validation:',json.dumps(baseline),flush=True)
    for epoch in range(1,args.epochs+1):
        model.train();loss_sum=0.
        for x,y in loader:
            x,y=x.to(device),y.to(device);optimizer.zero_grad(set_to_none=True)
            loss=criterion(model(augment_train(x)),y)
            if not torch.isfinite(loss):raise ValueError('Non-finite training loss')
            loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5);optimizer.step();loss_sum+=float(loss.detach())*len(x)
        current,_=evaluate(model,data,val,device,cutoff)
        history.append({'epoch':epoch,'training_loss':loss_sum/len(train),'validation':current})
        if admissible(current,baseline) and rank(current)>rank(best):
            best=current;best_epoch=epoch;best_state=copy.deepcopy(model.state_dict());stale=0
            torch.save(best_state,out/'candidate.pt')
        else:stale+=1
        (out/'history.json').write_text(json.dumps(history,indent=2),encoding='utf-8')
        print(f'Epoch {epoch}: {json.dumps(current)}; selected={best_epoch}',flush=True)
        if stale>=args.patience:break
    selection={'selected_epoch':best_epoch,'selected_model':'candidate' if best_epoch else 'v2',
               'selection':'Validation only; neither A-only nor A/B may increase accepted errors versus v2; extra deferrals <=5% each; minimize combined errors then deferrals',
               'test_used_for_selection':False,'baseline_validation':baseline,'selected_validation':best,'fixed_cutoff':cutoff,
               'training_seconds':time.perf_counter()-started,'seed':20261028,'learning_rate':.0001,'epochs_run':len(history),
               'class_counts':report['classes_by_split'],'data_sha256':sha(source/'confirmed_rows.npz'),
               'source_sha256':protected,'warning':'A/B per-question policy; sheet-level pair-mismatch gate not applied. Assisted data; Test not independent.'}
    (out/'selection.json').write_text(json.dumps(selection,indent=2),encoding='utf-8')
    # Test is touched only after the selection is written.
    selected_model,_=load_trained_model(model_dir/'row_cnn.pt',device=device,expected_sha256=config['weights_sha256'])
    selected_model.load_state_dict(best_state);selected_model.eval()
    baseline_model,_=load_trained_model(model_dir/'row_cnn.pt',device=device,expected_sha256=config['weights_sha256'])
    test=np.flatnonzero(data['split']=='test');frozen=np.flatnonzero((data['split']=='test') & np.isin(data['sheet_id'],report['frozen_test_sheets']))
    results={}
    for name,indices in [('all_confirmed_test',test),('frozen_ten_sheets',frozen)]:
        base,_=evaluate(baseline_model,data,indices,device,cutoff)
        chosen,_=evaluate(selected_model,data,indices,device,cutoff)
        results[name]={'v2':base,'selected':chosen}
    for name,expected in protected.items():
        if sha(ROOT/name)!=expected:raise RuntimeError('Protected source changed: '+name)
    evaluation={'independent_evaluation':False,'type':'assisted development retest',
                'selection_sha256':sha(out/'selection.json'),'results':results}
    (out/'evaluation.json').write_text(json.dumps(evaluation,indent=2),encoding='utf-8')
    print(json.dumps({'selection':selection,'test':evaluation},indent=2),flush=True)


if __name__=='__main__':main()

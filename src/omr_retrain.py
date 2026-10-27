"""Fine-tune saved RowCNN once on confirmed rows, selecting only on Validation."""
import argparse
import copy
import csv
import hashlib
import json
import random
import time
import zipfile
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

from omr_model import CLASSES, load_trained_model


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_rows(data, report):
    n = len(data['targets'])
    if data['crops'].shape != (n, 32, 160) or data['crops'].dtype != np.uint8:
        raise ValueError('Expected uint8 crops with shape (N,32,160).')
    if not np.isfinite(data['cla_scores']).all() or data['cla_scores'].shape != (n,5):
        raise ValueError('Invalid registered CLA scores.')
    if any(len(data[k]) != n for k in ('split','sheet_id','question_no','capture_role')):
        raise ValueError('Mismatched row metadata.')
    if set(data['split']) != {'train','validation','test'} or not np.isin(data['targets'],range(len(CLASSES))).all():
        raise ValueError('Invalid splits or class indices.')
    groups, sheet_splits = {}, {}
    for i in range(n):
        sid, q, role, split = str(data['sheet_id'][i]), int(data['question_no'][i]), str(data['capture_role'][i]), str(data['split'][i])
        if sid in sheet_splits and sheet_splits[sid] != split:
            raise ValueError(f'Sheet leakage across splits: {sid}')
        if not 1 <= q <= 100 or role not in {'A','B'}:
            raise ValueError('Invalid question or capture role.')
        sheet_splits[sid] = split
        group = groups.setdefault((sid,q),{})
        if role in group:
            raise ValueError('Duplicate question/capture row.')
        group[role] = int(data['targets'][i])
    if any(set(g) != {'A','B'} or g['A'] != g['B'] for g in groups.values()):
        raise ValueError('Missing paired crop or unequal A/B target.')
    expected_test = set(report['frozen_test_sheets'])
    actual_test={s for s,v in sheet_splits.items() if v=='test'}
    if (not report.get('include_all_confirmed_test') and actual_test != expected_test) or (report.get('include_all_confirmed_test') and not expected_test <= actual_test):
        raise ValueError('Frozen Test cohort changed.')
    for sid in expected_test:
        if {q for s,q in groups if s==sid} != set(range(1,101)):
            raise ValueError('Test must retain all 100 questions, including deferrals.')
    counts = {s:sum(v==s for v in data['split']) for s in ('train','validation','test')}
    if counts != report['crop_rows_by_split']:
        raise ValueError('Preflight row counts changed.')
    if report['omr_or_cnn_drafts_used_as_targets'] != 0:
        raise ValueError('Unconfirmed draft targets are prohibited in this run.')


def probabilities(model, crops, device, batch_size=256):
    model.eval()
    result=[]
    with torch.inference_mode():
        for start in range(0,len(crops),batch_size):
            x=torch.from_numpy(crops[start:start+batch_size,None].astype(np.float32)/255.).to(device)
            result.append(model(x).softmax(1).cpu().numpy())
    return np.concatenate(result)


def confidence_cutoff(truth, probs, precision=.99):
    predicted, confidence = probs.argmax(1), probs.max(1)
    candidates=[]
    for cutoff in np.unique(confidence):
        accepted=(confidence>=cutoff)&(predicted!=CLASSES.index('ambiguous'))
        if accepted.any() and (predicted[accepted]==truth[accepted]).mean()>=precision:
            candidates.append((int(accepted.sum()),float(cutoff)))
    return max(candidates,key=lambda p:(p[0],-p[1]))[1] if candidates else 1.01


def workflow(data, indices, probs, cutoff):
    groups={}
    for i,p in zip(indices,probs):
        sid,q,role=str(data['sheet_id'][i]),int(data['question_no'][i]),str(data['capture_role'][i])
        prediction=CLASSES[int(p.argmax())] if float(p.max())>=cutoff else 'ambiguous'
        groups.setdefault((sid,q),{})[role]=(prediction,float(p.max()),CLASSES[int(data['targets'][i])])
    rows=[]
    for (sid,q),g in sorted(groups.items()):
        if set(g)!={'A','B'} or g['A'][2]!=g['B'][2]:
            raise ValueError('Evaluation requires matching A/B targets.')
        a,ac,truth=g['A']; b,bc,_=g['B']; use_b=a=='ambiguous'
        rows.append({'sheet_id':sid,'question_no':q,'ground_truth':truth,'a_only':a,
            'a_then_b':b if use_b else a,'used_B':use_b,'a_confidence':ac,'b_confidence':bc})
    return rows


def metrics(rows, field):
    matrix=np.zeros((len(CLASSES),len(CLASSES)),dtype=np.int64)
    for row in rows:
        matrix[CLASSES.index(row['ground_truth']),CLASSES.index(row[field])]+=1
    tp=np.diag(matrix); support=matrix.sum(1); predicted=matrix.sum(0)
    precision=np.divide(tp,predicted,out=np.zeros(len(CLASSES)),where=predicted!=0)
    recall=np.divide(tp,support,out=np.zeros(len(CLASSES)),where=support!=0)
    f1=np.divide(2*precision*recall,precision+recall,out=np.zeros(len(CLASSES)),where=precision+recall!=0)
    deferred=sum(r[field]=='ambiguous' for r in rows)
    correct=sum(r[field]==r['ground_truth'] and r[field]!='ambiguous' for r in rows)
    return {'questions':len(rows),'correct':correct,'deferred':deferred,'wrong_non_deferred':len(rows)-correct-deferred,
        'accuracy':correct/len(rows),'coverage':1-deferred/len(rows),'macro_f1':float(f1.mean()),
        'confusion_matrix_labels':CLASSES,'confusion_matrix':matrix.tolist(),
        'classification_report':{c:{'precision':float(precision[i]),'recall':float(recall[i]),
            'f1-score':float(f1[i]),'support':int(support[i])} for i,c in enumerate(CLASSES)}}


def summarize(rows):
    return {'A_only':metrics(rows,'a_only'),'A_then_B':metrics(rows,'a_then_b'),
        'question_B_usage':sum(r['used_B'] for r in rows)/len(rows),
        'sheet_B_request_rate':len({r['sheet_id'] for r in rows if r['used_B']})/len({r['sheet_id'] for r in rows})}


def validation_result(model,data,indices,device):
    probs=probabilities(model,data['crops'][indices],device)
    a=data['capture_role'][indices]=='A'
    cutoff=confidence_cutoff(data['targets'][indices][a],probs[a])
    rows=workflow(data,indices,probs,cutoff)
    summary=summarize(rows)
    loss=float(-np.log(np.clip(probs[np.arange(len(indices)),data['targets'][indices]],1e-12,1)).mean())
    rank=(summary['A_only']['correct'],summary['A_then_B']['correct'],
          -summary['A_only']['wrong_non_deferred']-summary['A_then_B']['wrong_non_deferred'],-loss)
    return {'cutoff':cutoff,'summary':summary,'loss':loss,'rank':rank}, probs


def augment_train(x):
    # No flips: option order must remain 1..5. White padding avoids invented marks.
    n=len(x)
    angle=(torch.rand(n,device=x.device)-.5)*(.034906585)
    theta=torch.zeros((n,2,3),device=x.device)
    theta[:,0,0]=angle.cos(); theta[:,0,1]=-angle.sin()
    theta[:,1,0]=angle.sin(); theta[:,1,1]=angle.cos()
    theta[:,0,2]=(torch.rand(n,device=x.device)-.5)*.025
    theta[:,1,2]=(torch.rand(n,device=x.device)-.5)*.04
    grid=F.affine_grid(theta,x.shape,align_corners=False)
    x=F.grid_sample(x-1,grid,align_corners=False,padding_mode='zeros')+1
    gain=.9+.2*torch.rand((n,1,1,1),device=x.device)
    contrast=.9+.2*torch.rand((n,1,1,1),device=x.device)
    return ((x-.5)*contrast+.5).mul(gain).clamp(0,1)


def write_rows(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--epochs',type=int,default=12)
    parser.add_argument('--patience',type=int,default=3)
    parser.add_argument('--learning-rate',type=float,default=1e-4)
    parser.add_argument('--seed',type=int,default=20261026)
    parser.add_argument('--threads',type=int,default=4)
    args=parser.parse_args()
    if args.epochs<1 or args.patience<1 or args.learning_rate<=0 or args.threads<1:
        raise ValueError('Invalid training parameters.')
    output=args.output_dir.resolve();output.mkdir(parents=True,exist_ok=True)
    if (output/'evaluation.json').exists():
        raise ValueError('Use a new output directory; completed training runs are preserved.')
    random.seed(args.seed);np.random.seed(args.seed);torch.manual_seed(args.seed)
    torch.set_num_threads(args.threads)
    if torch.cuda.is_available():torch.cuda.manual_seed_all(args.seed)
    torch.backends.cudnn.benchmark=False
    torch.backends.cudnn.deterministic=True
    report=json.loads((args.data_dir/'preflight.json').read_text(encoding='utf-8'))
    for name,expected in report['package_sha256'].items():
        if sha(args.data_dir/name)!=expected:raise ValueError(f'Package checksum changed: {name}')
    if 'src/omr_retrain.py' in report['package_sha256'] and sha(Path(__file__))!=report['package_sha256']['src/omr_retrain.py']:
        raise ValueError('Running training code differs from the recorded package.')
    with np.load(args.data_dir/'confirmed_rows.npz',allow_pickle=False) as archive:
        data={name:archive[name] for name in archive.files}
    validate_rows(data,report)
    config=json.loads((args.data_dir/'baseline_config.json').read_text(encoding='utf-8'))
    if config['classes']!=CLASSES:raise ValueError('Class order changed.')
    model,device=load_trained_model(args.data_dir/'baseline_row_cnn.pt',expected_sha256=config['weights_sha256'])
    train=np.flatnonzero(data['split']=='train');val=np.flatnonzero(data['split']=='validation')
    # Test indices and predictions are not accessed during training or selection.
    initial,_=validation_result(model,data,val,device)
    best=initial;best_epoch=0;best_state=copy.deepcopy(model.state_dict());history=[]
    optimizer=torch.optim.Adam(model.parameters(),lr=args.learning_rate)
    counts=np.bincount(data['targets'][train],minlength=len(CLASSES))
    weights=np.ones(len(CLASSES),dtype=np.float32)
    observed=counts>0
    weights[observed]=np.minimum(np.sqrt(counts.max()/counts[observed]),8)
    criterion=torch.nn.CrossEntropyLoss(weight=torch.tensor(weights,device=device))
    dataset=TensorDataset(torch.from_numpy(data['crops'][train,None].astype(np.float32)/255.),torch.from_numpy(data['targets'][train]))
    loader=DataLoader(dataset,batch_size=128,shuffle=True,num_workers=0,generator=torch.Generator().manual_seed(args.seed))
    stale=0;started=time.perf_counter()
    print(f'Fine-tuning on {device}: {len(train)} crops; Validation={len(val)}; Test reserved until selection.',flush=True)
    print(f'Baseline Validation: A={initial["summary"]["A_only"]["correct"]}, A+B={initial["summary"]["A_then_B"]["correct"]}',flush=True)
    for epoch in range(1,args.epochs+1):
        model.train();total=0.;seen=0
        for x,y in loader:
            x,y=x.to(device),y.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss=criterion(model(augment_train(x)),y)
            if not torch.isfinite(loss):raise ValueError('Training loss is not finite.')
            loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5.);optimizer.step()
            total+=float(loss.item())*len(x);seen+=len(x)
        current,_=validation_result(model,data,val,device)
        history.append({'epoch':epoch,'training_loss':total/seen,'validation':current})
        if current['rank']>best['rank']:
            best=current;best_epoch=epoch;best_state=copy.deepcopy(model.state_dict());stale=0
            torch.save(best_state,output/'best_candidate.pt')
        else:stale+=1
        (output/'history.json').write_text(json.dumps(history,indent=2),encoding='utf-8')
        print(f'Epoch {epoch}: loss={total/seen:.4f}; Val A={current["summary"]["A_only"]["correct"]}; A+B={current["summary"]["A_then_B"]["correct"]}; selected epoch={best_epoch}',flush=True)
        if stale>=args.patience:break
    # Freeze the decision before reading Test predictions. Never select on Test.
    decision={'selected_epoch':best_epoch,'selected_weights':'fine_tuned' if best_epoch else 'baseline',
        'selected_on':'Validation only: A-only correct, A-then-B correct, fewer errors, lower loss',
        'baseline_validation':initial,'selected_validation':best,'test_used_for_selection':False,
        'epochs_run':len(history),'training_seconds':time.perf_counter()-started,
        'training_parameters':{'seed':args.seed,'learning_rate':args.learning_rate,'max_epochs':args.epochs,
            'patience':args.patience,'batch_size':128,'augmentation':'bounded brightness/contrast, small affine, white padding; Train only',
            'optimizer':'Adam','device':str(device),'torch_version':str(torch.__version__),'numpy_version':np.__version__}}
    (output/'selection.json').write_text(json.dumps(decision,indent=2),encoding='utf-8')
    model.load_state_dict(best_state,strict=True);model.eval()
    torch.save(model.state_dict(),output/'row_cnn.pt')
    config.update({'weights_sha256':sha(output/'row_cnn.pt'),'cnn_confidence_cutoff':best['cutoff'],
        'model_version':'confirmed-finetune-v2','selected_epoch':best_epoch,'selected_on':'validation',
        'training_confirmed_questions':report['confirmed_questions_by_split']['train'],
        'validation_confirmed_questions':report['confirmed_questions_by_split']['validation'],
        'training_sheets':report['sheets_by_split']['train'],'test_used_for_model_selection':False,
        'independent_evaluation':False,'annotation_mode':'human_inspected_omr_assisted'})
    config['baseline_pilot_provenance']={k:config.pop(k) for k in ('training_pilot_sheets','training_human_labels') if k in config}
    (output/'model_config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    test=np.flatnonzero(data['split']=='test')
    baseline,_=load_trained_model(args.data_dir/'baseline_row_cnn.pt',device=device,expected_sha256=report['package_sha256']['baseline_row_cnn.pt'])
    base_probs=probabilities(baseline,data['crops'][test],device)
    selected_probs=probabilities(model,data['crops'][test],device)
    original_config=json.loads((args.data_dir/'baseline_config.json').read_text(encoding='utf-8'))
    old_rows=workflow(data,test,base_probs,original_config['cnn_confidence_cutoff'])
    recalibrated_rows=workflow(data,test,base_probs,initial['cutoff'])
    new_rows=workflow(data,test,selected_probs,best['cutoff'])
    for name,rows in [('baseline',old_rows),('baseline_recalibrated',recalibrated_rows),('selected',new_rows)]:
        write_rows(output/f'{name}_test_predictions.csv',rows)
    evaluation={'evaluation_type':'assisted_development_retest','independent_evaluation':False,
        'test_questions':len(new_rows),'test_sheets':report['frozen_test_sheets'],'selection':decision,
        'baseline_original_cutoff':summarize(old_rows),'baseline_recalibrated_on_current_validation':summarize(recalibrated_rows),
        'selected_model':summarize(new_rows),'original_baseline_preserved':True,
        'training_class_weights':dict(zip(CLASSES,weights.tolist())),
        'training_classes_with_fewer_than_10_questions':[c for c in CLASSES if report['classes_by_split']['train'].get(c,0)<10],
        'dataset_source_sha256':report['source_sha256']}
    (output/'evaluation.json').write_text(json.dumps(evaluation,indent=2),encoding='utf-8')
    with zipfile.ZipFile(output/'retraining_results.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
        for path in output.iterdir():
            if path.is_file() and path.suffix in {'.pt','.json','.csv'}:z.write(path,path.name)
    def compact(rows):
        return {mode:{k:v for k,v in metrics(rows,field).items() if k in {'questions','correct','deferred','wrong_non_deferred','accuracy'}}
                for mode,field in [('A_only','a_only'),('A_then_B','a_then_b')]}
    print(json.dumps({'output':str(output),'selected_epoch':best_epoch,'baseline_test':compact(old_rows),
        'selected_test':compact(new_rows)},indent=2),flush=True)


if __name__ == '__main__':
    main()

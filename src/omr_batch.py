"""Operational test of every verified pair; accuracy is restricted to frozen labeled Test sheets."""
import argparse
import csv
import hashlib
import json
import time
import shutil
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import torch

from omr_model import CLASSES,load_trained_model,predict_cnn
from omr_geometry import read_image,rectify_sheet,row_crop,bubble_scores
from omr_inference import read_csv
from omr_runtime import build_methods,cla_reading
from omr_retrain import summarize

ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path,value):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)


def read_capture(image,model,device,conversions,cache,geometry_hash,compatible_versions=()):
    source=ROOT/image['relative_path'];normalized=ROOT/conversions.get(Path(image['relative_path']).as_posix(),image['relative_path'])
    started=time.perf_counter();source_sha=sha(source);normalized_sha=sha(normalized)
    fingerprint=hashlib.sha256((source_sha+normalized_sha+geometry_hash).encode()).hexdigest()
    target=cache/f'{image["sheet_id"]}_{image["capture_role"]}_{fingerprint[:20]}.npz'
    info_path=target.with_suffix('.json');cached=target.exists() and info_path.exists()
    if not cached:
        for previous in compatible_versions:
            old_fp=hashlib.sha256((source_sha+normalized_sha+previous).encode()).hexdigest()
            old=cache/f'{image["sheet_id"]}_{image["capture_role"]}_{old_fp[:20]}.npz';old_info_path=old.with_suffix('.json')
            if not old.exists() or not old_info_path.exists():continue
            old_info=json.loads(old_info_path.read_text(encoding='utf-8'))
            if old_info['source_sha256']!=source_sha or old_info['normalized_sha256']!=normalized_sha or old_info['geometry_hash']!=previous:
                raise ValueError('Predecessor cache provenance does not match.')
            # New row-level deskew affects only tilted rows. Reuse is proven
            # safe only when every row was already horizontal within one pixel.
            if old_info['registration'].get('alignment_after',{}).get('max_row_tilt_px',999)>1.:
                continue
            shutil.copy2(old,target);old_info.update(geometry_hash=geometry_hash,cache_reused_from_geometry_sha256=previous)
            write_json(info_path,old_info);cached=True;break
    if not cached:
        processing=time.perf_counter();raw=read_image(source,conversions,ROOT)
        gray,centers,registration=rectify_sheet(raw,source_sheet_id=image['sheet_id'])
        crops=np.stack([row_crop(gray,q,centers) for q in range(1,101)])
        scores=np.stack([bubble_scores(gray,q,centers) for q in range(1,101)])
        np.savez_compressed(target,crops=crops,scores=scores)
        write_json(info_path,{'source_sha256':source_sha,'normalized_sha256':normalized_sha,'geometry_hash':geometry_hash,
            'registration':registration,'processing_seconds':time.perf_counter()-processing})
    info=json.loads(info_path.read_text(encoding='utf-8'))
    if info['source_sha256']!=source_sha or info['normalized_sha256']!=normalized_sha or info['geometry_hash']!=geometry_hash:
        raise ValueError('Cache source or geometry fingerprint differs.')
    with np.load(target,allow_pickle=False) as archive:crops,scores=archive['crops'],archive['scores']
    if crops.shape!=(100,32,160) or crops.dtype!=np.uint8 or scores.shape!=(100,5) or not np.isfinite(scores).all():
        raise ValueError('Registered row cache is incomplete.')
    infer_started=time.perf_counter();indices,confidence=predict_cnn(model,crops,device)
    return {'predictions':[CLASSES[int(i)] for i in indices],'confidence':confidence.tolist(),'cla_scores':scores.tolist(),
        'registration':info['registration'],'used_registration_cache':bool(cached),
        'cached_cold_processing_seconds':info['processing_seconds'],'cnn_seconds':time.perf_counter()-infer_started,
        'actual_batch_seconds':time.perf_counter()-started,'source_sha256':source_sha,'normalized_sha256':normalized_sha}


def question_output(sid,method,rows,a,config):
    a_reading=cla_reading(a,config) if method=='cla' else a
    output=[]
    for row in rows:
        q=row['question_no'];a_only='ambiguous'
        if a_reading:
            a_only=a_reading['predictions'][q-1]
            if method=='cnn' and a_reading['confidence'][q-1]<config['cnn_confidence_cutoff']:a_only='ambiguous'
        output.append({**row,'method':method,'a_only':a_only,'a_then_b':row['proposed_answer'] or 'ambiguous'})
    return output


def write_csv(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir',type=Path,default=ROOT/'models/retrained_v2')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'presentation_build/system_test_270_v2')
    parser.add_argument('--calibrate-on-validation','--calibrate-cnn-on-validation',dest='calibrate_cnn_on_validation',action='store_true')
    parser.add_argument('--compatible-cache-geometry',action='append',default=[],help='Verified predecessor SHA; only for changes that append failure recovery and preserve successful outputs.')
    args=parser.parse_args();output=args.output_dir.resolve();output.mkdir(parents=True,exist_ok=True)
    if any(len(v)!=64 or any(c not in '0123456789abcdef' for c in v) for v in args.compatible_cache_geometry):
        raise ValueError('Compatible geometry versions must be complete lowercase SHA256 values.')
    meta=ROOT/'data/metadata';cache=ROOT/'presentation_build/registered_row_cache';cache.mkdir(exist_ok=True)
    protected={name:sha(ROOT/name) for name in ['data/metadata/image_inventory_verified.csv','data/metadata/answer_labels.csv',
        'data/metadata/sheet_splits.csv','data/metadata/pairing_review_holds.csv','models/row_cnn.pt']}
    config=json.loads((args.model_dir/'model_config.json').read_text(encoding='utf-8'))
    inventory=[r for r in read_csv(meta/'image_inventory_verified.csv') if r['pair_status']=='verified']
    pairs={}
    for image in inventory:pairs.setdefault(image['sheet_id'],{})[image['capture_role']]=image
    if len(inventory)!=540 or len(pairs)!=270 or any(set(p)!={'A','B'} for p in pairs.values()):
        raise ValueError('The fixed operational run requires exactly 270 verified A/B pairs.')
    if any(r['sheet_id'] in pairs and r['review_status']=='pending' for r in read_csv(meta/'pairing_review_holds.csv')):
        raise ValueError('A verified pair is on hold.')
    geometry_hash=hashlib.sha256(''.join(sha(ROOT/name) for name in ['src/omr_geometry.py','tools/build_answer_pilot.py']).encode()
        +protected['data/metadata/image_inventory_verified.csv'].encode()+protected['data/metadata/sheet_splits.csv'].encode()).hexdigest()
    conversions={r['source_relative_path']:r['normalized_relative_path'] for r in read_csv(meta/'heic_conversion_map.csv')}
    torch.set_num_threads(2);cv2.setNumThreads(2)
    model,device=load_trained_model(args.model_dir/config['weights_file'],expected_sha256=config['weights_sha256'])
    signature={'model_sha256':config['weights_sha256'],'geometry_sha256':geometry_hash,
        'inventory_sha256':protected['data/metadata/image_inventory_verified.csv'],'cnn_cutoff':config['cnn_confidence_cutoff'],
        'cla_fill':config['cla_fill_threshold'],'cla_margin':config['cla_margin_threshold'],'runtime_sha256':sha(ROOT/'src/omr_runtime.py'),
        'calibrate_cnn_on_validation':args.calibrate_cnn_on_validation}
    signature['compatible_predecessor_geometry_sha256']=args.compatible_cache_geometry
    signature_path=output/'run_signature.json'
    if signature_path.exists() and json.loads(signature_path.read_text())!=signature:
        raise ValueError('Use a new output directory after changing model, data or policies.')
    write_json(signature_path,signature)
    captures={};failures=[];image_records=[];started=time.perf_counter()
    for number,image in enumerate(sorted(inventory,key=lambda r:(r['sheet_id'],r['capture_role'])),1):
        sid,role=image['sheet_id'],image['capture_role'];record=output/f'{sid}_{role}.json'
        try:
            if record.exists():saved=json.loads(record.read_text(encoding='utf-8'))
            else:
                capture=read_capture(image,model,device,conversions,cache,geometry_hash,args.compatible_cache_geometry)
                saved={'sheet_id':sid,'role':role,'status':'read','capture':capture};write_json(record,saved)
            if saved['status']!='read':raise ValueError(saved['error'])
            captures[(sid,role)]=saved['capture'];image_records.append(saved)
        except (ValueError,OSError,RuntimeError,cv2.error) as error:
            captures[(sid,role)]=None
            saved={'sheet_id':sid,'role':role,'status':'failed','error':str(error)}
            failures.append(saved);image_records.append(saved);write_json(record,saved)
        if number%30==0 or number==540:
            write_json(output/'progress.json',{'attempted_images':number,'total_images':540,'failures':len(failures),'complete':False})
            print(f'Operational images {number}/540; failed={len(failures)}',flush=True)
    if args.calibrate_cnn_on_validation:
        split_map={r['sheet_id']:r['split'] for r in read_csv(meta/'sheet_splits.csv')}
        validation=[r for r in read_csv(meta/'answer_labels.csv') if split_map.get(r['sheet_id'])=='validation' and r['ground_truth'].strip()]
        observations=[]
        for row in validation:
            capture=captures.get((row['sheet_id'],'A'));q=int(row['question_no'])-1
            if capture:observations.append((row['ground_truth'],capture['predictions'][q],capture['confidence'][q]))
        candidates=[]
        for cutoff in sorted({float(c) for _,_,c in observations}):
            accepted=[(truth,pred) for truth,pred,conf in observations if conf>=cutoff and pred!='ambiguous']
            if accepted and sum(t==p for t,p in accepted)/len(accepted)>=.99:
                candidates.append((len(accepted),cutoff))
        selected=max(candidates,key=lambda p:(p[0],-p[1]))[1] if candidates else 1.01
        calibration={'selected_on':'Validation A only, after perspective correction','target_precision':.99,
            'confirmed_validation_questions':len(validation),'readable_validation_questions':len(observations),
            'previous_cutoff':config['cnn_confidence_cutoff'],'selected_cutoff':selected,'test_used_for_selection':False}
        cla_a=[];cla_b=[];truth=[];has_a=[];has_b=[]
        for row in validation:
            q=int(row['question_no'])-1;a=captures.get((row['sheet_id'],'A'));b=captures.get((row['sheet_id'],'B'))
            cla_a.append(a['cla_scores'][q] if a else [0]*5);cla_b.append(b['cla_scores'][q] if b else [0]*5)
            has_a.append(a is not None);has_b.append(b is not None);truth.append(CLASSES.index(row['ground_truth']))
        cla_a=np.asarray(cla_a);cla_b=np.asarray(cla_b);truth=np.asarray(truth);has_a=np.asarray(has_a);has_b=np.asarray(has_b)
        def classify(scores,fill,margin,exists):
            active=(scores>=fill).sum(1);ordered=np.sort(scores,axis=1)
            labels=np.where(active==0,5,np.where(active>1,6,np.where(ordered[:,-1]-ordered[:,-2]<margin,7,scores.argmax(1))))
            return np.where(exists,labels,7)
        best=None
        for fill in sorted({float(v) for v in np.linspace(.03,.30,28)}|{config['cla_fill_threshold']}):
            for margin in sorted({.01,.02,.04,.06,.08,.10,config['cla_margin_threshold']}):
                ap=classify(cla_a,fill,margin,has_a);bp=classify(cla_b,fill,margin,has_b)
                ab=np.where(np.isin(ap,[5,6,7])&has_b,bp,ap)
                rank=(int((ab==truth).sum()),int((ap==truth).sum()),-abs(fill-config['cla_fill_threshold'])-abs(margin-config['cla_margin_threshold']))
                if best is None or rank>best[0]:best=(rank,fill,margin)
        calibration['cla']={'selected_on':'Validation A-then-B correct first, A-only correct second; Test not used','previous_fill':config['cla_fill_threshold'],
            'previous_margin':config['cla_margin_threshold'],'selected_fill':best[1],'selected_margin':best[2],
            'validation_A_correct':best[0][1],'validation_A_then_B_correct':best[0][0],'questions':len(validation),'test_used_for_selection':False}
        write_json(output/'validation_calibration.json',calibration)
        config={**config,'cnn_confidence_cutoff':selected,'cla_fill_threshold':best[1],'cla_margin_threshold':best[2],
            'model_version':config['model_version']+'+perspective-v1',
            'preprocessing_version':'answer-plane-perspective-v1','geometry_sha256':geometry_hash,
            'validation_calibration':calibration}
    write_json(output/'effective_model_config.json',config)
    all_rows={'cnn':[],'cla':[]};pair_records=[]
    for sid in sorted(pairs):
        a,b=captures[(sid,'A')],captures[(sid,'B')]
        methods,check=build_methods(a,b,config,sid)
        for method,rows in methods.items():all_rows[method].extend(question_output(sid,method,rows,a,config))
        pair_records.append({'sheet_id':sid,'a_readable':a is not None,'b_readable':b is not None,'pair_check':check,
            **{f'{method}_review_questions':sum(r['needs_review'] for r in rows) for method,rows in methods.items()}})
    for method,rows in all_rows.items():write_csv(output/f'{method}_all_270_predictions.csv',rows)
    # Accuracy is computed only after the complete operational run, on the frozen cohort.
    preflight=json.loads((ROOT/'presentation_build/retraining_v2/preflight.json').read_text(encoding='utf-8'))
    test_sheets=set(preflight['frozen_test_sheets'])
    labels={(r['sheet_id'],int(r['question_no'])):r['ground_truth'] for r in read_csv(meta/'answer_labels.csv')
        if r['sheet_id'] in test_sheets and r['ground_truth'].strip()}
    if len(labels)!=1000:raise ValueError('Frozen Test reference must contain exactly 1,000 confirmed answers.')
    evaluation={}
    for method,rows in all_rows.items():
        test=[{**r,'ground_truth':labels[(r['sheet_id'],r['question_no'])]} for r in rows if r['sheet_id'] in test_sheets]
        evaluation[method]=summarize(test);write_csv(output/f'{method}_frozen_test_predictions.csv',test)
    assert protected=={name:sha(ROOT/name) for name in protected},'Canonical files or original weights changed.'
    summary={'attempted_pairs':270,'attempted_images':540,'readable_images':540-len(failures),'failed_images':failures,
        'pairs_with_both_images_readable':sum(r['a_readable'] and r['b_readable'] for r in pair_records),
        'pair_mismatch_flags':[r for r in pair_records if r['pair_check']['blocked']],
        'methods':{m:{'questions':len(rows),'needs_review':sum(r['needs_review'] for r in rows),
            'questions_using_B':sum(r['used_B'] for r in rows),'pairs_using_B':len({r['sheet_id'] for r in rows if r['used_B']})} for m,rows in all_rows.items()},
        'registration_modes':dict(Counter(r['capture']['registration']['mode'] for r in image_records if r['status']=='read')),
        'perspective_corrected_images':sum(r['capture']['registration'].get('perspective_corrected',False) for r in image_records if r['status']=='read'),
        'residual_curvature_warnings':[{'sheet_id':r['sheet_id'],'role':r['role'],'alignment':r['capture']['registration'].get('alignment_after')}
            for r in image_records if r['status']=='read' and not r['capture']['registration'].get('page_aligned',True)],
        'images_using_registration_cache':sum(r['capture']['used_registration_cache'] for r in image_records if r['status']=='read'),
        'timing_note':'actual_batch_seconds measures this cached run; cached_cold_processing_seconds records earlier uncached extraction. Neither is a fresh end-to-end UI benchmark.',
        'actual_batch_wall_seconds':time.perf_counter()-started,'frozen_test_questions':1000,
        'frozen_test_sheets':sorted(test_sheets),'evaluation':evaluation,'independent_evaluation':False,
        'evaluation_type':'assisted_development_retest','unlabeled_questions_used_as_reference':0,
        'canonical_files_preserved':True,'model_sha256':config['weights_sha256'],'geometry_sha256':geometry_hash,
        'cla_policy':'existing fill/margin; retry B for blank/multiple/ambiguous; pair mismatch gate shared with CNN',
        'pair_flags_do_not_modify_dataset':True}
    write_json(output/'summary.json',summary);write_json(output/'pair_results.json',pair_records)
    write_json(output/'progress.json',{'attempted_images':540,'total_images':540,'failures':len(failures),'complete':True})
    print(json.dumps({'pairs':270,'readable_images':summary['readable_images'],'failed_images':len(failures),
        'pair_flags':len(summary['pair_mismatch_flags']),'output':str(output)},indent=2),flush=True)


if __name__=='__main__':main()

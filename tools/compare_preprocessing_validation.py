"""Exploratory Validation-only preprocessing comparison; never changes runtime or labels."""
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from omr_geometry import read_image, rectify_sheet, row_crop
from omr_model import CLASSES, load_trained_model, predict_cnn
from omr_inference import combine_readings
from omr_runtime import effective_rows
from omr_geometry import reader


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def wider_row(gray, points):
    points = np.asarray(points, dtype=np.float32)
    direction = points[-1]-points[0]
    length = float(np.linalg.norm(direction))
    if length < 40 or direction[0] <= 0:
        raise ValueError('Invalid answer row geometry')
    along = direction/length
    across = np.array([-along[1], along[0]],dtype=np.float32)
    left = points[0]-along*22
    right = points[-1]+along*22
    corners = np.float32([left-across*20,right-across*20,right+across*20,left+across*20])
    target = np.float32([[0,0],[159,0],[159,31],[0,31]])
    return cv2.warpPerspective(gray,cv2.getPerspectiveTransform(corners,target),(160,32),
                               flags=cv2.INTER_AREA,borderValue=255)


def main():
    out=ROOT/'presentation_build/omr_preprocess_validation_20261027'
    if out.exists():raise SystemExit('Existing experiment preserved')
    out.mkdir(parents=True)
    meta=ROOT/'data/metadata'
    split={r['sheet_id']:r['split'] for r in rows(meta/'sheet_splits.csv')}
    labels={}
    for r in rows(meta/'answer_labels.csv'):
        if split.get(r['sheet_id'])=='validation' and r['ground_truth'].strip():
            labels[(r['sheet_id'],int(r['question_no']))]=r['ground_truth'].strip()
    sheets={sid for sid,_ in labels}
    images=[r for r in rows(meta/'image_inventory_verified.csv') if r['sheet_id'] in sheets and r['pair_status']=='verified']
    conversions={r['source_relative_path']:r['normalized_relative_path'] for r in rows(meta/'heic_conversion_map.csv')}
    model_dir=ROOT/'models/retrained_v2_perspective'
    config=json.loads((model_dir/'model_config.json').read_text(encoding='utf-8'))
    torch.set_num_threads(2);cv2.setNumThreads(2)
    model,device=load_trained_model(model_dir/config['weights_file'],expected_sha256=config['weights_sha256'])
    captures={};failures=[]
    for number,r in enumerate(images,1):
        sid,role=r['sheet_id'],r['capture_role']
        try:
            image=read_image(ROOT/r['relative_path'],conversions,ROOT)
            gray,centers,_=rectify_sheet(image,source_sheet_id=sid)
            normalized=reader.normalize_illumination(gray)
            variants={'current':np.stack([row_crop(gray,q,centers) for q in range(1,101)]),
                      'normalized':np.stack([row_crop(normalized,q,centers) for q in range(1,101)]),
                      'wider_existing_model':np.stack([wider_row(gray,points) for points in centers])}
            for name,crops in variants.items():
                idx,confidence=predict_cnn(model,crops,device)
                captures[(name,sid,role)]={'predictions':[CLASSES[int(i)] for i in idx],'confidence':confidence.tolist()}
        except (ValueError,OSError,RuntimeError,cv2.error) as e:
            failures.append({'sheet_id':sid,'role':role,'error':str(e)})
        if number%10==0 or number==len(images):print(f'Validation images {number}/{len(images)}; failures={len(failures)}',flush=True)
    if failures:
        (out/'failures.json').write_text(json.dumps(failures,indent=2),encoding='utf-8')
        raise SystemExit('Cannot compare different cohorts; no candidate selected.')
    summary={}
    for name in ('current','normalized','wider_existing_model'):
        stats={'questions':0,'correct':0,'wrong_accepted':0,'deferred':0,'used_b':0}
        for sid in sorted(sheets):
            a=captures[(name,sid,'A')];b=captures[(name,sid,'B')]
            for r in effective_rows(combine_readings(a,b,config['cnn_confidence_cutoff'],sid),{}):
                truth=labels.get((sid,r['question_no']))
                if truth is None:continue
                stats['questions']+=1;stats['deferred']+=int(r['unresolved']);stats['used_b']+=int(r['used_B'])
                if not r['unresolved']:
                    stats['correct']+=int(r['final_answer']==truth)
                    stats['wrong_accepted']+=int(r['final_answer']!=truth)
        summary[name]=stats
    result={'validation_only':True,'selection_or_runtime_changed':False,'results':summary,
            'note':'Wider crops use unchanged weights: an exploratory distribution-shift check, not a trained wider-context comparison. The sheet-level A/B mismatch gate was not applied; no special-class validation labels.'}
    (out/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()

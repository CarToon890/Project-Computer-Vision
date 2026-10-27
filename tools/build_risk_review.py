"""Prepare a frozen CNN/CLA risk queue from existing local predictions only."""
import csv
import hashlib
import json
import math
import random
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
META=ROOT/'data/metadata'
RUN=ROOT/'presentation_build/system_test_270_perspective_fixed'
OUT=ROOT/'presentation_build/risk_review_20261027_v3'
NUMERIC={'1','2','3','4','5'}


def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def classify(cnn,cla,cutoff,pair_blocked):
    reasons=[]
    def confidence(role):
        try:
            value=float(cnn[f'{role}_confidence'])
            return value if math.isfinite(value) and 0<=value<=1 else None
        except (ValueError,TypeError):return None
    ac,bc=confidence('a'),confidence('b')
    ap,bp=cnn['a_prediction'],cnn['b_prediction']
    ca,cb=cla['a_prediction'],cla['b_prediction']
    if pair_blocked:reasons.append('pair_warning')
    if not ap or not bp or not ca or not cb:reasons.append('missing_reading')
    if any(v in {'blank','multiple','ambiguous'} for v in (ap,bp,ca,cb)):
        reasons.append('special_or_uncertain')
    if ap and bp and ap!=bp:reasons.append('cnn_ab_disagree')
    if ca and cb and ca!=cb:reasons.append('cla_ab_disagree')
    if any(c and d and c!=d for c,d in ((ap,ca),(bp,cb))):reasons.append('methods_disagree')
    if not ap or not bp or ac is None or bc is None or min(ac,bc)<cutoff:
        reasons.append('low_cnn_confidence')
    if cnn['needs_review']=='True' or cla['needs_review']=='True':reasons.append('existing_review_flag')
    agreed=all(v in NUMERIC for v in (ap,bp,ca,cb)) and len({ap,bp,ca,cb})==1 and not reasons
    weights={'pair_warning':8,'missing_reading':6,'special_or_uncertain':5,'cnn_ab_disagree':4,
             'cla_ab_disagree':3,'methods_disagree':4,'low_cnn_confidence':3,'existing_review_flag':1}
    return {'group':'agreement' if agreed else 'risk','reasons':reasons,'priority':sum(weights[r] for r in reasons),
            'proposal':cnn['proposed_answer'], 'cnn_a':ap,'cnn_b':bp,'cla_a':ca,'cla_b':cb,
            'confidence_a':ac,'confidence_b':bc}


def build():
    config=json.loads((ROOT/'models/retrained_v2_perspective/model_config.json').read_text(encoding='utf-8'))
    summary=json.loads((RUN/'summary.json').read_text(encoding='utf-8'))
    audit=json.loads((ROOT/'presentation_build/omr_risk_policy_20261027/dataset_audit.json').read_text(encoding='utf-8'))
    for name in ('image_inventory_verified.csv','sheet_splits.csv'):
        if sha(META/name)!=audit['source_sha256'][name]:raise ValueError(f'Inventory or split changed: {name}')
    if summary['model_sha256']!=config['weights_sha256'] or summary['geometry_sha256']!=config['geometry_sha256']:
        raise ValueError('Saved predictions do not match current model profile')
    pairs={r['sheet_id']:r for r in json.loads((RUN/'pair_results.json').read_text(encoding='utf-8'))}
    inventory=read(META/'image_inventory_verified.csv')
    sheets={r['sheet_id'] for r in inventory if r['pair_status']=='verified'}
    if set(pairs)!=sheets:raise ValueError('Saved prediction sheets differ from verified inventory')
    splits={r['sheet_id']:r['split'] for r in read(META/'sheet_splits.csv')}
    labels={(r['sheet_id'],int(r['question_no'])) for r in read(META/'answer_labels.csv') if r['ground_truth'].strip()}
    holds={r['sheet_id'] for r in read(META/'pairing_review_holds.csv') if r['review_status']=='pending'}
    def keyed(path):
        result={}
        for r in read(path):
            k=(r['sheet_id'],int(r['question_no']))
            if k in result or k[0] not in sheets or not 1<=k[1]<=100:raise ValueError('Invalid prediction keys')
            result[k]=r
        return result
    cnn=keyed(RUN/'cnn_all_270_predictions.csv');cla=keyed(RUN/'cla_all_270_predictions.csv')
    expected={(sid,q) for sid in sheets for q in range(1,101)}
    if set(cnn)!=expected or set(cla)!=expected:raise ValueError('Predictions do not cover all verified sheets')
    items={}
    for sid,q in sorted(expected):
        if (sid,q) in labels or sid in holds:continue
        item=classify(cnn[(sid,q)],cla[(sid,q)],config['cnn_confidence_cutoff'],pairs[sid]['pair_check']['blocked'])
        item['split']=splits[sid];items[f'{sid}:{q}']=item
    # Deterministic sample is fixed before any sample answers are collected.
    eligible=sorted(k for k,v in items.items() if v['group']=='agreement')
    sample=random.Random(20261027).sample(eligible,min(100,len(eligible)))
    for k in sample:items[k]['audit_sample']=True
    paths=[RUN/'cnn_all_270_predictions.csv',RUN/'cla_all_270_predictions.csv',RUN/'pair_results.json',
           META/'answer_labels.csv',META/'image_inventory_verified.csv',META/'sheet_splits.csv']
    run_id=hashlib.sha256(json.dumps(items,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:16]
    return {'version':'cnn-cla-risk-v1','run_id':run_id,'items':items,'sample_size':len(sample),'sample_seed':20261027,
            'sample_method':'uniform random among unconfirmed agreement questions, fixed before review',
            'independent_evaluation':False,'model_sha256':config['weights_sha256'],
            'geometry_sha256':config['geometry_sha256'],'confidence_cutoff':config['cnn_confidence_cutoff'],
            'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in paths},
            'note':'Agreement is a heuristic, not a guarantee. Existing assisted labels and known development test are not independent.'}


def main():
    OUT.mkdir(parents=True,exist_ok=True);target=OUT/'risk_review.json'
    if target.exists():raise SystemExit('Existing queue preserved')
    data=build();target.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    from collections import Counter
    print(json.dumps({'groups':dict(Counter(i['group'] for i in data['items'].values())),
                      'sample_size':data['sample_size'],'output':str(target)},ensure_ascii=False))


if __name__=='__main__':main()

"""Summarize existing development predictions; never treat ground truth as a human review."""
import csv
import json
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'presentation_build/system_test_270_perspective_fixed'
OUT=ROOT/'presentation_build/omr_risk_policy_20261027/workflow_comparison.json'


def summarize(rows):
    result=Counter()
    for row in rows:
        result['questions']+=1
        result['raw_correct']+=int(row['proposed_answer']==row['ground_truth'])
        unresolved=row['needs_review']=='True' or row['proposed_answer'] not in {'1','2','3','4','5','blank','multiple'}
        result['deferred']+=int(unresolved)
        if not unresolved:
            result['correct_accepted']+=int(row['proposed_answer']==row['ground_truth'])
            result['wrong_accepted']+=int(row['proposed_answer']!=row['ground_truth'])
    return {k:result[k] for k in ('questions','raw_correct','correct_accepted','wrong_accepted','deferred')}


def main():
    if OUT.exists():raise SystemExit('Existing comparison preserved')
    outputs={}
    inputs={}
    for method in ('cnn','cla'):
        with (SOURCE/f'{method}_frozen_test_predictions.csv').open(encoding='utf-8-sig',newline='') as f:
            inputs[method]=list(csv.DictReader(f))
    keys=lambda rows:{(r['sheet_id'],r['question_no'],r['ground_truth']) for r in rows}
    if keys(inputs['cnn'])!=keys(inputs['cla']) or len(inputs['cnn'])!=1000 or len(inputs['cla'])!=1000:
        raise ValueError('Comparison cohorts differ')
    for method,rows in inputs.items():outputs[method]=summarize(rows)
    result={'evaluation_type':'assisted development retest','independent_evaluation':False,
            'workflow':'A-then-B, saved original runtime flags before subsequent disagreement policy change',
            'methods':outputs,'after_human_review':'Not available: no independent reviewed app-session outcomes were collected.',
            'limitation':'Special classes are poorly represented; accuracy cannot establish performance on unseen sheets.'}
    OUT.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()

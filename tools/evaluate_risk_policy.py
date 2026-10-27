"""Compare review policies on existing predictions; freeze on Validation before Test."""
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from omr_inference import combine_readings
from omr_runtime import effective_rows

SOURCE = ROOT / 'presentation_build/system_test_270_perspective_fixed'
OUT = ROOT / 'presentation_build/omr_risk_policy_20261027'


def read(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measurements(records, labels, cutoff, pair=True):
    groups = defaultdict(list)
    for row in records:
        if row['sheet_id'] in labels:
            groups[row['sheet_id']].append(row)
    totals = Counter()
    for sid, rows in groups.items():
        rows.sort(key=lambda r: int(r['question_no']))
        if len(rows) != 100:
            raise ValueError('Every included prediction sheet must contain 100 rows')
        def capture(role):
            if not all(r[f'{role}_prediction'] for r in rows):
                return None
            return {'predictions': [r[f'{role}_prediction'] for r in rows],
                    'confidence': [float(r[f'{role}_confidence']) for r in rows]}
        a, b = capture('a'), capture('b') if pair else None
        for row in effective_rows(combine_readings(a, b, cutoff, sid), {}):
            key = row['question_no']
            if key not in labels[sid]:
                continue
            totals['questions'] += 1
            totals['deferred'] += int(row['unresolved'])
            if not row['unresolved']:
                totals['correct'] += int(row['final_answer'] == labels[sid][key])
                totals['wrong_accepted'] += int(row['final_answer'] != labels[sid][key])
            totals['used_b'] += int(row['used_B'])
    return {k: totals[k] for k in ('questions', 'correct', 'wrong_accepted', 'deferred', 'used_b')}


def main():
    if (OUT / 'selection.json').exists():
        raise SystemExit('Existing run preserved; choose a new output directory.')
    meta = ROOT / 'data/metadata'
    config = json.loads((ROOT / 'models/retrained_v2_perspective/model_config.json').read_text(encoding='utf-8'))
    split = {r['sheet_id']: r['split'] for r in read(meta / 'sheet_splits.csv')}
    sources = [meta/'sheet_splits.csv', meta/'answer_labels.csv', meta/'image_inventory_verified.csv',
               SOURCE/'cnn_all_270_predictions.csv', SOURCE/'cla_all_270_predictions.csv',
               ROOT/'models/retrained_v2_perspective/model_config.json']
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    records = read(SOURCE/'cnn_all_270_predictions.csv')
    labels = defaultdict(lambda: defaultdict(dict))
    for row in read(meta/'answer_labels.csv'):
        sid = row['sheet_id']; answer = row['ground_truth'].strip()
        if answer:
            labels[split[sid]][sid][int(row['question_no'])] = answer
    val = labels['validation']
    old_cutoff = config['cnn_confidence_cutoff']
    baseline = measurements(records, val, old_cutoff)
    # Limit additional review workload to 5 percentage points versus current policy.
    max_deferred = baseline['deferred'] + int(.05 * baseline['questions'])
    candidates = {old_cutoff}
    for row in records:
        if row['sheet_id'] in val:
            candidates.update(float(row[k]) for k in ('a_confidence', 'b_confidence') if row[k] and float(row[k]) <= 1)
    candidates = sorted(candidates)
    tested = []
    for cutoff in candidates:
        m = measurements(records, val, cutoff)
        if m['deferred'] <= max_deferred:
            tested.append((m['wrong_accepted'], m['deferred'], abs(cutoff-old_cutoff), cutoff, m))
    best = min(tested, key=lambda x: x[:4])
    # Only change the active policy for a strictly lower Validation error count.
    promote = best[0] < baseline['wrong_accepted']
    chosen = best[3] if promote else old_cutoff
    OUT.mkdir(parents=True, exist_ok=True)
    decision = {'selected_on': 'confirmed Validation questions only', 'test_used_for_selection': False,
                'existing_cutoff': old_cutoff, 'selected_cutoff': chosen, 'promote_candidate': promote,
                'max_extra_deferred_fraction': .05, 'baseline': baseline,
                'best_candidate': {'cutoff': best[3], **best[4]}, 'source_sha256': hashes,
                'caution': 'Predictions are saved development runs; no special-mark validation support.'}
    (OUT/'selection.json').write_text(json.dumps(decision, indent=2), encoding='utf-8')
    # Development Test is read only after the selection file has been persisted.
    cohort = set(json.loads((ROOT/'presentation_build/retraining_v2/preflight.json').read_text(encoding='utf-8'))['frozen_test_sheets'])
    test = {s: labels['test'][s] for s in cohort}
    result = {'evaluation_type': 'assisted development retest', 'independent_evaluation': False,
              'current_policy': measurements(records, test, old_cutoff),
              'selected_policy': measurements(records, test, chosen),
              'current_a_only': measurements(records, test, old_cutoff, pair=False),
              'selected_a_only': measurements(records, test, chosen, pair=False),
              'selection_file_sha256': digest(OUT/'selection.json')}
    (OUT/'evaluation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    if hashes != {str(p.relative_to(ROOT)): digest(p) for p in sources}:
        raise RuntimeError('Source files changed during run')
    print(json.dumps({'selection': decision, 'evaluation': result}, indent=2))


if __name__ == '__main__':
    main()

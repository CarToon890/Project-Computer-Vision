"""Reproducible Image-A development comparison; never edits labels or models."""
import csv
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools')]
from omr_geometry import read_image, rectify_sheet, row_crop, bubble_scores
from omr_model import CLASSES, load_trained_model
from omr_quality import evaluate_image_quality


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def summarize(items):
    counts = Counter(r['outcome'] for r in items)
    correct, wrong = counts['correct'], counts['wrong']
    accepted = correct + wrong
    return {'confirmed_questions': len(items), 'correct_accepted': correct,
            'wrong_accepted': wrong, 'deferred': counts['deferred'],
            'alignment_failed_questions': counts['alignment_failed'],
            'accepted_accuracy': {'numerator': correct, 'denominator': accepted,
                                  'value': correct / accepted if accepted else None},
            'effective_yield': {'numerator': correct, 'denominator': len(items),
                                'value': correct / len(items) if items else None}}


def outcome(label, confidence, scores, truth, cutoff, rule):
    if label not in {'1', '2', '3', '4', '5'} or confidence < cutoff:
        return 'deferred'
    if rule == 'margin':
        ranked = sorted(scores, reverse=True)
        if ranked[0] - ranked[1] < 0.02:
            return 'deferred'
    return 'correct' if label == truth else 'wrong'


def main():
    # Exclusive directory prevents overwriting a concurrent experiment.
    out = ROOT / 'presentation_build' / ('image_a_tradeoffs_codex_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    out.mkdir(parents=True, exist_ok=False)
    meta = ROOT / 'data/metadata'
    inputs = [meta / n for n in ('answer_labels.csv', 'sheet_splits.csv', 'image_inventory_verified.csv', 'heic_conversion_map.csv', 'pairing_review_holds.csv')]
    inputs += [ROOT/'src/omr_geometry.py', ROOT/'src/omr_model.py', ROOT/'src/omr_inference.py', ROOT/'src/omr_quality.py', ROOT/'tools/build_answer_pilot.py', Path(__file__)]
    paths = {'v3': ROOT/'models/retrained_v3_verified/row_cnn.pt',
             'candidate': ROOT/'presentation_build/retraining_v4_single_a_20261029/candidate_single_a.pt',
             'final': ROOT/'presentation_build/retraining_v4_single_a_20261029/final_model/row_cnn.pt'}
    initial_hashes = {str(p.relative_to(ROOT)): digest(p) for p in inputs + list(paths.values())}
    cfg = json.loads((ROOT/'models/retrained_v3_verified/model_config.json').read_text(encoding='utf-8'))
    if initial_hashes[str(paths['v3'].relative_to(ROOT))] != cfg['weights_sha256']:
        raise ValueError('v3 checksum mismatch')
    splits = {r['sheet_id']: r['split'] for r in rows(meta/'sheet_splits.csv')}
    inv = {r['sheet_id']: r for r in rows(meta/'image_inventory_verified.csv') if r['pair_status'] == 'verified' and r['capture_role'] == 'A'}
    conv = {r['source_relative_path']: r['normalized_relative_path'] for r in rows(meta/'heic_conversion_map.csv')}
    held = {r['sheet_id'] for r in rows(meta/'pairing_review_holds.csv') if r['review_status'] == 'pending'}
    grouped = defaultdict(list)
    for r in rows(meta/'answer_labels.csv'):
        sid, truth = r['sheet_id'], r['ground_truth'].strip().lower()
        if truth and splits.get(sid) in ('validation', 'test'):
            if truth not in CLASSES or not 1 <= int(r['question_no']) <= 100:
                raise ValueError('Invalid confirmed label')
            grouped[sid].append((int(r['question_no']), truth))
    if not grouped:
        raise ValueError('No validation or test labels')
    torch.set_num_threads(4)
    models = {name: load_trained_model(path, device='cpu')[0] for name, path in paths.items()}
    extraction, prediction, failed = [], defaultdict(dict), []
    crops_saved, crop_keys, source_hashes = [], [], {}
    timing = defaultdict(list)
    print('Extracting', len(grouped), 'validation/test A images', flush=True)
    for index, (sid, labels) in enumerate(sorted(grouped.items()), 1):
        split = splits[sid]
        t = time.perf_counter()
        try:
            if sid in held or sid not in inv:
                raise ValueError('pending pair hold or missing verified A image')
            source_path = ROOT/inv[sid]['relative_path']
            source_hashes[sid] = {'source_sha256': digest(source_path)}
            normalized = conv.get(inv[sid]['relative_path'])
            if normalized:
                source_hashes[sid]['normalized_sha256'] = digest(ROOT/normalized)
            image = read_image(source_path, conv, ROOT)
            aligned, centers, reg = rectify_sheet(image, source_sheet_id=sid)
            crop = np.stack([row_crop(aligned, q, centers) for q, _ in labels])
            scores = [bubble_scores(aligned, q, centers).tolist() for q, _ in labels]
            quality = evaluate_image_quality(image, reg)['status']
            extraction_seconds = time.perf_counter() - t
            timing[split + '_extraction_seconds'].append(extraction_seconds)
            timing[split + '_quality_' + quality + '_extraction_seconds'].append(extraction_seconds)
            for name, model in models.items():
                t_model = time.perf_counter()
                with torch.inference_mode():
                    probs = torch.softmax(model(torch.from_numpy(crop[:, None].astype(np.float32)/255.)), 1).numpy()
                inference_seconds = time.perf_counter()-t_model
                timing[split + '_' + name + '_inference_seconds'].append(inference_seconds)
                timing[split + '_quality_' + quality + '_' + name + '_inference_seconds'].append(inference_seconds)
                prediction[name][sid] = [(CLASSES[int(p.argmax())], float(p.max())) for p in probs]
            for (q, truth), score in zip(labels, scores):
                extraction.append({'sheet': sid, 'question': q, 'truth': truth, 'split': split, 'quality': quality, 'scores': score})
            crops_saved.extend(crop)
            crop_keys.extend((sid, q) for q, _ in labels)
        except Exception as exc:
            failed.append({'sheet': sid, 'split': split, 'questions': len(labels), 'reason': str(exc)})
            for q, truth in labels:
                extraction.append({'sheet': sid, 'question': q, 'truth': truth, 'split': split, 'quality': 'alignment_failed', 'scores': None})
        if index % 20 == 0 or index == len(grouped):
            print(f'{index}/{len(grouped)} sheets, {len(failed)} failed', flush=True)
    # Stop if concurrent edits changed the inputs while reading.
    if any(digest(ROOT/p) != value for p, value in initial_hashes.items()):
        raise RuntimeError('Input or model changed during run; discard results')
    per_sheet_idx = Counter()
    for r in extraction:
        sid = r['sheet']
        if r['scores'] is not None:
            i = per_sheet_idx[sid]
            r['predictions'] = {name: prediction[name][sid][i] for name in models}
            per_sheet_idx[sid] += 1
    crop_path = out/'image_a_crops.npz'
    np.savez_compressed(crop_path, crops=np.asarray(crops_saved, dtype=np.uint8),
                        sheet_id=np.asarray([x[0] for x in crop_keys]),
                        question_no=np.asarray([x[1] for x in crop_keys], dtype=np.int16))
    # Prespecified finite grid; all choices use validation only. Prior test results were seen.
    grid = [(rule, c) for rule in ('cutoff', 'margin') for c in (0.40, 0.557031512260437, 0.70, 0.85, 0.95)]
    def evaluate(model, rule, cutoff, split):
        evaluated = []
        for r in extraction:
            if r['split'] != split:
                continue
            result = 'alignment_failed' if r['scores'] is None else outcome(*r['predictions'][model], r['scores'], r['truth'], cutoff, rule)
            evaluated.append({**r, 'outcome': result})
        return evaluated
    validation = [(rule, cutoff, summarize(evaluate('candidate', rule, cutoff, 'validation'))) for rule, cutoff in grid]
    # Two endpoints of the validation risk/coverage curve; not a claim of optimality.
    low_wrong = min(validation, key=lambda x: (x[2]['wrong_accepted'], x[2]['deferred'], x[0], x[1]))
    low_review = min(validation, key=lambda x: (x[2]['deferred'], x[2]['wrong_accepted'], x[0], x[1]))
    margin_choice = min((x for x in validation if x[0] == 'margin'), key=lambda x: (x[2]['wrong_accepted'], x[2]['deferred'], x[1]))
    frozen = {'validation_only_selection': {'reduce_errors': {'rule': low_wrong[0], 'cutoff': low_wrong[1]},
                                             'reduce_review': {'rule': low_review[0], 'cutoff': low_review[1]},
                                             'margin_reduce_errors': {'rule': margin_choice[0], 'cutoff': margin_choice[1]}},
              'warning': 'Retrospective development analysis; previous test results were observed. Final model includes validation training.',
              'hashes': initial_hashes, 'source_image_hashes': source_hashes,
              'crops_sha256': digest(crop_path)}
    (out/'selection_frozen.json').write_text(json.dumps(frozen, indent=2), encoding='utf-8')
    chosen = {'production_cutoff': ('cutoff', cfg['cnn_confidence_cutoff']),
              'validation_reduce_errors': low_wrong[:2], 'validation_reduce_review': low_review[:2],
              'validation_margin': margin_choice[:2]}
    reports = {}
    for split in ('validation', 'test'):
        reports[split] = {}
        for model in models:
            reports[split][model] = {}
            for policy, (rule, cutoff) in chosen.items():
                items = evaluate(model, rule, cutoff, split)
                class_groups, quality_groups = {}, {}
                for field, dest in [('truth', class_groups), ('quality', quality_groups)]:
                    for value in sorted(set(r[field] for r in items)):
                        dest[value] = summarize([r for r in items if r[field] == value])
                reports[split][model][policy] = {'rule': rule, 'cutoff': cutoff, 'overall': summarize(items),
                                                'by_truth': class_groups, 'by_experimental_quality': quality_groups}
    report = {'created_utc': datetime.now(timezone.utc).isoformat(), 'selection': frozen,
              'cohort': 'All confirmed validation/test answers with image A, including failed sheets',
              'limitations': ['Assisted retrospective retest, not independent.', 'Quality labels are experimental heuristics, not verified ground truth.', 'Final model trained on validation; its validation results are in-sample.', 'Only confirmed answer slots are scored; failure questions are not counted as deferred.'],
              'alignment_failures': failed, 'timings_seconds': {k: {'count': len(v), 'total': sum(v), 'median_per_sheet': float(np.median(v))} for k,v in timing.items()},
              'validation_grid_candidate': [{'rule': a, 'cutoff': b, 'metrics': c} for a,b,c in validation], 'results': reports}
    (out/'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print('RESULT_DIR', out, flush=True)


if __name__ == '__main__':
    main()

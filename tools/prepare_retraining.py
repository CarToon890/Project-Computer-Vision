"""Cache registered rows and package confirmed partial labels for one fine-tuning run."""
import argparse
import csv
import hashlib
import json
import shutil
import sys
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from omr_geometry import read_image, rectify_sheet, row_crop, bubble_scores

CLASSES = ['1', '2', '3', '4', '5', 'blank', 'multiple', 'ambiguous']


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_labels(inventory, labels, splits, test_sheets, holds):
    pairs = defaultdict(list)
    for row in inventory:
        if row['pair_status'] == 'verified':
            pairs[row['sheet_id']].append(row)
    for sid, images in pairs.items():
        if sorted(r['capture_role'] for r in images) != ['A', 'B']:
            raise ValueError(f'Invalid verified A/B pair: {sid}')
    if any(r['sheet_id'] in pairs and r['review_status'] == 'pending' for r in holds):
        raise ValueError('Resolve pending pairing holds before preparing training data.')
    split_map = {}
    for row in splits:
        sid = row['sheet_id']
        if sid in split_map or row['split'] not in {'train', 'validation', 'test'}:
            raise ValueError(f'Duplicate or invalid split: {sid}')
        split_map[sid] = row['split']
    if not pairs.keys() <= split_map.keys():
        raise ValueError('A verified sheet has no split.')
    if not test_sheets or any(split_map.get(s) != 'test' or s not in pairs for s in test_sheets):
        raise ValueError('The frozen evaluation cohort must contain only existing Test sheets.')
    selected, seen = [], set()
    for row in labels:
        sid, q = row['sheet_id'], int(row['question_no'])
        key = (sid, q)
        if sid not in pairs or not 1 <= q <= 100 or key in seen:
            raise ValueError(f'Invalid or duplicate canonical answer slot: {key}')
        seen.add(key)
        answer = row['ground_truth'].strip()
        if not answer:
            continue
        if answer not in CLASSES:
            raise ValueError(f'Invalid confirmed mark: {key} {answer}')
        split = split_map[sid]
        if split == 'test' and sid not in test_sheets:
            continue
        selected.append({'sheet_id': sid, 'question_no': q, 'ground_truth': answer, 'split': split})
    for sid in test_sheets:
        if {r['question_no'] for r in selected if r['sheet_id'] == sid} != set(range(1, 101)):
            raise ValueError(f'The frozen Test sheet is not fully confirmed: {sid}')
    if {r['split'] for r in selected} != {'train', 'validation', 'test'}:
        raise ValueError('Confirmed labels are required in each split.')
    return selected, pairs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'presentation_build/retraining_v2')
    parser.add_argument('--compatible-cache-geometry',action='append',default=[],
        help='Explicit predecessor SHA256, only after verifying that changes add recovery paths without changing successful outputs.')
    args = parser.parse_args()
    if any(len(v)!=64 or any(c not in '0123456789abcdef' for c in v) for v in args.compatible_cache_geometry):
        raise ValueError('Compatible geometry versions must be full lowercase SHA256 values.')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    meta = ROOT / 'data/metadata'
    protected = [meta / n for n in ('answer_labels.csv', 'image_inventory_verified.csv', 'sheet_splits.csv', 'pairing_review_holds.csv')]
    protected += [ROOT / 'models/row_cnn.pt', ROOT / 'models/model_config.json']
    before = {p.relative_to(ROOT).as_posix(): sha(p) for p in protected}
    pilot_split = ROOT / 'presentation_build/reviewed_pilot_270/data/metadata/sheet_splits.csv'
    test_sheets = {r['sheet_id'] for r in read_csv(pilot_split) if r['split'] == 'test'}
    selected, pairs = select_labels(read_csv(meta / 'image_inventory_verified.csv'),
        read_csv(meta / 'answer_labels.csv'), read_csv(meta / 'sheet_splits.csv'),
        test_sheets, read_csv(meta / 'pairing_review_holds.csv'))
    wanted = defaultdict(list)
    for label in selected:
        wanted[label['sheet_id']].append(label)
    conversion_path = meta / 'heic_conversion_map.csv'
    conversions = {r['source_relative_path']: r['normalized_relative_path'] for r in read_csv(conversion_path)} if conversion_path.exists() else {}
    geometry_files = [ROOT / 'src/omr_geometry.py', ROOT / 'tools/build_answer_pilot.py']
    geometry_hash = hashlib.sha256(''.join(sha(p) for p in geometry_files).encode()
        + before['data/metadata/image_inventory_verified.csv'].encode()
        + before['data/metadata/sheet_splits.csv'].encode()).hexdigest()
    cache = ROOT / 'presentation_build/registered_row_cache'
    cache.mkdir(parents=True, exist_ok=True)
    arrays, targets, split_values, sheets, questions, roles, scores = [], [], [], [], [], [], []
    failures, registrations = [], []
    images = [r for sid in sorted(wanted) for r in sorted(pairs[sid], key=lambda r: r['capture_role'])]
    for number, image in enumerate(images, 1):
        sid, role = image['sheet_id'], image['capture_role']
        source = ROOT / image['relative_path']
        normalized = ROOT / conversions.get(Path(image['relative_path']).as_posix(), image['relative_path'])
        try:
            fingerprint = hashlib.sha256((sha(source) + sha(normalized) + geometry_hash).encode()).hexdigest()
            target = cache / f'{sid}_{role}_{fingerprint[:20]}.npz'
            info_path = target.with_suffix('.json')
            if not target.exists() or not info_path.exists():
                for previous in args.compatible_cache_geometry:
                    old_fingerprint=hashlib.sha256((sha(source)+sha(normalized)+previous).encode()).hexdigest()
                    old=cache/f'{sid}_{role}_{old_fingerprint[:20]}.npz'
                    if not old.exists() or not old.with_suffix('.json').exists():
                        continue
                    old_info=json.loads(old.with_suffix('.json').read_text(encoding='utf-8'))
                    if old_info['source_sha256']!=sha(source) or old_info['normalized_sha256']!=sha(normalized) or old_info['geometry_hash']!=previous:
                        raise ValueError('Inconsistent predecessor cache provenance.')
                    shutil.copy2(old,target)
                    old_info.update({'geometry_hash':geometry_hash,'cache_reused_from_geometry_sha256':previous})
                    info_path.write_text(json.dumps(old_info,indent=2),encoding='utf-8')
                    break
            if not target.exists() or not info_path.exists():
                started = time.perf_counter()
                raw = read_image(source, conversions, ROOT)
                gray, centers, registration = rectify_sheet(raw, source_sheet_id=sid)
                crops = np.stack([row_crop(gray, q, centers) for q in range(1, 101)])
                bubbles = np.stack([bubble_scores(gray, q, centers) for q in range(1, 101)])
                np.savez_compressed(target, crops=crops, scores=bubbles)
                info_path.write_text(json.dumps({'source_sha256': sha(source), 'normalized_sha256': sha(normalized),
                    'geometry_hash': geometry_hash, 'registration': registration,
                    'processing_seconds': time.perf_counter()-started}, indent=2), encoding='utf-8')
            info = json.loads(info_path.read_text(encoding='utf-8'))
            with np.load(target, allow_pickle=False) as data:
                if data['crops'].shape != (100, 32, 160) or data['scores'].shape != (100, 5):
                    raise ValueError('Incomplete registered row cache.')
                all_crops, all_scores = data['crops'], data['scores']
                for label in sorted(wanted[sid], key=lambda r:r['question_no']):
                    q = label['question_no']
                    arrays.append(all_crops[q-1])
                    scores.append(all_scores[q-1])
                    targets.append(CLASSES.index(label['ground_truth']))
                    split_values.append(label['split']); sheets.append(sid); questions.append(q); roles.append(role)
            registrations.append({'sheet_id':sid, 'role':role, **info})
        except (ValueError, OSError, RuntimeError, cv2.error) as error:
            failures.append({'sheet_id':sid, 'role':role, 'path':image['relative_path'], 'error':str(error)})
            print(f'FAILED {sid} {role}: {error}', flush=True)
        if number % 20 == 0 or number == len(images):
            print(f'Prepared images {number}/{len(images)}; failures={len(failures)}', flush=True)
    (output / 'preprocessing.json').write_text(json.dumps({'registrations':registrations,'failures':failures}, ensure_ascii=False, indent=2), encoding='utf-8')
    if failures:
        raise SystemExit(f'{len(failures)} source images failed; no training package created. See {output / "preprocessing.json"}')
    np.savez_compressed(output / 'confirmed_rows.npz', crops=np.stack(arrays), targets=np.asarray(targets, dtype=np.int64),
        split=np.asarray(split_values), sheet_id=np.asarray(sheets), question_no=np.asarray(questions,dtype=np.int16),
        capture_role=np.asarray(roles), cla_scores=np.asarray(scores,dtype=np.float32))
    copied = {'src/omr_model.py':ROOT/'src/omr_model.py', 'src/omr_retrain.py':ROOT/'src/omr_retrain.py',
              'baseline_row_cnn.pt':ROOT/'models/row_cnn.pt', 'baseline_config.json':ROOT/'models/model_config.json'}
    for name, source in copied.items():
        destination = output/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    report = {'final_dataset_pairs':270, 'purpose':'confirmed-partial-label-finetuning',
        'confirmed_questions_by_split':dict(Counter(r['split'] for r in selected)),
        'crop_rows_by_split':dict(Counter(split_values)),
        'sheets_by_split':{s:len({r['sheet_id'] for r in selected if r['split']==s}) for s in ('train','validation','test')},
        'classes_by_split':{s:dict(Counter(r['ground_truth'] for r in selected if r['split']==s)) for s in ('train','validation','test')},
        'frozen_test_sheets':sorted(test_sheets), 'test_used_for_model_selection':False,
        'omr_or_cnn_drafts_used_as_targets':0, 'independent_evaluation':False,
        'annotation_mode':'human_inspected_omr_assisted', 'source_sha256':before,
        'geometry_sha256':geometry_hash,'source_images':len(images), 'all_source_images_registered':True,
        'explicit_compatible_geometry_versions':args.compatible_cache_geometry,
        'reused_compatible_images':sum('cache_reused_from_geometry_sha256' in r for r in registrations),
        'registration_modes':dict(Counter(r['registration']['mode'] for r in registrations))}
    report['package_sha256'] = {n:sha(output/n) for n in ['confirmed_rows.npz', *copied]}
    (output/'preflight.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    assert before == {p.relative_to(ROOT).as_posix():sha(p) for p in protected}, 'Canonical files changed during preparation.'
    with zipfile.ZipFile(output/'omr_retraining_v2.zip','w') as archive:
        for name in ['confirmed_rows.npz','preflight.json',*copied]:
            archive.write(output/name,name,compress_type=zipfile.ZIP_STORED if name.endswith(('.npz','.pt')) else zipfile.ZIP_DEFLATED)
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)


if __name__ == '__main__':
    main()

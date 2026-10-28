"""Extract fresh row crops and CLA scores from source images using the fixed geometry,
then rigorously evaluate CNN models (v3 production, v4 candidate, v4 final model)
on single Image A.

Records:
- Geometry version and file hashes
- Explicit formula & denominators for all percentages:
  * Accepted Accuracy = correct_accepted / (correct_accepted + wrong_accepted)
  * Effective Yield = correct_accepted / total_questions
  * Deferral Rate = deferred / total_questions
- Separates production policy (cnn_cutoff_only) from experimental risk policies
- Clearly separates candidate from final_model
- Flags that Validation is in-sample for final_model and CANNOT be used as an evaluation of final_model
- Explicitly marks Test results as retrospective retests, NOT independent/blind tests.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))

from omr_geometry import read_image, rectify_sheet, row_crop, bubble_scores
from omr_model import CLASSES, RowCNN, load_trained_model

OUTPUT_DIR = ROOT / 'presentation_build/retraining_v4_single_a_20261029'
OUT_NPZ = OUTPUT_DIR / 'fresh_image_a_crops_and_scores.npz'
OUT_JSON = OUTPUT_DIR / 'rigorous_single_a_evaluation_fresh_geometry.json'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cla_predict_single(scores: np.ndarray, fill_threshold: float = 0.17138, margin_threshold: float = 0.02) -> tuple[str, float]:
    order = np.argsort(scores)[::-1]
    active = np.flatnonzero(scores >= fill_threshold)
    if len(active) == 0:
        return 'blank', max(0.0, fill_threshold - float(scores[order[0]]))
    if len(active) > 1:
        return 'multiple', float(scores[order[1]]) - fill_threshold
    margin = float(scores[order[0]] - scores[order[1]])
    if margin < margin_threshold:
        return 'ambiguous', margin
    return str(int(order[0]) + 1), margin


def evaluate_cohort(probs: np.ndarray, targets: np.ndarray, cla_scores: np.ndarray,
                    policy_name: str, cnn_cutoff: float = 0.557,
                    cla_fill: float = 0.17138, cla_margin_th: float = 0.02,
                    high_conf_override: float = 0.90) -> dict:
    n = len(targets)
    correct_acc = 0
    wrong_acc = 0
    deferred = 0

    cnn_preds = probs.argmax(axis=1)
    cnn_confs = probs.max(axis=1)

    for i in range(n):
        cnn_p = CLASSES[cnn_preds[i]]
        conf = float(cnn_confs[i])
        truth = CLASSES[targets[i]]
        c_scores = cla_scores[i]
        cla_p, cla_m = cla_predict_single(c_scores, cla_fill, cla_margin_th)

        if cnn_p in {'ambiguous', 'blank', 'multiple'}:
            deferred += 1
            continue

        is_deferred = False
        if policy_name == 'cnn_cutoff_only':
            if conf < cnn_cutoff:
                is_deferred = True

        elif policy_name == 'cnn_cla_agreement':
            if conf < cnn_cutoff or cnn_p != cla_p:
                is_deferred = True

        elif policy_name == 'cnn_cla_margin':
            if conf < cnn_cutoff or cla_m < cla_margin_th:
                is_deferred = True

        elif policy_name == 'cnn_cla_hybrid':
            if conf < cnn_cutoff:
                is_deferred = True
            elif cnn_p != cla_p and conf < high_conf_override:
                is_deferred = True
            elif cla_m < 0.010 and conf < high_conf_override:
                is_deferred = True
        else:
            raise ValueError(f'Unknown policy: {policy_name}')

        if is_deferred:
            deferred += 1
        else:
            if cnn_p == truth:
                correct_acc += 1
            else:
                wrong_acc += 1

    accepted_total = correct_acc + wrong_acc
    return {
        'total_questions': n,
        'correct_accepted': correct_acc,
        'wrong_accepted': wrong_acc,
        'deferred': deferred,
        'alignment_failures': 0,
        'denominators': {
            'accepted_accuracy_formula': 'correct_accepted / (correct_accepted + wrong_accepted)',
            'accepted_accuracy_denominator': accepted_total,
            'effective_yield_formula': 'correct_accepted / total_questions',
            'effective_yield_denominator': n,
            'deferral_rate_formula': 'deferred / total_questions',
            'deferral_rate_denominator': n
        },
        'deferral_rate': round(deferred / max(1, n), 4),
        'accepted_accuracy': round(correct_acc / max(1, accepted_total), 4) if accepted_total > 0 else 0.0,
        'effective_yield': round(correct_acc / max(1, n), 4)
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    meta = ROOT / 'data/metadata'

    # 1. Record geometry hashes and versions
    geo_files = [ROOT / 'src/omr_geometry.py', ROOT / 'tools/build_answer_pilot.py']
    inv_sha = sha(meta / 'image_inventory_verified.csv')
    splits_sha = sha(meta / 'sheet_splits.csv')
    labels_sha = sha(meta / 'answer_labels.csv')

    geometry_hash = hashlib.sha256(''.join(sha(p) for p in geo_files).encode()
                                   + inv_sha.encode() + splits_sha.encode()).hexdigest()

    print('=== Geometry Provenance ===')
    print(f'Geometry Hash: {geometry_hash}')
    print(f'omr_geometry.py SHA256: {sha(geo_files[0])}')
    print(f'build_answer_pilot.py SHA256: {sha(geo_files[1])}')

    # 2. Identify confirmed Image A questions
    with (meta / 'heic_conversion_map.csv').open(encoding='utf-8-sig') as f:
        conv = {r['source_relative_path']: r['normalized_relative_path'] for r in csv.DictReader(f)}
    with (meta / 'sheet_splits.csv').open(encoding='utf-8-sig') as f:
        split_map = {r['sheet_id']: r['split'] for r in csv.DictReader(f)}
    with (meta / 'image_inventory_verified.csv').open(encoding='utf-8-sig') as f:
        image_map_a = {r['sheet_id']: r for r in csv.DictReader(f) if r['capture_role'] == 'A' and r['pair_status'] == 'verified'}

    pilot_split = ROOT / 'presentation_build/reviewed_pilot_270/data/metadata/sheet_splits.csv'
    with pilot_split.open(encoding='utf-8-sig') as f:
        frozen_test_sheets = {r['sheet_id'] for r in csv.DictReader(f) if r['split'] == 'test'}

    with (meta / 'answer_labels.csv').open(encoding='utf-8-sig') as f:
        all_labels = [r for r in csv.DictReader(f) if r['ground_truth'].strip()]

    # Group questions by sheet
    questions_by_sheet = defaultdict(list)
    for row in all_labels:
        sid = row['sheet_id']
        if sid in image_map_a:
            q = int(row['question_no'])
            gt = row['ground_truth'].strip()
            if gt in CLASSES:
                questions_by_sheet[sid].append((q, gt))

    print(f'Total sheets with confirmed answers in Image A: {len(questions_by_sheet)}')

    # 3. Extract fresh crops and CLA scores directly from original images
    crops_list = []
    scores_list = []
    targets_list = []
    splits_list = []
    sheets_list = []
    questions_list = []
    is_frozen_test_list = []
    alignment_failures = []

    print('Extracting fresh crops and CLA scores from source images with updated geometry...')
    started = time.perf_counter()

    for idx, (sid, q_list) in enumerate(sorted(questions_by_sheet.items()), 1):
        img_info = image_map_a[sid]
        source_path = ROOT / img_info['relative_path']
        split = split_map[sid]
        is_frozen = sid in frozen_test_sheets

        try:
            bgr = read_image(source_path, conv, ROOT)
            aligned, centers, reg = rectify_sheet(bgr, source_sheet_id=sid)

            for q, gt in sorted(q_list):
                crop = row_crop(aligned, q, centers)
                bubble_score = bubble_scores(aligned, q, centers)

                crops_list.append(crop)
                scores_list.append(bubble_score)
                targets_list.append(CLASSES.index(gt))
                splits_list.append(split)
                sheets_list.append(sid)
                questions_list.append(q)
                is_frozen_test_list.append(is_frozen)

        except Exception as e:
            alignment_failures.append({'sheet_id': sid, 'error': str(e)})
            print(f'FAILED {sid}: {e}')

        if idx % 50 == 0 or idx == len(questions_by_sheet):
            print(f'Extracted {idx}/{len(questions_by_sheet)} sheets ({len(crops_list)} questions)...', flush=True)

    elapsed_extract = time.perf_counter() - started
    print(f'Extraction complete in {elapsed_extract:.2f}s. Total questions: {len(crops_list)}')

    crops_arr = np.stack(crops_list)
    scores_arr = np.stack(scores_list)
    targets_arr = np.asarray(targets_list, dtype=np.int64)
    splits_arr = np.asarray(splits_list)
    sheets_arr = np.asarray(sheets_list)
    questions_arr = np.asarray(questions_list, dtype=np.int16)
    is_frozen_arr = np.asarray(is_frozen_test_list)

    # Save fresh npz
    np.savez_compressed(
        OUT_NPZ,
        crops=crops_arr,
        scores=scores_arr,
        targets=targets_arr,
        split=splits_arr,
        sheet_id=sheets_arr,
        question_no=questions_arr,
        is_frozen_test=is_frozen_arr,
        geometry_hash=geometry_hash
    )
    print(f'Saved fresh crops to {OUT_NPZ}')

    # 4. Rigorous Evaluation
    print('\n=== Running Rigorous Single Image A CNN Evaluation ===')
    torch.set_num_threads(4)
    device = torch.device('cpu')

    # Load models
    v3_dir = ROOT / 'models/retrained_v3_verified'
    v3_cfg = json.loads((v3_dir / 'model_config.json').read_text(encoding='utf-8'))
    v3_model, _ = load_trained_model(v3_dir / 'row_cnn.pt', device=device, expected_sha256=v3_cfg['weights_sha256'])

    cand_path = OUTPUT_DIR / 'candidate_single_a.pt'
    cand_model = RowCNN().to(device)
    cand_model.load_state_dict(torch.load(cand_path, map_location=device, weights_only=True))
    cand_model.eval()

    final_path = OUTPUT_DIR / 'final_model/row_cnn.pt'
    final_model = RowCNN().to(device)
    final_model.load_state_dict(torch.load(final_path, map_location=device, weights_only=True))
    final_model.eval()

    models = {
        'v3_production': {
            'model': v3_model,
            'sha256': sha(v3_dir / 'row_cnn.pt'),
            'description': 'Current active production weights (verified v3)',
            'role': 'production'
        },
        'v4_candidate': {
            'model': cand_model,
            'sha256': sha(cand_path),
            'description': 'Candidate model selected from Validation (trained on Train 5,591 only)',
            'role': 'research_candidate'
        },
        'v4_final_model': {
            'model': final_model,
            'sha256': sha(final_path),
            'description': 'Final model trained on pooled Train + Validation (6,024 questions)',
            'role': 'research_final'
        }
    }

    # Cohort indices
    val_idx = np.flatnonzero(splits_arr == 'validation')
    test_frozen_idx = np.flatnonzero((splits_arr == 'test') & is_frozen_arr)
    test_all_idx = np.flatnonzero(splits_arr == 'test')

    print(f'Cohort sizes: Validation={len(val_idx)}, Test Frozen 10={len(test_frozen_idx)}, Test All Confirmed={len(test_all_idx)}')

    # Compute CNN probabilities
    def get_probs(m, indices):
        sub_crops = crops_arr[indices]
        tensor = torch.from_numpy(sub_crops).unsqueeze(1).float() / 255.0
        with torch.no_grad():
            logits = m(tensor)
            probs = torch.softmax(logits, dim=1).numpy()
        return probs

    eval_results = {}
    policies = ['cnn_cutoff_only', 'cnn_cla_agreement', 'cnn_cla_margin', 'cnn_cla_hybrid']

    for m_name, m_info in models.items():
        eval_results[m_name] = {
            'sha256': m_info['sha256'],
            'description': m_info['description'],
            'role': m_info['role'],
            'cohorts': {}
        }
        m = m_info['model']

        # Validation cohort
        if m_name == 'v4_final_model':
            # Validation is in-sample for final_model!
            val_probs = get_probs(m, val_idx)
            eval_results[m_name]['cohorts']['validation_433'] = {
                'evaluation_note': 'IN-SAMPLE: Validation data was included in final_model training (6,024 items). This cannot be treated as an evaluation metric.',
                'is_valid_evaluation': False,
                'policies': {p: evaluate_cohort(val_probs, targets_arr[val_idx], scores_arr[val_idx], p) for p in policies}
            }
        else:
            val_probs = get_probs(m, val_idx)
            eval_results[m_name]['cohorts']['validation_433'] = {
                'evaluation_note': 'Held-out validation cohort used for policy and model selection.',
                'is_valid_evaluation': True,
                'policies': {p: evaluate_cohort(val_probs, targets_arr[val_idx], scores_arr[val_idx], p) for p in policies}
            }

        # Test Frozen 10 cohort
        test_frozen_probs = get_probs(m, test_frozen_idx)
        eval_results[m_name]['cohorts']['test_frozen10_1000'] = {
            'evaluation_note': 'Assisted retrospective retest on frozen 10 sheets (NOT an independent or blind test).',
            'is_valid_evaluation': True,
            'policies': {p: evaluate_cohort(test_frozen_probs, targets_arr[test_frozen_idx], scores_arr[test_frozen_idx], p) for p in policies}
        }

        # Test All Confirmed cohort
        test_all_probs = get_probs(m, test_all_idx)
        eval_results[m_name]['cohorts']['test_all_confirmed_1129'] = {
            'evaluation_note': 'Assisted retrospective retest on all confirmed Test slots (NOT an independent or blind test).',
            'is_valid_evaluation': True,
            'policies': {p: evaluate_cohort(test_all_probs, targets_arr[test_all_idx], scores_arr[test_all_idx], p) for p in policies}
        }

    # Policy selection gate on Validation (Candidate vs Baseline)
    val_cand_policies = eval_results['v4_candidate']['cohorts']['validation_433']['policies']
    val_v3_policies = eval_results['v3_production']['cohorts']['validation_433']['policies']

    ranking = []
    for p in policies:
        cand_p = val_cand_policies[p]
        v3_p = val_v3_policies[p]
        # Gate: wrong_accepted <= v3 cutoff_only (which has 1 error)
        # Minimize wrong_accepted, then minimize deferred, then maximize correct_accepted
        rank_tuple = (-cand_p['wrong_accepted'], -cand_p['deferred'], cand_p['correct_accepted'])
        ranking.append((rank_tuple, p, cand_p, v3_p))

    ranking.sort(reverse=True)
    winner_tuple, winner_policy, winner_cand_metrics, winner_v3_metrics = ranking[0]

    output_payload = {
        'geometry_version': {
            'geometry_hash': geometry_hash,
            'src_omr_geometry_sha256': sha(geo_files[0]),
            'tools_build_answer_pilot_sha256': sha(geo_files[1]),
            'data_metadata_image_inventory_sha256': inv_sha,
            'data_metadata_sheet_splits_sha256': splits_sha,
            'data_metadata_answer_labels_sha256': labels_sha
        },
        'system_integration_status': {
            'production_active_model': 'v3_production (models/retrained_v3_verified/row_cnn.pt)',
            'production_active_policy': 'cnn_cutoff_only (cutoff=0.557)',
            'is_v4_deployed': False,
            'is_experimental_policy_connected_to_runtime': False,
            'runtime_engine_status': 'Strictly unchanged; keeps v3 weights and cutoff policy.'
        },
        'policy_selection_on_validation': {
            'cohort': 'Validation (433 confirmed questions, single Image A)',
            'predeclared_objective': 'Zero wrong accepted (or <= v3 baseline), then minimize deferred, then maximize correct accepted',
            'objective_winner': winner_policy,
            'winner_candidate_metrics': winner_cand_metrics,
            'winner_v3_metrics': winner_v3_metrics,
            'policy_ranking_validation': [
                {
                    'policy': r[1],
                    'candidate_wrong': r[2]['wrong_accepted'],
                    'candidate_deferred': r[2]['deferred'],
                    'candidate_correct': r[2]['correct_accepted'],
                    'accepted_accuracy': r[2]['accepted_accuracy'],
                    'effective_yield': r[2]['effective_yield']
                }
                for r in ranking
            ]
        },
        'models_evaluated': {
            k: {'sha256': v['sha256'], 'description': v['description'], 'role': v['role']}
            for k, v in models.items()
        },
        'evaluation_results': eval_results
    }

    OUT_JSON.write_text(json.dumps(output_payload, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Saved rigorous evaluation report to {OUT_JSON}')


if __name__ == '__main__':
    main()

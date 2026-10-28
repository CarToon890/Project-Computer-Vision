"""Train and evaluate CNN for single-image A OMR, comparing against v3.

Key features:
1. Uses ONLY confirmed human labels (5,591 Train questions, 433 Validation, 1,129 Test).
2. Preserves existing Train/Validation/Test splits; keeps A/B of each sheet in the same split.
3. Evaluates and selects candidate models and risk routing policies strictly on Validation.
4. Experiments with CNN confidence combined with CLA agreement and bubble-level margin to route risky questions to human review.
5. Measures: ข้อถูก (correct accepted), ข้อผิดที่ยอมรับ (wrong accepted), and ข้อรอตรวจ (deferred).
6. Trains the final candidate and records all evaluation metrics on Image A.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from omr_model import CLASSES, RowCNN, load_trained_model
from omr_retrain import augment_train, probabilities, sha, validate_rows

V3_DIR = ROOT / 'models/retrained_v3_verified'
OUT_DEFAULT = ROOT / 'presentation_build/retraining_v4_single_a_20261029'
MODEL_OUT = ROOT / 'models/retrained_v4_single_a'


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


def evaluate_single_a(probs: np.ndarray, targets: np.ndarray, cla_scores: np.ndarray,
                      policy_name: str, cnn_cutoff: float = 0.557,
                      cla_fill: float = 0.17138, cla_margin_th: float = 0.02,
                      high_conf_override: float = 0.90) -> dict:
    """Evaluates Image A predictions under a specific risk routing policy."""
    n = len(targets)
    correct_acc = 0
    wrong_acc = 0
    deferred = 0

    cnn_preds = probs.argmax(axis=1)
    cnn_confs = probs.max(axis=1)

    for i in range(n):
        pred_idx = cnn_preds[i]
        cnn_p = CLASSES[pred_idx]
        conf = float(cnn_confs[i])
        truth = CLASSES[targets[i]]
        c_scores = cla_scores[i]
        cla_p, cla_m = cla_predict_single(c_scores, cla_fill, cla_margin_th)

        # Baseline: ambiguous, blank, multiple in CNN are intrinsically risky
        if cnn_p in {'ambiguous', 'blank', 'multiple'}:
            deferred += 1
            continue

        is_deferred = False

        if policy_name == 'cnn_cutoff_only':
            if conf < cnn_cutoff:
                is_deferred = True

        elif policy_name == 'cnn_cla_agreement':
            # Must meet CNN cutoff AND agree with CLA prediction
            if conf < cnn_cutoff or cnn_p != cla_p:
                is_deferred = True

        elif policy_name == 'cnn_cla_margin':
            # Must meet CNN cutoff AND have solid bubble contrast margin in CLA
            if conf < cnn_cutoff or cla_m < cla_margin_th:
                is_deferred = True

        elif policy_name == 'cnn_cla_hybrid':
            # Accept if conf >= cutoff AND (agrees with CLA OR has very high CNN conf) AND CLA has basic contrast
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

    return {
        'questions': n,
        'correct_accepted': correct_acc,
        'wrong_accepted': wrong_acc,
        'deferred': deferred,
        'deferral_rate': round(deferred / max(1, n), 4),
        'accuracy_accepted': round(correct_acc / max(1, correct_acc + wrong_acc), 4)
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=OUT_DEFAULT)
    parser.add_argument('--epochs', type=int, default=6)
    parser.add_argument('--lr', type=float, default=3e-5)
    parser.add_argument('--seed', type=int, default=20261029)
    args = parser.parse_args()

    out_dir = args.output
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Source and Data checks
    source_dir = ROOT / 'presentation_build/retraining_v3_20261028/input'
    package = source_dir / 'confirmed_rows.npz'
    report = json.loads((source_dir / 'preflight.json').read_text(encoding='utf-8'))

    with np.load(package, allow_pickle=False) as z:
        data = {k: z[k] for k in z.files}
    validate_rows(data, report)

    v3_cfg = json.loads((V3_DIR / 'model_config.json').read_text(encoding='utf-8'))
    cutoff = v3_cfg['cnn_confidence_cutoff']

    # 2. Filter Indices
    train_idx = np.flatnonzero(data['split'] == 'train')
    val_a_idx = np.flatnonzero((data['split'] == 'validation') & (data['capture_role'] == 'A'))
    test_a_idx = np.flatnonzero((data['split'] == 'test') & (data['capture_role'] == 'A'))

    # Frozen 10 test sheets (Image A)
    frozen_test_sheets = set(report['frozen_test_sheets'])
    test_a_frozen10_idx = np.flatnonzero(
        (data['split'] == 'test') & (data['capture_role'] == 'A') & np.isin(data['sheet_id'], list(frozen_test_sheets))
    )

    print(f'Train crops count: {len(train_idx)} (from {len(train_idx)//2} confirmed questions)')
    print(f'Validation Image A count: {len(val_a_idx)} questions')
    print(f'Test Image A count: {len(test_a_idx)} questions (Frozen 10: {len(test_a_frozen10_idx)} questions)')

    # Reproducibility
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(4)

    # 3. Load v3 model
    v3_model, device = load_trained_model(V3_DIR / 'row_cnn.pt', expected_sha256=v3_cfg['weights_sha256'])

    # Evaluate v3 baseline on Validation Image A
    v3_val_probs = probabilities(v3_model, data['crops'][val_a_idx], device)
    v3_val_targets = data['targets'][val_a_idx]
    v3_val_cla = data['cla_scores'][val_a_idx]

    policies = ['cnn_cutoff_only', 'cnn_cla_agreement', 'cnn_cla_margin', 'cnn_cla_hybrid']
    v3_val_metrics = {pol: evaluate_single_a(v3_val_probs, v3_val_targets, v3_val_cla, pol, cutoff) for pol in policies}
    print('\n=== Baseline v3 on Validation (Image A) ===')
    for pol, m in v3_val_metrics.items():
        print(f'  {pol:20s}: correct={m["correct_accepted"]}, wrong={m["wrong_accepted"]}, deferred={m["deferred"]}')

    # 4. Train Candidate CNN
    candidate_model = copy.deepcopy(v3_model)
    counts = np.bincount(data['targets'][train_idx], minlength=len(CLASSES))
    weights = np.ones(len(CLASSES), dtype=np.float32)
    weights[counts > 0] = np.minimum(np.sqrt(counts.max() / counts[counts > 0]), 8.0)
    criterion = nn.CrossEntropyLoss(weight=torch.tensor(weights, device=device))
    optimizer = torch.optim.Adam(candidate_model.parameters(), lr=args.lr)

    train_dataset = TensorDataset(
        torch.from_numpy(data['crops'][train_idx, None].astype(np.float32) / 255.0),
        torch.from_numpy(data['targets'][train_idx])
    )
    train_loader = DataLoader(train_dataset, batch_size=128, shuffle=True, generator=torch.Generator().manual_seed(args.seed))

    best_state = copy.deepcopy(candidate_model.state_dict())
    best_epoch = 0
    best_policy = 'cnn_cla_hybrid'
    best_score = (-v3_val_metrics[best_policy]['wrong_accepted'], -v3_val_metrics[best_policy]['deferred'], v3_val_metrics[best_policy]['correct_accepted'])
    history = []

    print('\n=== Training Candidate CNN (epochs=1..%d) ===' % args.epochs)
    for epoch in range(1, args.epochs + 1):
        candidate_model.train()
        epoch_loss = 0.0
        for x_b, y_b in train_loader:
            x_b, y_b = x_b.to(device), y_b.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(candidate_model(augment_train(x_b)), y_b)
            loss.backward()
            nn.utils.clip_grad_norm_(candidate_model.parameters(), 5.0)
            optimizer.step()
            epoch_loss += float(loss.detach()) * len(x_b)

        epoch_loss /= len(train_dataset)

        # Evaluate on Validation Image A
        val_probs = probabilities(candidate_model, data['crops'][val_a_idx], device)
        epoch_val_metrics = {pol: evaluate_single_a(val_probs, v3_val_targets, v3_val_cla, pol, cutoff) for pol in policies}
        history.append({'epoch': epoch, 'loss': epoch_loss, 'validation': epoch_val_metrics})

        print(f'Epoch {epoch:2d} (loss={epoch_loss:.4f}):')
        for pol, m in epoch_val_metrics.items():
            print(f'    {pol:20s}: correct={m["correct_accepted"]}, wrong={m["wrong_accepted"]}, deferred={m["deferred"]}')

        # Selection gate: wrong_accepted must be <= v3, maximize rank
        hybrid_m = epoch_val_metrics['cnn_cla_hybrid']
        score = (-hybrid_m['wrong_accepted'], -hybrid_m['deferred'], hybrid_m['correct_accepted'])
        if score > best_score:
            best_score = score
            best_epoch = epoch
            best_state = copy.deepcopy(candidate_model.state_dict())
            print(f'    >>> Selected new best candidate at epoch {epoch}!')

    # If epoch 0 (baseline) was better or equal, record choice
    chosen_epoch = best_epoch if best_epoch > 0 else 0
    candidate_model.load_state_dict(best_state)

    # 5. Save candidate weights
    torch.save(best_state, out_dir / 'candidate_single_a.pt')

    # 6. Full Evaluation on Validation and Test (Image A only)
    val_probs_best = probabilities(candidate_model, data['crops'][val_a_idx], device)
    test_probs_best = probabilities(candidate_model, data['crops'][test_a_idx], device)
    test_probs_v3 = probabilities(v3_model, data['crops'][test_a_idx], device)

    test_targets = data['targets'][test_a_idx]
    test_cla = data['cla_scores'][test_a_idx]

    frozen_mask_in_test = np.isin(data['sheet_id'][test_a_idx], list(frozen_test_sheets))

    final_eval = {
        'target_workflow': 'Image A Only (ภาพ A เพียงภาพเดียว)',
        'baseline_model': 'v3',
        'selected_epoch': chosen_epoch,
        'selected_policy': best_policy,
        'selection_dataset': 'Validation (433 confirmed questions, Image A)',
        'test_used_for_selection': False,
        'training_epochs': args.epochs,
        'learning_rate': args.lr,
        'seed': args.seed,
        'validation_comparison': {
            'v3': v3_val_metrics,
            'v4_candidate': {pol: evaluate_single_a(val_probs_best, v3_val_targets, v3_val_cla, pol, cutoff) for pol in policies}
        },
        'test_all_confirmed_1129': {
            'v3': {pol: evaluate_single_a(test_probs_v3, test_targets, test_cla, pol, cutoff) for pol in policies},
            'v4_candidate': {pol: evaluate_single_a(test_probs_best, test_targets, test_cla, pol, cutoff) for pol in policies}
        },
        'test_frozen_ten_sheets_1000': {
            'v3': {pol: evaluate_single_a(test_probs_v3[frozen_mask_in_test], test_targets[frozen_mask_in_test], test_cla[frozen_mask_in_test], pol, cutoff) for pol in policies},
            'v4_candidate': {pol: evaluate_single_a(test_probs_best[frozen_mask_in_test], test_targets[frozen_mask_in_test], test_cla[frozen_mask_in_test], pol, cutoff) for pol in policies}
        },
        'training_history': history
    }

    eval_path = out_dir / 'evaluation_single_a.json'
    eval_path.write_text(json.dumps(final_eval, indent=2), encoding='utf-8')
    print(f'\nWrote evaluation results to {eval_path}')

    # Print clean summary table
    print('\n==================== FINAL RESULTS SUMMARY (IMAGE A) ====================')
    print(f'Selected Model: Epoch {chosen_epoch} with policy "{best_policy}"')
    print('\n[Validation Cohort - 433 questions]:')
    for m_name, metrics in [('v3 Baseline', v3_val_metrics[best_policy]), ('v4 Selected', final_eval['validation_comparison']['v4_candidate'][best_policy])]:
        print(f'  {m_name:15s}: Correct={metrics["correct_accepted"]} | Wrong={metrics["wrong_accepted"]} | Deferred={metrics["deferred"]} (Accuracy: {metrics["accuracy_accepted"]*100:.2f}%)')

    print('\n[Test Cohort (Frozen 10 sheets - 1,000 questions)] (Assisted Retest):')
    v3_t10 = final_eval['test_frozen_ten_sheets_1000']['v3'][best_policy]
    v4_t10 = final_eval['test_frozen_ten_sheets_1000']['v4_candidate'][best_policy]
    print(f'  {"v3 Baseline":15s}: Correct={v3_t10["correct_accepted"]} | Wrong={v3_t10["wrong_accepted"]} | Deferred={v3_t10["deferred"]} (Accuracy: {v3_t10["accuracy_accepted"]*100:.2f}%)')
    print(f'  {"v4 Selected":15s}: Correct={v4_t10["correct_accepted"]} | Wrong={v4_t10["wrong_accepted"]} | Deferred={v4_t10["deferred"]} (Accuracy: {v4_t10["accuracy_accepted"]*100:.2f}%)')

    print('\n[Test Cohort (All Confirmed - 1,129 questions)] (Assisted Retest):')
    v3_tall = final_eval['test_all_confirmed_1129']['v3'][best_policy]
    v4_tall = final_eval['test_all_confirmed_1129']['v4_candidate'][best_policy]
    print(f'  {"v3 Baseline":15s}: Correct={v3_tall["correct_accepted"]} | Wrong={v3_tall["wrong_accepted"]} | Deferred={v3_tall["deferred"]} (Accuracy: {v3_tall["accuracy_accepted"]*100:.2f}%)')
    print(f'  {"v4 Selected":15s}: Correct={v4_tall["correct_accepted"]} | Wrong={v4_tall["wrong_accepted"]} | Deferred={v4_tall["deferred"]} (Accuracy: {v4_tall["accuracy_accepted"]*100:.2f}%)')


if __name__ == '__main__':
    main()

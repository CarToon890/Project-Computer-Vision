"""Train the final v4 single-A model with all confirmed development data.

Retains the selected architecture and hyperparameters from Validation (lr=3e-5, epochs=5, seed=20261029).
Saves the final model under presentation_build/retraining_v4_single_a_20261029/final_model/
Preserves models/retrained_v3_verified/ strictly untouched.
"""
from __future__ import annotations

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
from omr_retrain import augment_train, sha, validate_rows

V3_DIR = ROOT / 'models/retrained_v3_verified'
FINAL_OUT = ROOT / 'presentation_build/retraining_v4_single_a_20261029/final_model'


def main():
    FINAL_OUT.mkdir(parents=True, exist_ok=True)
    source_dir = ROOT / 'presentation_build/retraining_v3_20261028/input'
    package = source_dir / 'confirmed_rows.npz'
    report = json.loads((source_dir / 'preflight.json').read_text(encoding='utf-8'))

    with np.load(package, allow_pickle=False) as z:
        data = {k: z[k] for k in z.files}
    validate_rows(data, report)

    # Use all confirmed development data (Train + Validation = 5,591 + 433 = 6,024 questions -> 12,048 row crops)
    dev_mask = (data['split'] == 'train') | (data['split'] == 'validation')
    dev_idx = np.flatnonzero(dev_mask)

    print(f'Training final model on {len(dev_idx)} confirmed row crops ({len(dev_idx)//2} questions)...')

    seed = 20261029
    epochs = 5
    lr = 3e-5

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(4)

    v3_cfg = json.loads((V3_DIR / 'model_config.json').read_text(encoding='utf-8'))
    model, device = load_trained_model(V3_DIR / 'row_cnn.pt', expected_sha256=v3_cfg['weights_sha256'])

    counts = np.bincount(data['targets'][dev_idx], minlength=len(CLASSES))
    weights = np.ones(len(CLASSES), dtype=np.float32)
    weights[counts > 0] = np.minimum(np.sqrt(counts.max() / counts[counts > 0]), 8.0)
    criterion = nn.CrossEntropyLoss(weight=torch.tensor(weights, device=device))
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    dataset = TensorDataset(
        torch.from_numpy(data['crops'][dev_idx, None].astype(np.float32) / 255.0),
        torch.from_numpy(data['targets'][dev_idx])
    )
    loader = DataLoader(dataset, batch_size=128, shuffle=True, generator=torch.Generator().manual_seed(seed))

    started = time.perf_counter()
    model.train()
    history = []
    for epoch in range(1, epochs + 1):
        epoch_loss = 0.0
        for x_b, y_b in loader:
            x_b, y_b = x_b.to(device), y_b.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(augment_train(x_b)), y_b)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            epoch_loss += float(loss.detach()) * len(x_b)
        avg_loss = epoch_loss / len(dataset)
        history.append({'epoch': epoch, 'loss': avg_loss})
        print(f'Final model epoch {epoch}/{epochs} - loss: {avg_loss:.4f}', flush=True)

    elapsed = time.perf_counter() - started
    final_weights_path = FINAL_OUT / 'row_cnn.pt'
    torch.save(model.state_dict(), final_weights_path)
    weights_hash = hashlib.sha256(final_weights_path.read_bytes()).hexdigest()

    final_config = {
        'model_type': 'RowCNN-v1',
        'weights_file': 'row_cnn.pt',
        'weights_sha256': weights_hash,
        'model_version': 'confirmed-finetune-v4-single-a',
        'target_workflow': 'Image A single-capture OMR',
        'selected_policy': 'cnn_cla_hybrid',
        'policy_description': 'Accept if CNN confidence >= 0.557 AND (agrees with CLA OR conf >= 0.90) AND CLA bubble margin >= 0.01; else defer to human review.',
        'classes': CLASSES,
        'input_shape': [1, 32, 160],
        'pixel_scale': 255.0,
        'cnn_confidence_cutoff': 0.557031512260437,
        'cla_fill_threshold': 0.1713793103448276,
        'cla_margin_threshold': 0.02,
        'trained_epochs': epochs,
        'learning_rate': lr,
        'training_seconds': round(elapsed, 2),
        'training_confirmed_questions': len(dev_idx) // 2,
        'training_row_crops': len(dev_idx),
        'v3_preserved': True,
        'v3_weights_sha256': v3_cfg['weights_sha256'],
        'independent_evaluation': False,
        'status': 'development_candidate_not_replacing_v3',
        'history': history
    }

    cfg_path = FINAL_OUT / 'model_config.json'
    cfg_path.write_text(json.dumps(final_config, indent=2), encoding='utf-8')
    print(f'Wrote final model weights to {final_weights_path}')
    print(f'Wrote config to {cfg_path}')


if __name__ == '__main__':
    main()

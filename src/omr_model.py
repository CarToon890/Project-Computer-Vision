"""Row CNN architecture, weight loading and prediction without training dependencies."""
import hashlib
from pathlib import Path

import numpy as np
import torch
from torch import nn

CLASSES = ['1', '2', '3', '4', '5', 'blank', 'multiple', 'ambiguous']


class RowCNN(nn.Module):
    def __init__(self, num_classes=len(CLASSES)):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(), nn.AdaptiveAvgPool2d((4, 8)),
        )
        self.classifier = nn.Sequential(nn.Flatten(), nn.Linear(64*4*8, 128),
            nn.ReLU(), nn.Dropout(.25), nn.Linear(128, num_classes))

    def forward(self, x):
        return self.classifier(self.features(x))


def load_trained_model(path: Path, device=None, expected_sha256=None):
    if expected_sha256 and hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError('The model file does not match its recorded checksum.')
    device = torch.device(device or ('cuda' if torch.cuda.is_available() else 'cpu'))
    state = torch.load(path, map_location=device, weights_only=True)
    if not isinstance(state, dict) or not all(isinstance(v, torch.Tensor) for v in state.values()):
        raise ValueError('Expected a tensor-only RowCNN state dictionary.')
    if not all(torch.isfinite(v).all().item() for v in state.values()):
        raise ValueError('Model contains nonfinite weights.')
    model = RowCNN().to(device)
    model.load_state_dict(state, strict=True)
    model.eval()
    return model, device


def predict_cnn(model, crops, device, batch_size=512):
    if len(crops) == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float32)
    if crops.ndim != 3 or crops.shape[1:] != (32, 160):
        raise ValueError('CNN input must have shape (N, 32, 160).')
    model.eval()
    all_probs = []
    with torch.inference_mode():
        for start in range(0, len(crops), batch_size):
            batch = torch.from_numpy(crops[start:start+batch_size, None].astype(np.float32)/255.).to(device)
            all_probs.append(torch.softmax(model(batch), dim=1).cpu().numpy())
    probs = np.concatenate(all_probs)
    return probs.argmax(axis=1), probs.max(axis=1)

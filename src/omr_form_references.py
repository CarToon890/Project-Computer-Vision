"""Portable registration features; no raw photographs or answer labels."""
import json
from pathlib import Path

import cv2
import numpy as np


def encode_keys(keys):
    return np.asarray([[*k.pt, k.size, k.angle, k.response, k.octave, k.class_id]
                       for k in keys], dtype=np.float64).reshape(-1, 7)


def decode_reference(archive, prefix):
    centers = archive[prefix + '_centers']
    points = archive[prefix + '_keys']
    descriptors = archive[prefix + '_descriptors']
    if (centers.shape != (100, 5, 2) or points.ndim != 2 or points.shape[1] != 7
            or descriptors.shape != (len(points), 128) or not len(points)
            or not all(np.isfinite(a).all() for a in (centers, points, descriptors))):
        raise ValueError('Invalid portable form reference.')
    keys = [cv2.KeyPoint(float(x), float(y), float(size), float(angle),
                         float(response), int(octave), int(class_id))
            for x, y, size, angle, response, octave, class_id in points]
    return centers.tolist(), keys, descriptors.astype(np.float32)


def load_references(path: Path):
    with np.load(path, allow_pickle=False) as archive:
        metadata = json.loads(str(archive['metadata']))
        if metadata.get('version') != 1:
            raise ValueError('Unsupported portable form reference version.')
        primary = decode_reference(archive, 'primary')
        train = [(sid, *decode_reference(archive, f'train_{i}'))
                 for i, sid in enumerate(metadata['train_sheet_ids'])]
    return primary, train

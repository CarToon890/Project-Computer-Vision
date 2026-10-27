"""Run real v3 inference with packaged features and temporary output only."""
import argparse
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

try:
    import resource
except ImportError:  # The local baseline can also run on Windows.
    resource = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image-a', required=True, type=Path)
    parser.add_argument('--image-b', type=Path)
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'probe_manifest.json').read_text(encoding='utf-8'))
    for name, info in manifest['files'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != info['sha256']:
            raise ValueError(f'Bundle checksum mismatch: {name}')
    started = time.perf_counter()
    import cv2
    import torch
    from omr_model import load_trained_model
    from omr_inference import read_role
    from omr_runtime import build_methods
    torch.set_num_threads(2)
    model_dir = ROOT / 'models/retrained_v3_verified'
    config = json.loads((model_dir / 'model_config.json').read_text(encoding='utf-8'))
    model, device = load_trained_model(model_dir / config['weights_file'], device='cpu',
                                      expected_sha256=config['weights_sha256'])
    loaded = time.perf_counter()
    with tempfile.TemporaryDirectory() as folder:
        readings = {}
        for role, image in [('A', args.image_a), ('B', args.image_b)]:
            if image:
                readings[role] = read_role(model, device, image.resolve(), ROOT, {},
                                           Path(folder), None, role)
        methods, pair = build_methods(readings.get('A'), readings.get('B'), config, 'cloud-probe')
        print(json.dumps({'purpose': 'functional_feasibility_not_independent_accuracy',
            'model_version': config['model_version'], 'model_sha256': config['weights_sha256'],
            'torch_version': torch.__version__, 'opencv_version': cv2.__version__,
            'load_seconds': loaded - started, 'total_seconds': time.perf_counter() - started,
            'peak_rss_platform_units': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource else None,
            'question_count': len(methods['cnn']), 'pair_check': pair,
            'registration': {role: r['registration'] for role, r in readings.items()},
            'methods': methods, 'canonical_labels_written': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()

"""Build a private, local Linux feasibility bundle without shipping the dataset."""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from omr_geometry import reader, train_references
from omr_form_references import encode_keys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit('Existing bundle preserved. Choose a new output directory.')
    output.mkdir(parents=True)
    for name in ('src', 'tools', 'data/metadata', 'models/retrained_v3_verified'):
        (output / name).mkdir(parents=True, exist_ok=True)
    for name in ('omr_model', 'omr_geometry', 'omr_inference', 'omr_runtime', 'omr_form_references'):
        shutil.copy2(ROOT / 'src' / f'{name}.py', output / 'src')
    for name in ('build_answer_pilot', 'cloud_probe'):
        shutil.copy2(ROOT / 'tools' / f'{name}.py', output / 'tools')
    for name in ('row_cnn.pt', 'model_config.json'):
        shutil.copy2(ROOT / 'models/retrained_v3_verified' / name,
                     output / 'models/retrained_v3_verified')

    _, centers, keys, descriptors, _ = reader.registration_reference()
    train = train_references()
    if len(train) != 3:
        raise ValueError('Expected the same three Train references as the local pipeline.')
    arrays = {'primary_centers': np.asarray(centers), 'primary_keys': encode_keys(keys),
              'primary_descriptors': descriptors}
    for i, (_, centers, keys, descriptors) in enumerate(train):
        arrays.update({f'train_{i}_centers': np.asarray(centers),
                       f'train_{i}_keys': encode_keys(keys),
                       f'train_{i}_descriptors': descriptors})
    arrays['metadata'] = np.asarray(json.dumps({'version': 1,
        'train_sheet_ids': [item[0] for item in train]}))
    np.savez_compressed(output / 'data/metadata/form_references.npz', **arrays)
    for name in ('Dockerfile', 'requirements.txt'):
        shutil.copy2(ROOT / 'deploy/cloud-probe' / name, output / name)
    files = {p.relative_to(output).as_posix(): {'bytes': p.stat().st_size,
             'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(output.rglob('*')) if p.is_file()}
    report = {'status': 'local_feasibility_bundle_not_a_deployment',
              'model_version': 'confirmed-finetune-v3-risk-first',
              'raw_dataset_photos_included': False, 'answer_labels_included': False,
              'contains_private_reference_features': True,
              'total_bytes_without_dependencies': sum(f['bytes'] for f in files.values()),
              'files': files}
    (output / 'probe_manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(output), 'files': len(files),
                      'total_bytes_without_dependencies': report['total_bytes_without_dependencies']}, indent=2))


if __name__ == '__main__':
    main()

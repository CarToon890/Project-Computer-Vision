"""Stage the private FastAPI project and separate, checksummed model uploads."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    bundle, output = args.reference_bundle.resolve(), args.output.resolve()
    if output.exists():
        raise SystemExit('Existing deployment bundle preserved. Choose a new output path.')
    manifest = json.loads((bundle / 'probe_manifest.json').read_text(encoding='utf-8'))
    for name, info in manifest['files'].items():
        if hashlib.sha256((bundle / name).read_bytes()).hexdigest() != info['sha256']:
            raise SystemExit(f'Reference bundle checksum mismatch: {name}')
    engine = output / 'engine'
    shutil.copytree(ROOT / 'apps/engine', engine, ignore=shutil.ignore_patterns('__pycache__', '.env*', '.vercel', '.venv', '.agents', 'skills-lock.json'))
    shutil.copy2(ROOT / 'apps/engine/.env.example', engine / '.env.example')
    (engine / 'src').mkdir()
    (engine / 'tools').mkdir()
    for name in ('omr_model', 'omr_geometry', 'omr_inference', 'omr_runtime', 'omr_form_references'):
        shutil.copy2(ROOT / 'src' / f'{name}.py', engine / 'src')
    shutil.copy2(ROOT / 'tools/build_answer_pilot.py', engine / 'tools')
    uploads = output / 'system_upload'
    uploads.mkdir()
    files = {}
    for name, relative, destination in [
        ('config', 'models/retrained_v3_verified/model_config.json', 'model_config.json'),
        ('weights', 'models/retrained_v3_verified/row_cnn.pt', 'row_cnn.pt'),
        ('references', 'data/metadata/form_references.npz', 'form_references.npz')]:
        source = bundle / relative
        shutil.copy2(source, uploads / destination)
        files[name] = {'key': 'system/v3/' + destination,
                       'bytes': source.stat().st_size,
                       'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    model_manifest = json.dumps({'version': 1, 'files': files}, sort_keys=True, separators=(',', ':')).encode()
    (uploads / 'manifest.json').write_bytes(model_manifest)
    print(json.dumps({'engine_directory': str(engine),
                      'model_manifest_sha256': hashlib.sha256(model_manifest).hexdigest(),
                      'dataset_photos_included': False, 'ground_truth_included': False}, indent=2))


if __name__ == '__main__':
    main()

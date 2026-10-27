"""Package the reviewed pilot photos, metadata and code for one Kaggle upload."""
import csv
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / 'presentation_build/reviewed_pilot_270'
OUTPUT = ROOT / 'presentation_build/kaggle_reviewed_pilot'


def main():
    meta = PILOT / 'data/metadata'
    report = json.loads((PILOT / 'preflight.json').read_text(encoding='utf-8'))
    with (meta / 'image_inventory_verified.csv').open(encoding='utf-8-sig', newline='') as f:
        images = list(csv.DictReader(f))
    assert len(images) == report['pilot_images'] == 76
    assert report['pilot_sheets'] == 38 and report['pilot_human_labels'] == 3800
    assert report['omr_drafts_used_as_labels'] == 0
    files = {}
    photo_hashes = {}
    for row in images:
        source = (ROOT / row['relative_path']).resolve()
        if not source.is_relative_to(ROOT / 'Dataset-Computer-vision') or not source.is_file():
            raise ValueError(f'Missing or out-of-root pilot image: {source}')
        archive_name = row['relative_path']
        if archive_name in files:
            raise ValueError(f'Duplicate archive image path: {archive_name}')
        files[archive_name] = source
        photo_hashes[archive_name] = hashlib.sha256(source.read_bytes()).hexdigest()
    for name in ('image_inventory_verified.csv', 'answer_labels.csv', 'sheet_splits.csv', 'dataset_scope.json'):
        files['data/metadata/'+name] = meta / name
    files.update({'src/omr_pipeline.py': ROOT / 'src/omr_pipeline.py',
                  'src/omr_geometry.py': ROOT / 'src/omr_geometry.py',
                  'tools/build_answer_pilot.py': ROOT / 'tools/build_answer_pilot.py',
                  'requirements.txt': ROOT / 'requirements.txt',
                  'pilot_preflight.json': PILOT / 'preflight.json', 'README.md': PILOT / 'README.md'})
    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = OUTPUT / 'omr_reviewed_pilot.zip'
    temporary = target.with_suffix('.partial')
    with zipfile.ZipFile(temporary, 'w', allowZip64=True) as z:
        for name, source in files.items():
            z.write(source, name, compress_type=zipfile.ZIP_STORED if name in photo_hashes else zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(temporary) as z:
        assert z.testzip() is None
        assert set(z.namelist()) == set(files)
        for name, expected in photo_hashes.items():
            assert hashlib.sha256(z.read(name)).hexdigest() == expected
    temporary.replace(target)
    notebook = OUTPUT / 'omr_reviewed_pilot.ipynb'
    shutil.copy2(ROOT / 'notebooks/omr_reviewed_pilot.ipynb', notebook)
    package_report = {'final_dataset_pairs': 270, 'pilot_sheets': 38, 'pilot_images': 76,
                      'human_labels': 3800, 'draft_labels': 0, 'archive_files': len(files),
                      'zip_bytes': target.stat().st_size, 'all_original_photo_bytes_verified': True,
                      'upload_performed': False, 'models_trained': False,
                      'zip_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                      'notebook_sha256': hashlib.sha256(notebook.read_bytes()).hexdigest()}
    (OUTPUT / 'package_report.json').write_text(json.dumps(package_report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(package_report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

"""Compare identical local test images on current Windows runtime and Linux probe."""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from omr_inference import read_csv, read_role
from omr_model import load_trained_model
from omr_runtime import build_methods


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--image-tag', default='omr-v3-cloud-probe:matched-20261028')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit('Existing report preserved. Choose a new output directory.')
    output.mkdir(parents=True)
    samples = output / 'samples'
    samples.mkdir()
    inventory = read_csv(ROOT / 'data/metadata/image_inventory_verified.csv')
    conversions = {r['source_relative_path']: r['normalized_relative_path']
                   for r in read_csv(ROOT / 'data/metadata/heic_conversion_map.csv')}
    model_dir = ROOT / 'models/retrained_v3_verified'
    config = json.loads((model_dir / 'model_config.json').read_text(encoding='utf-8'))
    import torch
    torch.set_num_threads(2)
    started = time.perf_counter()
    model, device = load_trained_model(model_dir / config['weights_file'], device='cpu',
                                      expected_sha256=config['weights_sha256'])
    report = {'purpose': 'functional_parity_not_accuracy', 'model_sha256': config['weights_sha256'],
              'windows_torch_version': torch.__version__, 'cases': []}
    for sid in ('S0035', 'S0106'):
        readings = {}
        for role in ('A', 'B'):
            row = next(r for r in inventory if r['sheet_id'] == sid and r['capture_role'] == role
                       and r['pair_status'] == 'verified')
            source = ROOT / row['relative_path']
            if source.suffix.lower() in {'.heic', '.heif'}:
                source = ROOT / conversions[row['relative_path']]
            target = samples / f'{sid}_{role}{source.suffix.lower()}'
            shutil.copy2(source, target)
            local_out = output / f'{sid}_{role}_local'
            local_out.mkdir()
            readings[role] = read_role(model, device, target, ROOT, {}, local_out, None, role)
            if role == 'A':
                variants = [('A-only', {'A': readings['A']})]
            else:
                variants = [('A+B', readings)]
            for name, captures in variants:
                local, local_pair = build_methods(captures.get('A'), captures.get('B'), config, 'cloud-probe')
                command = ['docker', 'run', '--rm', '--network', 'none', '--memory', '2g', '--cpus', '1',
                           '--mount', f'type=bind,source={samples},target=/samples,readonly',
                           args.image_tag, '--image-a', f'/samples/{sid}_A{target.suffix.lower()}']
                # Resolve each filename independently; A and B can have different extensions.
                command[-1] = '/samples/' + next(samples.glob(f'{sid}_A.*')).name
                if name == 'A+B':
                    command += ['--image-b', '/samples/' + target.name]
                process = subprocess.run(command, text=True, encoding='utf-8', capture_output=True, timeout=300)
                if process.returncode:
                    raise RuntimeError(process.stderr[-4000:])
                cloud = json.loads(process.stdout)
                (output / f'{sid}_{name.replace("+", "_")}_linux.json').write_text(
                    json.dumps(cloud, ensure_ascii=False, indent=2), encoding='utf-8')
                (output / f'{sid}_{name.replace("+", "_")}_windows.json').write_text(
                    json.dumps({'methods': local, 'pair_check': local_pair}, ensure_ascii=False, indent=2), encoding='utf-8')
                comparisons = {}
                for method in ('cnn', 'cla'):
                    different = [a['question_no'] for a, b in zip(local[method], cloud['methods'][method])
                                 if any(a[k] != b[k] for k in ('proposed_answer', 'needs_review', 'review_reasons', 'used_B'))]
                    confidence_delta = max(abs(a['selected_confidence'] - b['selected_confidence'])
                                           for a, b in zip(local[method], cloud['methods'][method]))
                    comparisons[method] = {'different_decision_questions': different,
                                            'max_confidence_delta': confidence_delta}
                case = {'sheet_id': sid, 'variant': name, 'linux_model_version': cloud['model_version'],
                        'linux_torch_version': cloud['torch_version'], 'linux_opencv_version': cloud['opencv_version'],
                        'question_count': cloud['question_count'], 'load_seconds': cloud['load_seconds'],
                        'total_seconds': cloud['total_seconds'], 'peak_rss_linux_kib': cloud['peak_rss_platform_units'],
                        'pair_check_same': local_pair == cloud['pair_check'], 'comparison': comparisons}
                report['cases'].append(case)
                (output / 'comparison.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
                print(json.dumps(case), flush=True)
    report['elapsed_seconds'] = time.perf_counter() - started
    report['all_decisions_match'] = all(c['question_count'] == 100 and c['pair_check_same']
        and all(not v['different_decision_questions'] for v in c['comparison'].values()) for c in report['cases'])
    (output / 'comparison.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(output / 'comparison.json'),
                      'all_decisions_match': report['all_decisions_match']}), flush=True)


if __name__ == '__main__':
    main()

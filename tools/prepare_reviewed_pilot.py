"""Prepare a fully reviewed development subset without changing the final 270-pair set."""
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / 'data/metadata'


def read(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def write(path, fields, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'presentation_build/reviewed_pilot_270')
    args = parser.parse_args()
    scope = json.loads((META / 'dataset_scope.json').read_text(encoding='utf-8'))
    ic, inventory = read(META / 'image_inventory_verified.csv')
    lc, labels = read(META / 'answer_labels.csv')
    sc, splits = read(META / 'sheet_splits.csv')
    _, holds = read(META / 'pairing_review_holds.csv')
    blocked = {r['sheet_id'] for r in holds if r['review_status'] == 'pending'}
    pairs = defaultdict(list)
    answers = defaultdict(dict)
    valid_marks = {'1', '2', '3', '4', '5', 'blank', 'multiple', 'ambiguous'}
    for row in inventory:
        if row['pair_status'] == 'verified':
            pairs[row['sheet_id']].append(row)
    assert len(pairs) == scope['final_paired_sheets']
    assert not (set(pairs) & blocked)
    for sid, rows in pairs.items():
        if Counter(r['capture_role'] for r in rows) != Counter({'A': 1, 'B': 1}):
            raise ValueError(f'Invalid paired sheet {sid}')
    for row in labels:
        sid, q = row['sheet_id'], int(row['question_no'])
        if sid not in pairs or q in answers[sid] or not 1 <= q <= 100:
            raise ValueError(f'Unknown or duplicate label slot: {row}')
        value = row['ground_truth'].strip()
        if value and value not in valid_marks:
            raise ValueError(f'Invalid inspected label: {row}')
        answers[sid][q] = value
    complete = {sid for sid, rows in answers.items()
                if set(rows) == set(range(1, 101)) and all(rows.values())}
    subset_images = [r for r in inventory if r['pair_status'] == 'verified' and r['sheet_id'] in complete]
    subset_labels = [r for r in labels if r['sheet_id'] in complete]
    subset_splits = [r for r in splits if r['sheet_id'] in complete]
    split_counts = Counter(r['split'] for r in subset_splits)
    if set(split_counts) != {'train', 'validation', 'test'}:
        raise ValueError('A development pilot requires reviewed sheets in every existing split.')
    output = args.output / 'data/metadata'
    output.mkdir(parents=True, exist_ok=True)
    write(output / 'image_inventory_verified.csv', ic, subset_images)
    write(output / 'answer_labels.csv', lc, subset_labels)
    write(output / 'sheet_splits.csv', sc, subset_splits)
    subset_scope = {**scope, 'subset_purpose': 'assisted_development_pilot',
                    'input_subset_sheets': len(complete), 'input_subset_human_labels': len(subset_labels)}
    (output / 'dataset_scope.json').write_text(json.dumps(subset_scope, ensure_ascii=False, indent=2), encoding='utf-8')
    source_names = ['image_inventory_verified.csv', 'answer_labels.csv', 'sheet_splits.csv', 'pairing_review_holds.csv']
    report = {
        'final_dataset_pairs': len(pairs), 'final_dataset_images': 2*len(pairs),
        'additional_image_collection': False, 'pilot_sheets': len(complete),
        'pilot_images': len(subset_images), 'pilot_human_labels': len(subset_labels),
        'pilot_sheet_splits': dict(split_counts),
        'pilot_classes': dict(Counter(r['ground_truth'] for r in subset_labels)),
        'classes_without_pilot_examples': sorted(valid_marks-{r['ground_truth'] for r in subset_labels}),
        'all_official_human_labels': sum(bool(r['ground_truth']) for r in labels),
        'other_inspected_labels_preserved_in_canonical_csv': sum(bool(r['ground_truth']) for r in labels if r['sheet_id'] not in complete),
        'source_image_extensions': dict(Counter(r['extension'] for r in subset_images)),
        'omr_drafts_used_as_labels': 0, 'canonical_files_modified': False,
        'existing_sheet_splits_preserved': True, 'annotation_mode': 'omr_assisted',
        'evaluation_type': 'assisted_development_pilot', 'independent_evaluation': False,
        'source_sha256': {n: hashlib.sha256((META/n).read_bytes()).hexdigest() for n in source_names},
        'models_trained': False,
    }
    (args.output / 'preflight.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (args.output / 'README.md').write_text(
        '# Reviewed development pilot\n\n'
        'The final collection is fixed at 270 paired sheets / 540 photos. '
        f'This first development subset contains only the {len(complete)} sheets whose 100 answers '
        f'were already inspected. The {report["other_inspected_labels_preserved_in_canonical_csv"]} inspected answers on other sheets stay in '
        'the canonical CSV; no tentative OMR draft is used as a label.\n\n'
        'The three metadata files retain original photo paths and original split '
        'assignments. Use the project source-image directory as the data root. '
        'The photos themselves are not copied or moved. This is an assisted '
        'development pilot, not an independent final test. Multiple/ambiguous '
        'classes have no examples in this pilot. This preparation command does not train models.\n',
        encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

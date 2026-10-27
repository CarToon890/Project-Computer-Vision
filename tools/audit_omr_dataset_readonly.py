"""Read-only pairing, split and exact-image-duplicate audit; never alters data."""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / 'data/metadata'
OUT = ROOT / 'presentation_build/omr_risk_policy_20261027/dataset_audit.json'


def read(name):
    with (META/name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    inventory = [r for r in read('image_inventory_verified.csv') if r['pair_status']=='verified']
    splits = read('sheet_splits.csv')
    counts = Counter(r['sheet_id'] for r in splits)
    split = {r['sheet_id']:r['split'] for r in splits}
    sheets = defaultdict(list); sizes = defaultdict(list); missing = []
    for r in inventory:
        sheets[r['sheet_id']].append(r)
        p = ROOT/r['relative_path']
        if not p.is_file():
            missing.append(r['image_id'])
        else:
            sizes[p.stat().st_size].append((r,p))
    duplicates = defaultdict(list)
    for group in sizes.values():
        if len(group)>1:
            for row,path in group:
                duplicates[sha(path)].append(row)
    cross_split = [[r['image_id'] for r in group] for group in duplicates.values()
                   if len(group)>1 and len({split.get(r['sheet_id']) for r in group})>1]
    bad_pairs = [s for s,rows in sheets.items() if sorted(r['capture_role'] for r in rows)!=['A','B']]
    result = {'verified_sheets':len(sheets),'verified_images':len(inventory),
              'split_sheets':dict(Counter(split.get(s,'missing') for s in sheets)),
              'sheets_without_valid_ab':bad_pairs,'duplicate_split_sheet_ids':[s for s,n in counts.items() if n!=1],
              'sheets_without_split':[s for s in sheets if s not in split],
              'missing_images':missing,'exact_duplicate_images_across_splits':cross_split,
              'scope':'Exact byte duplicates only; visually similar or re-encoded photos require separate checks.',
              'source_sha256':{n:sha(META/n) for n in ('image_inventory_verified.csv','sheet_splits.csv','answer_labels.csv')}}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    if OUT.exists():raise SystemExit('Existing audit preserved')
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()

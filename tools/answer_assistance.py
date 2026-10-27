"""Build a reproducible review workload; confidence never means human verified."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path


def freeze_assistance(workload, path: Path, fingerprint):
    """Keep the agreed 1,000 tasks fixed as reviewed labels are imported."""
    if workload is None:
        return None
    if path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if saved['fingerprint'] == fingerprint and saved['workload']['version'] == workload['version']:
            fixed = saved['workload']
            keys = [r['key'] for r in fixed['queue']]
            if len(keys) != len(set(keys)) or any(k not in fixed['items'] for k in keys):
                raise ValueError('Invalid saved review workload; preserve it for investigation.')
            return fixed
    staging = path.with_suffix('.tmp')
    staging.write_text(json.dumps({'fingerprint': fingerprint, 'workload': workload}, ensure_ascii=False, indent=2), encoding='utf-8')
    staging.replace(path)
    return workload


def spread_pick(candidates, count, *, randomize=False):
    groups = defaultdict(list)
    for row in candidates:
        groups[row['contributor']].append(row)
    def order(row):
        tie = hashlib.sha256(('omr-review-20261026:' + row['key']).encode()).hexdigest()
        return (0 if randomize else -row['risk_score'], tie)
    for group in groups.values():
        group.sort(key=order)
    chosen = []
    while len(chosen) < count:
        added = False
        for contributor in sorted(groups):
            if groups[contributor] and len(chosen) < count:
                chosen.append(groups[contributor].pop(0))
                added = True
        if not added:
            break
    return chosen


def build_assistance(sheets, pilot, initial, holds, *, start='S0039', risk_count=800, sample_count=200):
    if not pilot:
        return None
    candidates = []
    items = {}
    for sheet in sheets:
        sid = sheet['id']
        if sid < start or sid in holds:
            continue
        predictions = pilot['sheets'].get(sid, {})
        readable = {role: result for role, result in predictions.items() if len(result.get('rows', [])) == 100}
        role = 'B' if 'B' in readable else 'A' if 'A' in readable else None
        if role is None:
            continue
        other_role = 'A' if role == 'B' else 'B'
        other_rows = {r['question_no']: r for r in readable.get(other_role, {}).get('rows', [])}
        for row in readable[role]['rows']:
            key = f"{sid}:{row['question_no']}"
            if key in initial:
                continue
            other = other_rows.get(row['question_no'])
            reasons = []
            if other and other['proposed'] != row['proposed']:
                reasons.append('ab_disagree')
            if row['proposed'] in {'blank', 'multiple', 'ambiguous'}:
                reasons.append('special_mark')
            if row['uncertain']:
                reasons.append('low_confidence')
            if not other:
                reasons.append('single_image')
            if readable[role].get('registration', {}).get('mode') == 'printed-feature-homography':
                reasons.append('template_registration')
            weights = {'ab_disagree': 1000, 'special_mark': 900, 'low_confidence': 800,
                       'single_image': 100, 'template_registration': 200}
            risk = sum(weights[r] for r in reasons)
            confident = not row['uncertain'] and row['proposed'] in {'1','2','3','4','5'}
            item = {'proposed': row['proposed'], 'role': role, 'confident': confident,
                    'reasons': reasons, 'risk_score': risk}
            items[key] = item
            candidates.append({'key': key, 'contributor': sheet['contributor'], **item})
    risk_pool = [r for r in candidates if r['reasons']]
    risk = spread_pick(risk_pool, risk_count)
    used = {r['key'] for r in risk}
    sample = spread_pick([r for r in candidates if r['confident'] and r['key'] not in used], sample_count, randomize=True)
    queue = [{'key': r['key'], 'kind': kind} for kind, selected in [('risk', risk), ('sample', sample)] for r in selected]
    policy = {'start': start, 'risk_count': risk_count, 'sample_count': sample_count,
              'pilot_run_id': pilot['run_id'], 'version': 1}
    version = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()[:16]
    return {'version': version, 'start': start, 'items': items, 'queue': queue,
            'summary': {'eligible': len(items), 'auto_drafts': sum(r['confident'] for r in items.values()),
                        'risk': len(risk), 'sample': len(sample)}}

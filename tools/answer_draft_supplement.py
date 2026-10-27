"""Offer an alternative image's clear reading without changing frozen runs or labels."""
import hashlib
import json
from omr_pair_reading import propose_pair, MIN_SIGNAL, MIN_MARGIN


METHOD = 'paired-image-draft-v2'


def build_draft_supplement(sheets, pilot, initial, holds, *, start='S0039'):
    items = {}
    if pilot:
        for sheet in sheets:
            sid = sheet['id']
            if sid < start or sid in holds:
                continue
            readings = pilot['sheets'].get(sid, {})
            a, b = readings.get('A', {}), readings.get('B', {})
            if len(a.get('rows', [])) != 100 or len(b.get('rows', [])) != 100:
                continue
            if any(readings[r].get('image_id') != sheet[r]['id'] for r in ('A', 'B')):
                raise ValueError(f'Alternative draft source no longer matches pair {sid}')
            by_question = {row['question_no']: row for row in a['rows']}
            for base in b['rows']:
                question = base['question_no']
                key = f'{sid}:{question}'
                alternative = by_question.get(question)
                if key in initial or not alternative:
                    continue
                proposal = propose_pair(alternative, base)
                if not proposal['eligible_draft']:
                    continue
                reasons = [proposal['reason']]
                if alternative['proposed'] != base['proposed']:
                    reasons.insert(0, 'ab_disagree')
                items[key] = {
                    'proposed': proposal['proposed'], 'role': proposal['role'],
                    'image_a_id': a['image_id'], 'image_b_id': b['image_id'],
                    'reasons': reasons,
                    'label_status': 'omr_draft', 'reviewed_by_human': False,
                }
    policy = {'min_signal_each_image': MIN_SIGNAL, 'min_margin_each_image': MIN_MARGIN,
              'new_draft_requires_matching_peaks': True}
    run_id = hashlib.sha256(json.dumps({
        'method': METHOD, 'source_run_id': pilot.get('run_id') if pilot else None,
        'items': items, 'policy': policy,
    }, sort_keys=True).encode()).hexdigest()[:16]
    return {'method': METHOD, 'run_id': run_id, 'policy': policy,
            'source_run_id': pilot.get('run_id') if pilot else None,
            'items': items}

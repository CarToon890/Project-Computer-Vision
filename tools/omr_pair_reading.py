"""Tentative per-question reading policy; frozen single-image results stay intact."""
import math


MIN_SIGNAL = .08
MIN_MARGIN = .04


def peak_evidence(row):
    if not row or row.get('proposed') in {'multiple', 'ambiguous'}:
        return None
    scores = row.get('scores', [])
    if len(scores) != 5 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in scores):
        return None
    order = sorted(range(5), key=lambda i: scores[i], reverse=True)
    first, second = scores[order[0]], scores[order[1]]
    return {'mark': str(order[0] + 1), 'signal': first, 'margin': first - second}


def propose_pair(a, b):
    row = b or a
    if not row:
        return None
    baseline = {'proposed': row['proposed'], 'role': 'B' if b else 'A',
                'eligible_draft': False, 'reason': 'frozen_single_image'}
    if not a or not b:
        return baseline
    # The original v1 alternative-image rule is preserved.
    if (b['proposed'] == 'blank' and b['uncertain'] and not a['uncertain']
            and a['proposed'] in {'1', '2', '3', '4', '5'}):
        return {'proposed': a['proposed'], 'role': 'A',
                'eligible_draft': True, 'reason': 'alternative_image'}
    # Extend drafts only when two registered image rows independently support
    # the same option. Never turn missing/weak/contradictory evidence into truth.
    ea, eb = peak_evidence(a), peak_evidence(b)
    if (b['uncertain'] and ea and eb and ea['mark'] == eb['mark']
            and min(ea['signal'], eb['signal']) >= MIN_SIGNAL
            and min(ea['margin'], eb['margin']) >= MIN_MARGIN):
        role = 'A' if ea['margin'] >= eb['margin'] else 'B'
        return {'proposed': ea['mark'], 'role': role, 'eligible_draft': True,
                'reason': 'paired_peak_agreement'}
    return baseline

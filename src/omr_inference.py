"""Read one verified A/B sheet with saved weights; outputs are unverified drafts."""
import argparse
import csv
import html
import json
import time
from pathlib import Path

import numpy as np
import cv2
import torch
from PIL import Image

from omr_model import CLASSES, load_trained_model, predict_cnn
from omr_geometry import read_image, rectify_sheet, row_crop, bubble_scores, display_row


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def combine_readings(a, b, cutoff, sheet_id):
    """Apply the existing CNN A-then-B policy, including missing-image cases."""
    rows = []
    for i in range(100):
        def prediction(result):
            if result is None:
                return '', 0.
            return result['predictions'][i], float(result['confidence'][i])
        ap, ac = prediction(a)
        bp, bc = prediction(b)
        accepted_a = bool(ap and ap != 'ambiguous' and ac >= cutoff)
        use_b = not accepted_a and b is not None
        answer = ap if accepted_a else bp if use_b and bc >= cutoff else 'ambiguous'
        confidence = ac if accepted_a else bc if use_b else 0.
        reasons = []
        if a is None and b is None:
            answer = ''
            reasons.append('registration_failed')
        elif answer == 'ambiguous':
            reasons.append('low_confidence')
        if answer in {'blank', 'multiple'}:
            reasons.append('limited_special_mark_training')
        # A low-confidence A prediction may still disagree with the B answer
        # selected for scoring. Keep that disagreement visible for human review.
        if ap and ap != 'ambiguous' and bp and bp != 'ambiguous' and bp != ap and bc >= cutoff:
            reasons.append('ab_disagree')
        rows.append({'sheet_id': sheet_id, 'question_no': i+1,
            'proposed_answer': answer, 'a_prediction': ap, 'a_confidence': ac,
            'b_prediction': bp, 'b_confidence': bc, 'used_B': use_b,
            'selected_confidence': confidence, 'needs_review': bool(reasons),
            'review_reasons': ';'.join(reasons),
            'label_status': 'registration_failed' if not answer else 'model_draft',
            'reviewed_by_human': False})
    return rows


def read_role(model, device, source, data_root, conversion_map, output, sheet_id, role):
    started = time.perf_counter()
    raw = read_image(source, conversion_map, data_root)
    preview = Image.fromarray(cv2.cvtColor(raw, cv2.COLOR_BGR2RGB))
    preview.thumbnail((1200, 1600), Image.Resampling.LANCZOS)
    preview.save(output/f'{role}_input.jpg', quality=90)
    gray, centers, registration = rectify_sheet(raw, source_sheet_id=sheet_id)
    crops = np.stack([row_crop(gray, q, centers) for q in range(1, 101)])
    indices, confidence = predict_cnn(model, crops, device)
    scores = np.stack([bubble_scores(gray, q, centers) for q in range(1, 101)])
    Image.fromarray(gray).save(output/f'{role}_registered.jpg', quality=92)
    sprite = Image.new('L', (600, 9000), 255)
    for i, points in enumerate(centers):
        crop = Image.fromarray(display_row(gray,i+1,centers)).resize((600, 90), Image.Resampling.LANCZOS)
        sprite.paste(crop, (0, i*90))
    sprite.save(output/f'{role}_rows.jpg', quality=94)
    return {'predictions': [CLASSES[int(i)] for i in indices],
            'confidence': confidence.tolist(), 'registration': registration,
            'cla_scores': scores.tolist(), 'processing_seconds': time.perf_counter()-started}


def write_report(output, rows, summary):
    mark = lambda value: {'ambiguous': 'รอตรวจ', 'blank': 'เว้นว่าง', 'multiple': 'หลายช่อง', '': 'อ่านภาพไม่ได้'}.get(value, value)
    body = []
    for row in rows:
        pics = []
        for role in 'AB':
            if role in summary['readable_roles']:
                pics.append(f'<td><div class="strip"><img loading="lazy" src="{role}_rows.jpg" style="top:-{(row["question_no"]-1)*100}%" alt="ภาพ {role} ข้อ {row["question_no"]}"></div></td>')
            else:
                pics.append('<td>ไม่ได้ใช้ภาพนี้</td>')
        body.append(f'<tr data-review="{str(row["needs_review"]).lower()}"><td>{row["question_no"]}</td><td><strong>{html.escape(mark(row["proposed_answer"]))}</strong></td><td>{row["selected_confidence"]:.3f}</td><td>{"B" if row["used_B"] else "A"}</td>'+''.join(pics)+'</tr>')
    links = ' · '.join(f'<a href="{r}_registered.jpg" target="_blank">ดูภาพ {r} เต็ม</a>' for r in summary['readable_roles'])
    page = '''<!doctype html><html lang="th"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ผลอ่านคำตอบจากโมเดล</title>
<style>body{font:16px Tahoma,sans-serif;margin:22px;color:#17212b;background:#f5f7f8}main{background:white;padding:20px;max-width:1250px;margin:auto}h1{font-size:24px}p{line-height:1.7}button,a{font:inherit}button{padding:10px 15px;margin:8px 6px 12px 0;cursor:pointer}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:8px;border-bottom:1px solid #d8dfe5;text-align:left}th{background:#edf2f5;position:sticky;top:0}tr[data-review=true]{background:#fff5dd}.strip{width:270px;max-width:30vw;aspect-ratio:600/90;overflow:hidden;position:relative}.strip img{width:100%;position:absolute;left:0}a{color:#174a6e}.hide{display:none}</style>
<main><h1>ผลอ่าน SHEET</h1><p>ตอบได้ตามเกณฑ์ NUMERIC ข้อ · ต้องดูเพิ่มเติม REVIEW ข้อ · ใช้ภาพ B ช่วย BCOUNT ข้อ</p><p>คำตอบทั้งหมดเป็นร่างจากโมเดล ยังไม่ใช่คำตอบที่คนตรวจแล้ว คะแนนโมเดลไม่ใช่เปอร์เซ็นต์ความถูกต้อง</p><p>LINKS · <a href="model_predictions.csv" download>ดาวน์โหลดคำตอบร่าง CSV</a></p><button id="filter">แสดงเฉพาะข้อที่ต้องดู</button><span id="count"></span><table><thead><tr><th>ข้อ</th><th>คำตอบร่าง</th><th>คะแนนโมเดล</th><th>ใช้ภาพ</th><th>รอยฝน A</th><th>รอยฝน B</th></tr></thead><tbody>ROWS</tbody></table></main>
<script>let only=true;function draw(){let n=0;for(const row of document.querySelectorAll('tbody tr')){const visible=!only||row.dataset.review==='true';row.classList.toggle('hide',!visible);if(visible)n++}document.getElementById('count').textContent='แสดง '+n+' / 100 ข้อ';document.getElementById('filter').textContent=only?'ดูคำตอบทั้ง 100 ข้อ':'ดูเฉพาะข้อที่ต้องดู'}document.getElementById('filter').onclick=()=>{only=!only;draw()};draw();</script></html>'''
    page = page.replace('SHEET', html.escape(summary['sheet_id'])).replace('NUMERIC', str(summary['answers_above_cutoff'])).replace('REVIEW', str(summary['needs_review'])).replace('BCOUNT', str(summary['questions_using_B'])).replace('LINKS', links).replace('ROWS', ''.join(body))
    (output/'report.html').write_text(page, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=Path('.'))
    parser.add_argument('--model-dir', type=Path, default=Path('models'))
    parser.add_argument('--sheet', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    root = args.data_root.resolve()
    config = json.loads((args.model_dir/'model_config.json').read_text(encoding='utf-8'))
    if config['classes'] != CLASSES:
        raise ValueError('Model class ordering does not match RowCNN.')
    inventory = read_csv(root/'data/metadata/image_inventory_verified.csv')
    pair = [r for r in inventory if r['sheet_id'] == args.sheet and r['pair_status'] == 'verified']
    if len(pair) != 2 or sorted(r['capture_role'] for r in pair) != ['A', 'B']:
        raise ValueError('Choose a verified A/B sheet; single or withdrawn images cannot be used as a pair.')
    hold_path = root/'data/metadata/pairing_review_holds.csv'
    if hold_path.exists() and any(r['sheet_id'] == args.sheet and r['review_status'] == 'pending' for r in read_csv(hold_path)):
        raise ValueError('This A/B pair is on hold.')
    conversion_path = root/'data/metadata/heic_conversion_map.csv'
    conversions = {r['source_relative_path']: r['normalized_relative_path'] for r in read_csv(conversion_path)} if conversion_path.exists() else {}
    torch.set_num_threads(2)
    model, device = load_trained_model(args.model_dir/config['weights_file'], expected_sha256=config['weights_sha256'])
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    readings, errors = {}, {}
    def attempt(role):
        row = next(r for r in pair if r['capture_role'] == role)
        try:
            readings[role] = read_role(model, device, root/row['relative_path'], root, conversions, output, args.sheet, role)
        except (ValueError, OSError, RuntimeError) as error:
            errors[role] = str(error)
            readings[role] = None
    cutoff = config['cnn_confidence_cutoff']
    attempt('A')
    a = readings['A']
    if a is None or any(p == 'ambiguous' or c < cutoff for p, c in zip(a['predictions'], a['confidence'])):
        attempt('B')
    rows = combine_readings(readings.get('A'), readings.get('B'), cutoff, args.sheet)
    with (output/'model_predictions.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {'sheet_id': args.sheet, 'device': str(device), 'model_sha256': config['weights_sha256'],
        'confidence_cutoff': cutoff, 'question_rows': 100,
        'answers_above_cutoff': sum(bool(r['proposed_answer']) and r['proposed_answer'] != 'ambiguous' for r in rows),
        'needs_review': sum(r['needs_review'] for r in rows),
        'questions_using_B': sum(r['used_B'] for r in rows),
        'readable_roles': [r for r in 'AB' if readings.get(r) is not None],
        'registration': {r: p['registration'] for r,p in readings.items() if p is not None},
        'errors': errors, 'label_status': 'model_draft', 'canonical_labels_written': False,
        'new_training_run': False}
    (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    write_report(output, rows, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()

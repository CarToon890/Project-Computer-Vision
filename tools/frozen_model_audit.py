"""Prepare and score a frozen-model audit on existing held-out sheet images.

The review page intentionally hides model predictions. Human labels are saved
separately from the canonical answer-label table and from model outputs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

CLASSES = ["1", "2", "3", "4", "5", "blank", "multiple", "ambiguous"]
PRIOR_TEST_COHORT = {
    "S0009", "S0011", "S0012", "S0014", "S0016",
    "S0020", "S0022", "S0026", "S0035", "S0037",
}
SEED = "frozen-model-audit-20261027"
OUT = ROOT / "presentation_build/frozen_model_audit_20261027"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def select_sheets() -> tuple[list[str], list[str]]:
    split_rows = read_csv(ROOT / "data/metadata/sheet_splits.csv")
    test_sheets = sorted(
        row["sheet_id"] for row in split_rows
        if row["split"] == "test" and row["sheet_id"] not in PRIOR_TEST_COHORT
    )
    ranked = sorted(
        test_sheets,
        key=lambda sheet: hashlib.sha256(f"{SEED}|{sheet}".encode()).hexdigest(),
    )
    return ranked[:10], ranked


def review_html(sheet_ids: list[str], default_answers: dict[str, str]) -> str:
    display = {"blank": "เว้นว่าง", "multiple": "หลายช่อง", "ambiguous": "กำกวม"}
    cards = []
    for sheet in sheet_ids:
        for question in range(1, 101):
            cards.append(
                f'<tr data-sheet="{sheet}" data-q="{question}" data-reviewed="false">'
                f'<td class="meta"><b>{sheet}</b><span>ข้อ {question}</span>'
                '<span class="rowStatus">ยังไม่ตรวจ</span></td>'
                f'<td class="rowImage"><strong>ภาพ A</strong><div class="strip"><img loading="lazy" src="assets/{sheet}/A_rows.jpg" '
                f'style="top:-{(question - 1) * 100}%" alt="{sheet} A ข้อ {question}"></div>'
                f'<button type="button" data-zoom="{sheet}_A">ขยายภาพ A เต็มแผ่น</button></td>'
                f'<td class="rowImage"><strong>ภาพ B</strong><div class="strip"><img loading="lazy" src="assets/{sheet}/B_rows.jpg" '
                f'style="top:-{(question - 1) * 100}%" alt="{sheet} B ข้อ {question}"></div>'
                f'<button type="button" data-zoom="{sheet}_B">ขยายภาพ B เต็มแผ่น</button></td>'
                '<td class="answerCell"><div class="choices">'
                + "".join(
                    f'<label><input type="radio" name="{sheet}_{question}" value="{mark}"><span>{display.get(mark, mark)}</span></label>'
                    for mark in CLASSES
                )
                + f'</div><span class="defaultTag" hidden>คำตอบคนตรวจเดิม · กรุณาตรวจภาพก่อนยืนยัน</span>'
                + f'<label class="correction"><input type="checkbox" data-correction="{sheet}_{question}"> '
                'พบรอยแก้/ขีดฆ่า</label><input class="note" type="text" placeholder="หมายเหตุ (ไม่บังคับ)" '
                f'data-note="{sheet}_{question}"><button type="button" class="rowConfirm" data-confirm="{sheet}_{question}">ยืนยันข้อนี้</button></td></tr>'
            )
    defaults = json.dumps(default_answers, ensure_ascii=False).replace("</", "<\\/")
    page = '''<!doctype html><html lang="th"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ตรวจคำตอบอ้างอิง · Frozen-model audit</title>
<style>
*{box-sizing:border-box}body{font:15px Segoe UI,Tahoma,sans-serif;margin:0;background:#f3f5f7;color:#17212b}
header{background:#fff;padding:12px 18px;position:sticky;top:0;z-index:3;box-shadow:0 1px 4px #0002}
h1{font-size:20px;margin:0 0 6px}p{margin:5px 0}.warning{color:#7d341b;font-weight:600}.toolbar,.navigation{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:7px}
button,select,input{font:inherit}button{padding:8px 11px;border:1px solid #aebbc5;border-radius:7px;background:#fff;cursor:pointer}button:hover{background:#edf4f8}
button:disabled{opacity:.45;cursor:default}.primary{background:#155e75;color:#fff;border-color:#155e75}.primary:hover{background:#0e4d60;color:#fff}
main{padding:12px}#modeLabel{font-weight:700}#overallProgress{width:min(320px,45vw);height:13px;vertical-align:middle}#progressText,#sheetProgress{font-weight:600}
select,input[type=number]{padding:7px;border:1px solid #aebbc5;border-radius:6px;background:white}input[type=number]{width:85px}
table{border-collapse:collapse;width:100%;background:white}th,td{border-bottom:1px solid #d8dfe5;padding:9px;vertical-align:middle}
th{position:sticky;top:176px;background:#eaf0f4;text-align:left;z-index:1}tbody tr:nth-child(even){background:#fafcfd}
.strip{width:min(38vw,600px);aspect-ratio:600/90;overflow:hidden;position:relative;background:#fff;border:1px solid #d6dfe5;border-radius:5px}
.strip img{width:100%;position:absolute;left:0;max-width:none}.rowImage{min-width:260px}.rowImage strong{display:block;margin-bottom:5px}
.choices{display:grid;grid-template-columns:repeat(4,minmax(68px,1fr));gap:7px}.choices label{display:flex;align-items:center;gap:5px;padding:7px;border:1px solid #ccd5dc;border-radius:7px;background:white;cursor:pointer}
.choices label:has(input:checked){border-color:#147d64;background:#e8f7f2;font-weight:700}.choices input{accent-color:#147d64}
.correction{display:block;margin:8px 0;color:#7d341b}.note{width:100%;min-width:180px;padding:7px;border:1px solid #c3cdd5;border-radius:5px}
.meta{min-width:110px}.meta b,.meta span{display:block;margin-bottom:5px}.rowStatus{font-size:13px;color:#576874}.rowStatus.reviewed{color:#147d4f;font-weight:700}.defaultTag{display:block;color:#795400;background:#fff6db;border-radius:5px;padding:6px;margin:7px 0;font-size:13px}
tr[data-reviewed="true"]{outline:2px solid #61a77f;outline-offset:-2px}.skipStatus{color:#8b4c00}.hide{display:none}.focus-mode{display:block;background:transparent}.focus-mode thead{display:none}.focus-mode tbody{display:block}
.focus-mode tbody tr:not(.active){display:none}.focus-mode tbody tr.active{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;max-width:1500px;margin:8px auto;background:#fff;border:1px solid #d5dfe5;border-radius:10px;padding:12px;box-shadow:0 2px 7px #0001}
.focus-mode tbody tr.active td{display:block;border:0;padding:7px;min-width:0}.focus-mode tbody tr.active td.meta,.focus-mode tbody tr.active td.answerCell{grid-column:1/-1}
.focus-mode .rowImage{min-width:0}.focus-mode .strip{width:100%;max-width:780px}.focus-mode .choices{grid-template-columns:repeat(8,minmax(64px,1fr));max-width:900px}.focus-mode .choices label{justify-content:center;padding:10px 5px;font-size:17px}
.rowConfirm{margin-top:8px}.table-mode .rowConfirm{padding:5px 8px;font-size:13px}.table-mode .choices{min-width:340px}.table-mode tr.active{box-shadow:inset 0 0 0 3px #147d64}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
dialog{border:0;border-radius:10px;padding:10px;max-width:95vw;max-height:95vh;box-shadow:0 5px 30px #0006}dialog::backdrop{background:#101820bb}dialog img{display:block;max-width:90vw;max-height:82vh;object-fit:contain;margin:8px auto}dialog form{text-align:right}
@media(max-width:900px){.focus-mode tbody tr.active{display:block}.focus-mode tbody tr.active td{width:100%}.focus-mode .strip{max-width:none}.focus-mode .choices{grid-template-columns:repeat(4,minmax(60px,1fr))}th{top:210px}}
</style><header><h1>ตรวจคำตอบอ้างอิง · Frozen-model audit</h1>
<p>ตรวจภาพ A/B แล้วเลือกคำตอบที่เห็นจริง · ไม่แสดงคำทำนาย CNN · ปุ่มลัด: 1–5, B เว้นว่าง, M หลายช่อง, ? กำกวม, ←/→ เปลี่ยนข้อ, Enter ยืนยัน</p>
<p class="warning">ต้องดูภาพก่อนยืนยันคำตอบคนตรวจเดิม หากพบรอยแก้/ขีดฆ่าให้ติ๊กช่องกำกับ ข้อที่ข้ามไว้ยังไม่นับว่าตรวจแล้ว</p>
<div><progress id="overallProgress" max="1000" value="0"></progress> <span id="progressText"></span> · <span id="sheetProgress"></span> · <span id="saveStatus">บันทึกอัตโนมัติเปิดอยู่</span></div>
<div class="toolbar"><span id="modeLabel">โหมดตรวจทีละข้อ</span><button id="focusMode">ตรวจทีละข้อ</button><button id="tableMode">ดูตาราง</button>
<select id="sheetJump" aria-label="เลือกแผ่น"></select><label for="questionJump">ข้อ</label><input id="questionJump" type="number" min="1" max="100" value="1"><button id="goJump">ไป</button>
<button id="save">บันทึกตอนนี้</button><button id="export">ดาวน์โหลด CSV</button><button id="backup">ดาวน์โหลดสำรอง JSON</button></div>
<div class="navigation"><button id="previous">← ก่อนหน้า</button><button id="next">ถัดไป →</button><button id="nextPending">ข้อที่ยังไม่ตรวจถัดไป</button>
<button id="confirmCurrent" class="primary">ยืนยันข้อนี้ แล้วไปข้อถัดไป</button><button id="skip">ข้ามไว้ก่อน</button></div>
</header><main><table id="reviewTable" class="focus-mode"><thead><tr><th>แผ่น/ข้อ</th><th>ภาพ A</th><th>ภาพ B</th><th>คำตอบอ้างอิงจากภาพ</th></tr></thead><tbody>ROWS</tbody></table></main>
<dialog id="zoomDialog"><form method="dialog"><button>ปิดภาพ</button></form><img id="zoomImage" alt="ภาพขยาย"><p id="zoomCaption"></p></dialog>
<script>
const rows=[...document.querySelectorAll('#reviewTable tbody tr')];
const defaults=DEFAULTS; const key=(kind,id)=>`frozen-model-audit:${kind}:${id}`; let currentIndex=0; let mode='focus';
const idOf=row=>row.dataset.sheet+'_'+row.dataset.q;
function checked(row){return row.querySelector('input[type=radio]:checked')}
function renderStatus(row){row.dataset.reviewed=String(row.dataset.reviewed==='true');row.classList.toggle('reviewedRow',row.dataset.reviewed==='true');
row.querySelector('.rowStatus').textContent=row.dataset.reviewed==='true'?'ตรวจจากภาพแล้ว':(defaults[idOf(row)]?'รอยืนยันคำตอบคนตรวจเดิม':'ยังไม่ตรวจ');
row.querySelector('.rowStatus').classList.toggle('reviewed',row.dataset.reviewed==='true');row.querySelector('.defaultTag').hidden=!(defaults[idOf(row)]&&row.dataset.reviewed!=='true');}
function persistRow(row){const id=idOf(row),answer=checked(row);if(answer&&(row.dataset.reviewed==='true'||!defaults[id]))localStorage.setItem(key('answer',id),answer.value);else if(!answer)localStorage.removeItem(key('answer',id));
localStorage.setItem(key('reviewed',id),row.dataset.reviewed==='true'?'true':'false');localStorage.setItem(key('correction',id),String(row.querySelector('[data-correction]').checked));
localStorage.setItem(key('note',id),row.querySelector('[data-note]').value);renderStatus(row);}
function restore(){for(const row of rows){const id=idOf(row),saved=localStorage.getItem(key('answer',id));const initial=saved||defaults[id];if(initial){const radio=row.querySelector(`input[type=radio][value="${initial}"]`);if(radio)radio.checked=true}
const reviewed=localStorage.getItem(key('reviewed',id));row.dataset.reviewed=reviewed==='true'||(reviewed===null&&saved!==null)?'true':'false';
const correction=localStorage.getItem(key('correction',id));if(correction==='true')row.querySelector('[data-correction]').checked=true;
const note=localStorage.getItem(key('note',id));if(note)row.querySelector('[data-note]').value=note;renderStatus(row)}
const savedCurrent=localStorage.getItem(key('current','global'));const savedIndex=rows.findIndex(row=>idOf(row)===savedCurrent);currentIndex=savedIndex>=0?savedIndex:findPending(0,false);}
function setCurrent(index){currentIndex=(index+rows.length)%rows.length;localStorage.setItem(key('current','global'),idOf(rows[currentIndex]));render();if(mode==='table')rows[currentIndex].scrollIntoView({block:'center',behavior:'smooth'})}
function findPending(start,wrap=true){for(let i=start;i<rows.length;i++)if(rows[i].dataset.reviewed!=='true')return i;if(wrap)for(let i=0;i<start;i++)if(rows[i].dataset.reviewed!=='true')return i;return Math.min(start,rows.length-1)}
function render(){const row=rows[currentIndex];document.querySelector('#reviewTable').className=mode==='focus'?'focus-mode':'table-mode';
rows.forEach((r,i)=>r.classList.toggle('active',i===currentIndex));document.querySelector('#modeLabel').textContent=mode==='focus'?'โหมดตรวจทีละข้อ':'โหมดตาราง';
const done=rows.filter(r=>r.dataset.reviewed==='true').length;document.querySelector('#overallProgress').value=done;document.querySelector('#progressText').textContent=done===1000?'ตรวจครบ 1000 ข้อแล้ว':`ตรวจจากภาพ ${done}/1000 ข้อ`;
const sameSheet=rows.filter(r=>r.dataset.sheet===row.dataset.sheet);const sheetDone=sameSheet.filter(r=>r.dataset.reviewed==='true').length;
document.querySelector('#sheetProgress').textContent=`${row.dataset.sheet}: ${sheetDone}/100 ข้อ · ข้อ ${row.dataset.q}`;
document.querySelector('#questionJump').value=row.dataset.q;document.querySelector('#sheetJump').value=row.dataset.sheet;document.querySelector('#previous').disabled=currentIndex===0;document.querySelector('#next').disabled=currentIndex===rows.length-1;
document.querySelector('#saveStatus').textContent='บันทึกอัตโนมัติเปิดอยู่';}
function advancePending(){const nextIndex=findPending(currentIndex+1);setCurrent(nextIndex)}
function markReviewed(row){if(!checked(row)){document.querySelector('#saveStatus').textContent='เลือกคำตอบก่อนยืนยัน';return false}row.dataset.reviewed='true';persistRow(row);return true}
function confirmCurrent(){if(markReviewed(rows[currentIndex]))advancePending()}
function exportRows(){return rows.map(row=>({sheet_id:row.dataset.sheet,question_no:row.dataset.q,ground_truth:checked(row)?.value||'',reviewed:row.dataset.reviewed==='true'?'yes':'no',correction_observed:row.querySelector('[data-correction]').checked?'yes':'no',note:row.querySelector('[data-note]').value}))}
rows.forEach((row,index)=>{row.addEventListener('change',event=>{if(event.target.matches('input[type=radio]')){row.dataset.reviewed='true';persistRow(row);if(mode==='focus'&&index===currentIndex)advancePending()}else persistRow(row)});
row.querySelector('[data-note]').addEventListener('input',()=>{persistRow(row)});
row.querySelector('[data-confirm]').addEventListener('click',()=>{if(mode==='focus'&&index===currentIndex)confirmCurrent();else if(markReviewed(row))render()});
row.querySelectorAll('[data-zoom]').forEach(button=>button.addEventListener('click',()=>{const [sheet,role]=button.dataset.zoom.split('_');document.querySelector('#zoomImage').src=`assets/${sheet}/${role}_registered.jpg`;document.querySelector('#zoomCaption').textContent=`${sheet} · ภาพ ${role}`;document.querySelector('#zoomDialog').showModal()}));});
document.querySelector('#focusMode').onclick=()=>{mode='focus';render()};document.querySelector('#tableMode').onclick=()=>{mode='table';render();rows[currentIndex].scrollIntoView({block:'center',behavior:'smooth'})};
document.querySelector('#previous').onclick=()=>setCurrent(currentIndex-1);document.querySelector('#next').onclick=()=>setCurrent(currentIndex+1);
document.querySelector('#nextPending').onclick=advancePending;document.querySelector('#confirmCurrent').onclick=confirmCurrent;
document.querySelector('#skip').onclick=()=>advancePending();document.querySelector('#sheetJump').innerHTML=SHEETS.map(s=>`<option value="${s}">${s}</option>`).join('');
document.querySelector('#goJump').onclick=()=>{const sheet=document.querySelector('#sheetJump').value,q=Math.max(1,Math.min(100,Number(document.querySelector('#questionJump').value)||1));const idx=rows.findIndex(r=>r.dataset.sheet===sheet&&Number(r.dataset.q)===q);if(idx>=0)setCurrent(idx)};
document.querySelector('#save').onclick=()=>{rows.forEach(persistRow);document.querySelector('#saveStatus').textContent='บันทึกแล้ว'};
function download(name,text,type){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type}));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
document.querySelector('#export').onclick=()=>download('frozen_model_audit_labels.csv','\\ufeffsheet_id,question_no,ground_truth,reviewed,correction_observed,note\\n'+exportRows().map(r=>[r.sheet_id,r.question_no,r.ground_truth,r.reviewed,r.correction_observed,r.note].map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\\n'),'text/csv;charset=utf-8');
document.querySelector('#backup').onclick=()=>download('frozen_model_audit_backup.json',JSON.stringify({protocol:'frozen-model-audit-20261027',current:idOf(rows[currentIndex]),labels:exportRows()},null,2),'application/json');
document.addEventListener('keydown',event=>{if(event.ctrlKey||event.altKey||event.metaKey)return;if(event.target.closest('input[type=text],input[type=number],textarea,select,[contenteditable=true]'))return;if(event.key==='Enter'&&event.target.closest('button'))return;
if(event.key==='ArrowLeft'){event.preventDefault();setCurrent(currentIndex-1);return}if(event.key==='ArrowRight'){event.preventDefault();setCurrent(currentIndex+1);return}
if(event.key==='Enter'){event.preventDefault();confirmCurrent();return}const k=event.key.toLowerCase();const mark=/^[1-5]$/.test(k)?k:k==='b'?'blank':k==='m'?'multiple':k==='?'?'ambiguous':null;
if(mark){event.preventDefault();const radio=rows[currentIndex].querySelector(`input[type=radio][value="${mark}"]`);if(radio){radio.checked=true;radio.dispatchEvent(new Event('change',{bubbles:true}))}}});
restore();document.querySelector('#sheetJump').innerHTML=SHEETS.map(s=>`<option value="${s}">${s}</option>`).join('');render();
</script></html>'''
    return page.replace("ROWS", "".join(cards)).replace("DEFAULTS", defaults).replace("SHEETS", json.dumps(sheet_ids))


def score(labels_path: Path) -> None:
    pred_rows = read_csv(OUT / "evaluation/frozen_model_predictions.csv")
    label_rows = read_csv(labels_path)
    pred_map = {(r["sheet_id"], int(r["question_no"])): r for r in pred_rows}
    truth_map: dict[tuple[str, int], str] = {}
    for row in label_rows:
        key = (row["sheet_id"], int(row["question_no"]))
        truth = row["ground_truth"].strip().lower()
        if (key in truth_map or key not in pred_map or truth not in CLASSES
                or row.get("reviewed", "").strip().lower() != "yes"):
            raise ValueError(f"Invalid or duplicate audit label: {row}")
        truth_map[key] = truth
    expected = set(pred_map)
    if set(truth_map) != expected:
        missing = sorted(expected - set(truth_map))[:10]
        extra = sorted(set(truth_map) - expected)[:10]
        raise ValueError(f"Need exactly one label for every audit row; missing={missing}, extra={extra}")

    def metrics(column: str) -> dict[str, object]:
        matrix = {actual: {guess: 0 for guess in CLASSES} for actual in CLASSES}
        for key, truth in truth_map.items():
            guess = pred_map[key][column]
            if guess not in CLASSES:
                raise ValueError(f"Unknown prediction {guess!r} for {key}")
            matrix[truth][guess] += 1
        total = len(truth_map)
        correct = sum(matrix[label][label] for label in CLASSES)
        report = {}
        for label in CLASSES:
            tp = matrix[label][label]
            support = sum(matrix[label].values())
            predicted = sum(matrix[actual][label] for actual in CLASSES)
            precision = tp / predicted if predicted else 0.0
            recall = tp / support if support else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            report[label] = {"support": support, "precision": precision, "recall": recall, "f1": f1}
        return {"questions": total, "correct": correct, "incorrect_or_deferred": total-correct,
                "accuracy_including_deferred_as_not_correct": correct/total,
                "macro_f1_including_absent_classes_as_zero": sum(x["f1"] for x in report.values())/len(CLASSES),
                "per_class": report, "confusion_matrix_labels": CLASSES,
                "confusion_matrix": [[matrix[a][p] for p in CLASSES] for a in CLASSES]}

    result = {
        "audit_type": "frozen_model_audit_on_previously_inferred_images",
        "independent_evaluation": False,
        "model_config": json.loads((ROOT / "models/retrained_v2_perspective/model_config.json").read_text(encoding="utf-8")),
        "label_source": "human visual inspection in the separate blind review page",
        "sheets": sorted({key[0] for key in truth_map}),
        "labels": len(truth_map),
        "A_only": metrics("a_only"),
        "A_then_B": metrics("a_then_b"),
        "limitations": [
            "All 270 images were previously processed by a model; strict end-to-end holdout independence cannot be established.",
            "Model weights and confidence cutoff were frozen for this audit; audit labels must not be used for training or threshold changes.",
            "The audit set is a deterministic sample from the remaining Test sheets, not a newly collected photo set.",
        ],
    }
    (OUT / "evaluation/audit_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"results": str(OUT / "evaluation/audit_results.json"), "sheets": result["sheets"], "labels": result["labels"]}, ensure_ascii=False, indent=2))


def prepare() -> None:
    import torch
    from omr_inference import combine_readings, read_role
    from omr_model import CLASSES as MODEL_CLASSES, load_trained_model

    if MODEL_CLASSES != CLASSES:
        raise ValueError("Audit class order does not match the current CNN.")
    sheet_ids, candidates = select_sheets()
    model_dir = ROOT / "models/retrained_v2_perspective"
    config = json.loads((model_dir / "model_config.json").read_text(encoding="utf-8"))
    if config["classes"] != CLASSES:
        raise ValueError("Frozen model class order does not match the audit protocol.")
    inventory = read_csv(ROOT / "data/metadata/image_inventory_verified.csv")
    labels = read_csv(ROOT / "data/metadata/answer_labels.csv")
    split_map = {row["sheet_id"]: row["split"] for row in read_csv(ROOT / "data/metadata/sheet_splits.csv")}
    conversion = {row["source_relative_path"]: row["normalized_relative_path"]
                  for row in read_csv(ROOT / "data/metadata/heic_conversion_map.csv")}
    selected_set = set(sheet_ids)
    default_answers = {
        f"{row['sheet_id']}_{int(row['question_no'])}": row["ground_truth"].strip().lower()
        for row in labels if row["sheet_id"] in selected_set and row["ground_truth"].strip()
    }
    if any(answer not in CLASSES for answer in default_answers.values()):
        raise ValueError("Existing confirmed labels contain a class outside the frozen audit set.")
    confirmed = Counter(row["sheet_id"] for row in labels if row["ground_truth"].strip())
    pairs = {}
    for row in inventory:
        if row["sheet_id"] in sheet_ids and row["pair_status"] == "verified":
            pairs.setdefault(row["sheet_id"], {})[row["capture_role"]] = row
    for sheet in sheet_ids:
        if split_map.get(sheet) != "test" or set(pairs.get(sheet, {})) != {"A", "B"}:
            raise ValueError(f"Selected sheet is not a verified Test pair: {sheet}")
        for row in pairs[sheet].values():
            if not (ROOT / row["relative_path"]).is_file():
                raise FileNotFoundError(ROOT / row["relative_path"])

    OUT.mkdir(parents=True, exist_ok=True)
    assets = OUT / "assets"
    evaluation = OUT / "evaluation"
    assets.mkdir(exist_ok=True)
    evaluation.mkdir(exist_ok=True)

    template_rows = [
        {"sheet_id": sheet, "question_no": q,
         "ground_truth": default_answers.get(f"{sheet}_{q}", ""),
         "reviewed": "no", "correction_observed": "", "note": ""}
        for sheet in sheet_ids for q in range(1, 101)
    ]
    label_fields = ["sheet_id", "question_no", "ground_truth", "reviewed", "correction_observed", "note"]
    write_csv(OUT / "labels_template.csv", template_rows, label_fields)

    torch.set_num_threads(2)
    model, device = load_trained_model(model_dir / config["weights_file"], expected_sha256=config["weights_sha256"])
    prediction_rows = []
    registration = {}
    for sheet in sheet_ids:
        sheet_assets = assets / sheet
        sheet_assets.mkdir(exist_ok=True)
        readings = {}
        for role in ("A", "B"):
            row = pairs[sheet][role]
            result = read_role(model, device, ROOT / row["relative_path"], ROOT, conversion, sheet_assets, sheet, role)
            readings[role] = result
            registration[f"{sheet}_{role}"] = result["registration"]
        rows = combine_readings(readings["A"], readings["B"], config["cnn_confidence_cutoff"], sheet)
        for row in rows:
            prediction_rows.append({
                "sheet_id": sheet, "question_no": row["question_no"],
                "a_only": row["a_prediction"], "a_confidence": row["a_confidence"],
                "b_prediction": row["b_prediction"], "b_confidence": row["b_confidence"],
                "a_then_b": row["proposed_answer"], "used_B": row["used_B"],
                "needs_review": row["needs_review"], "review_reasons": row["review_reasons"],
            })
    prediction_fields = list(prediction_rows[0])
    write_csv(evaluation / "frozen_model_predictions.csv", prediction_rows, prediction_fields)

    selection = {
        "audit_type": "frozen_model_audit_on_previously_inferred_images",
        "selection_seed": SEED,
        "selected_sheets": sheet_ids,
        "candidate_sheets": candidates,
        "prior_full_test_cohort_excluded": sorted(PRIOR_TEST_COHORT),
        "selected_sheet_existing_confirmed_labels": {s: confirmed[s] for s in sheet_ids},
        "existing_confirmed_labels_on_selected_sheets": sum(confirmed[s] for s in sheet_ids),
        "existing_labels_prefilled_but_not_marked_reviewed": len(default_answers),
        "human_visual_reviews_required": len(template_rows),
        "model_config_path": "models/retrained_v2_perspective/model_config.json",
        "model_sha256": config["weights_sha256"],
        "cnn_confidence_cutoff": config["cnn_confidence_cutoff"],
        "preprocessing_version": config.get("preprocessing_version"),
        "selection_method": "SHA256 ranking of Test sheet IDs outside the previous 10-sheet test cohort",
        "provenance_limit": "All 270 images had prior model inference; logs cannot prove these selected images were never exposed during preprocessing development.",
        "human_labels_are_not_model_predictions": True,
    }
    (OUT / "selection.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "registration.json").write_text(json.dumps(registration, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "review.html").write_text(review_html(sheet_ids, default_answers), encoding="utf-8")
    protocol = f"""# Frozen-model audit protocol

This is a **frozen-model audit on previously inferred images**, not a fully independent test.

- Selected 10 Test sheets: {', '.join(sheet_ids)}.
- Images were already processed in earlier full-dataset runs. Repository records do not prove they were never exposed during preprocessing development.
- Frozen profile: `models/retrained_v2_perspective/model_config.json`.
- Weight SHA256: `{config['weights_sha256']}`.
- CNN confidence cutoff: `{config['cnn_confidence_cutoff']}`.
- Do not use labels from this audit to train weights or change thresholds.
- The review page intentionally hides model predictions. Review each A/B row, confirm its visible reference answer, and flag any correction/cross-out seen by the human reviewer.
- Existing human-confirmed answers are prefilled only as starting values. They are not marked reviewed until a person visually checks the row and confirms it; saved browser selections take priority.
- All 1,000 rows require visual confirmation for this audit, including rows with a prefilled human answer.
- Download the CSV from `review.html` as `frozen_model_audit_labels.csv`. Then score it with:

  `python tools/frozen_model_audit.py --evaluate presentation_build/frozen_model_audit_20261027/frozen_model_audit_labels.csv`

The audit report will include A-only and A-then-B accuracy, per-class precision/recall/F1, confusion matrices, and its provenance limitation.
"""
    (OUT / "README.md").write_text(protocol, encoding="utf-8")
    print(json.dumps({
        "audit_dir": str(OUT), "review_page": str(OUT / "review.html"),
        "selected_sheets": sheet_ids, "existing_labels_prefilled_but_not_marked_reviewed": selection["existing_labels_prefilled_but_not_marked_reviewed"],
        "required_human_review_rows": len(template_rows), "model_sha256": config["weights_sha256"],
        "confidence_cutoff": config["cnn_confidence_cutoff"], "device": str(device),
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluate", type=Path, help="Score a completed human annotation CSV.")
    parser.add_argument("--render-only", action="store_true", help="Regenerate the review page without rerunning inference.")
    args = parser.parse_args()
    if args.evaluate:
        score(args.evaluate if args.evaluate.is_absolute() else ROOT / args.evaluate)
    elif args.render_only:
        selection = json.loads((OUT / "selection.json").read_text(encoding="utf-8"))
        selected = set(selection["selected_sheets"])
        label_rows = read_csv(ROOT / "data/metadata/answer_labels.csv")
        default_answers = {
            f"{row['sheet_id']}_{int(row['question_no'])}": row["ground_truth"].strip().lower()
            for row in label_rows
            if row["sheet_id"] in selected and row["ground_truth"].strip()
        }
        template_rows = [
            {"sheet_id": sheet, "question_no": q,
             "ground_truth": default_answers.get(f"{sheet}_{q}", ""),
             "reviewed": "no", "correction_observed": "", "note": ""}
            for sheet in selection["selected_sheets"] for q in range(1, 101)
        ]
        write_csv(OUT / "labels_template.csv", template_rows,
                  ["sheet_id", "question_no", "ground_truth", "reviewed", "correction_observed", "note"])
        selection["selected_sheet_existing_confirmed_labels"] = dict(Counter(
            row["sheet_id"] for row in label_rows
            if row["sheet_id"] in selected and row["ground_truth"].strip()
        ))
        selection["selected_sheet_existing_confirmed_labels"] = {
            sheet: selection["selected_sheet_existing_confirmed_labels"].get(sheet, 0)
            for sheet in selection["selected_sheets"]
        }
        selection["existing_labels_prefilled_but_not_marked_reviewed"] = len(default_answers)
        selection["human_visual_reviews_required"] = 1000
        selection.pop("selected_sheet_existing_confirmed_labels_not_prefilled", None)
        (OUT / "selection.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")
        (OUT / "review.html").write_text(review_html(selection["selected_sheets"], default_answers), encoding="utf-8")
        protocol = """# Frozen-model audit protocol

This is a **frozen-model audit on previously inferred images**, not a fully independent test.

- The review page keeps model predictions hidden and uses the frozen perspective profile.
- It preserves answers already saved in the browser and resumes at the current or next unanswered question.
- Forty-six previously human-confirmed answers are prefilled as starting values. They are not considered reviewed until a person checks the image and confirms the row.
- All 1,000 rows require visual confirmation for this audit, including rows with a prefilled human answer. Do not use audit labels to train weights or change thresholds.
- Use answer keys `1`–`5`, `B` for blank, `M` for multiple, `?` for ambiguous, arrow keys to navigate, and Enter to confirm a prefilled answer. Shortcuts pause in text fields.
- Download `frozen_model_audit_labels.csv` when complete. The `reviewed` column must be `yes` for all 1,000 rows before evaluation.
- Score the completed file with:

  `python tools/frozen_model_audit.py --evaluate presentation_build/frozen_model_audit_20261027/frozen_model_audit_labels.csv`

The report includes A-only and A-then-B accuracy, per-class precision/recall/F1, confusion matrices, and the provenance limitation.
"""
        (OUT / "README.md").write_text(protocol, encoding="utf-8")
        print(str(OUT / "review.html"))
    else:
        prepare()


if __name__ == "__main__":
    main()

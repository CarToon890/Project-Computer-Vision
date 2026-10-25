"""Create the starter Kaggle notebook from maintained cell sources below."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "omr_kaggle.ipynb"


def markdown(source: str) -> dict[str, object]:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def code(source: str) -> dict[str, object]:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


cells = [
    markdown(
        """# OMR: เปรียบเทียบ CLA, CNN และภาพยืนยัน A/B

โน้ตบุ๊กนี้รันเมื่อจับคู่ภาพ A/B และกรอก Ground truth ครบแล้วเท่านั้น โดยใช้คำตอบที่คนอ่านจากเครื่องหมายจริงบนกระดาษ ไม่ใช้เฉลยข้อสอบ

**ก่อนเริ่ม:** อัปโหลดโฟลเดอร์ `Dataset-Computer-vision/` และ `data/metadata/` ไว้ใน Kaggle Dataset เดียวกัน พร้อมแนบโค้ด `src/omr_pipeline.py` จาก repository เป็น Kaggle Dataset อีกชุดหนึ่ง ต้องมี `image_inventory_verified.csv`, `answer_labels.csv` และ `sheet_splits.csv` ใน `data/metadata/` ถ้ามี HEIC ให้แปลงด้วย `tools/convert_heic.py` ก่อนอัปโหลด และแนบ `heic_conversion_map.csv` กับ `data/normalized_images/` ด้วย

การจับคู่จากชื่อไฟล์ไม่เพียงพอ ให้ตรวจคำตอบ 100 ข้อว่าเหมือนกันก่อนยืนยันคู่ และแบ่ง Train/Validation/Test ตาม `sheet_id` เสมอ
"""
    ),
    code(
        """from pathlib import Path
import json
import subprocess
import sys

INPUT = Path('/kaggle/input')
DATA_ROOTS = [p.parent.parent.parent for p in INPUT.rglob('image_inventory_verified.csv') if p.parent.name == 'metadata']
CODE_SCRIPTS = list(INPUT.rglob('omr_pipeline.py'))

if not DATA_ROOTS:
    raise FileNotFoundError('แนบ Kaggle Dataset ที่มี data/metadata/image_inventory_verified.csv และ Dataset-Computer-vision/')
if not CODE_SCRIPTS:
    raise FileNotFoundError('แนบ Kaggle Dataset โค้ดที่มี src/omr_pipeline.py')

DATA_ROOT = DATA_ROOTS[0]
PIPELINE = CODE_SCRIPTS[0]
META = DATA_ROOT / 'data' / 'metadata'
for required in ['answer_labels.csv', 'sheet_splits.csv']:
    if not (META / required).is_file():
        raise FileNotFoundError(f'ยังไม่มี {META / required}; จับคู่ภาพและกรอก Ground truth ก่อน')

print('Data root:', DATA_ROOT)
print('Pipeline:', PIPELINE)
print('GPU available:', subprocess.run(['nvidia-smi'], capture_output=True).returncode == 0)
"""
    ),
    markdown(
        """## ตรวจและรัน

ระบบจะหยุดเมื่อยังมีคู่ที่ไม่ยืนยัน ป้ายคำตอบไม่ครบ หรือจัดแนวกระดาษไม่ได้ ให้แก้ข้อมูลต้นทางก่อนอ่านผล โมเดล CNN และ baseline CLA ใช้ชุดแบ่งข้อมูลเดียวกัน ส่วนเกณฑ์ความมั่นใจเลือกจาก Validation เท่านั้น
"""
    ),
    code(
        """import pandas as pd
from IPython.display import display

inventory = pd.read_csv(META / 'image_inventory_verified.csv')
labels = pd.read_csv(META / 'answer_labels.csv')
splits = pd.read_csv(META / 'sheet_splits.csv')
print('Verified image rows:', len(inventory[inventory.pair_status == 'verified']))
print('Verified sheets:', inventory.loc[inventory.pair_status == 'verified', 'sheet_id'].nunique())
print('Ground-truth rows:', len(labels))
display(splits.groupby('split').sheet_id.nunique().rename('sheets').to_frame())
"""
    ),
    code(
        """OUTPUT = Path('/kaggle/working/omr-results')
command = [
    sys.executable, str(PIPELINE),
    '--data-root', str(DATA_ROOT),
    '--inventory', 'data/metadata/image_inventory_verified.csv',
    '--labels', 'data/metadata/answer_labels.csv',
    '--splits', 'data/metadata/sheet_splits.csv',
    '--heic-map', 'data/metadata/heic_conversion_map.csv',
    '--output-dir', str(OUTPUT),
    '--epochs', '12',
    '--seed', '20261025',
]
subprocess.run(command, check=True)
"""
    ),
    code(
        """report = json.loads((OUTPUT / 'evaluation.json').read_text(encoding='utf-8'))
print('Split by sheet:', report['split_sheets'])
print('CLA thresholds:', report['cla_fill_threshold'], report['cla_margin_threshold'])
print('CNN confidence cutoff:', report['cnn_validation_confidence_cutoff'])
for model_name, values in report['models'].items():
    print('\\n', model_name.upper())
    for workflow, metrics in values.items():
        print(workflow, 'accuracy=', round(metrics['accuracy'], 4), 'macro F1=', round(metrics['macro_f1'], 4), 'coverage=', round(metrics['coverage'], 4))
"""
    ),
    markdown("""## ตัวอย่างเดโมจากชุด Test

แสดงภาพ A/B ของกระดาษหนึ่งแผ่นและผลอ่านรายข้อจากทั้ง CLA กับ CNN รวมถึงข้อที่ระบบใช้ภาพ B ยืนยัน
"""),
    code(
        """from IPython.display import display, Image as DisplayImage

test_sheet = splits.loc[splits.split.eq('test'), 'sheet_id'].iloc[0]
pair = inventory[(inventory.sheet_id == test_sheet) & (inventory.pair_status == 'verified')].set_index('capture_role')
conversion_map = {}
map_file = META / 'heic_conversion_map.csv'
if map_file.exists():
    conversion_df = pd.read_csv(map_file)
    conversion_map = dict(zip(conversion_df.source_relative_path, conversion_df.normalized_relative_path))
for role in ['A', 'B']:
    rel = pair.loc[role, 'relative_path']
    img_path = DATA_ROOT / rel
    if img_path.suffix.lower() in {'.heic', '.heif'}:
        normalized = conversion_map.get(Path(rel).as_posix())
        if not normalized:
            raise FileNotFoundError(f'ไม่มี JPEG conversion สำหรับ {rel}')
        img_path = DATA_ROOT / normalized
    print(test_sheet, role)
    display(DisplayImage(filename=str(img_path), width=360))

cnn_demo = pd.read_csv(OUTPUT / 'cnn_test_predictions.csv')
cla_demo = pd.read_csv(OUTPUT / 'cla_test_predictions.csv')
demo = cnn_demo[cnn_demo.sheet_id.eq(test_sheet)].merge(
    cla_demo[['sheet_id', 'question_no', 'a_only', 'a_then_b']],
    on=['sheet_id', 'question_no'], suffixes=('_cnn', '_cla')
)
display(demo[['question_no', 'ground_truth', 'a_only_cla', 'a_then_b_cla', 'a_only_cnn', 'a_then_b_cnn', 'used_B']].sort_values('question_no'))
"""
    ),
]

notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}
NOTEBOOK.parent.mkdir(parents=True, exist_ok=True)
NOTEBOOK.write_text(json.dumps(notebook, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Created {NOTEBOOK.relative_to(ROOT)} with {len(cells)} cells")

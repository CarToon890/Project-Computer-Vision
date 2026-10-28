# เทรน CNN เพิ่มหนึ่งรอบจากคำตอบที่ยืนยันแล้ว

รอบ 26 ต.ค. รันบน CPU สำเร็จแล้ว รุ่นที่เลือกอยู่ `models/retrained_v2/`
เลือก epoch 9 จาก 12 epochs ผล Test เดิม 1,000 ข้อ: A-only ถูก 998 และ A-then-B ถูก 999
ดูรายละเอียดและผลรุ่นเดิมที่ปรับ cutoff ใน `models/retrained_v2/README.md`
การรันด้านล่างเป็นวิธีทำซ้ำหรือใช้ Kaggle สำรอง ไม่ใช่งานที่ผู้ใช้ต้องทำเพิ่มตอนนี้

รอบนี้รับคำตอบเป็นรายข้อจาก `data/metadata/answer_labels.csv`
จึงใช้ข้อที่ตรวจแล้วในแผ่นที่ยังกรอกไม่ครบได้ ไม่ใช้ร่าง OMR/CNN เป็นเป้าหมายฝึก
ภาพ A/B ของคำตอบเดียวกันอยู่ split เดียวกันเสมอ

## ข้อมูลและขั้นตอน

ใช้คำตอบ Train 3,259 ข้อ และ Validation 400 ข้อ
ส่วน Test ใช้ 10 แผ่นที่ตรวจครบเดิม รวม 1,000 ข้อ
คำตอบ Test ที่ตรวจไว้อีก 101 ข้อยังเก็บในไฟล์หลัก แต่ไม่เพิ่มเข้า cohort ของรอบนี้
ขอบเขตข้อมูลสุดท้ายยังเป็น 270 คู่ / 540 ภาพ

1. `tools/convert_heic.py` สร้างสำเนา JPEG ของ HEIC 130 ภาพและ conversion map
2. `tools/prepare_retraining.py` เลือกเฉพาะคำตอบยืนยัน ตรวจ split/คู่/holds
   จัดแนวและเก็บ cache แถวคำตอบ จากนั้นสร้าง `confirmed_rows.npz` และ `preflight.json`
3. `src/omr_retrain.py` โหลดน้ำหนักเดิมแบบ tensor-only และตรวจ SHA256
   ทดลอง fine-tune ที่ learning rate 0.0001 สูงสุด 12 epochs หยุดเมื่อ Validation ไม่ดีขึ้น 3 รอบ
4. จำลองความสว่าง contrast และ affine เล็กน้อยเฉพาะ Train ไม่มีการกลับลำดับช่องคำตอบ
   จำกัดน้ำหนักคลาสที่มีตัวอย่างน้อย เพื่อไม่ให้ตัวอย่างเพียงสองข้อมีผลมากเกินไป
5. เปรียบเทียบโมเดลเดิมกับ checkpoint แต่ละรอบบน Validation เดียวกัน
   เลือกเกณฑ์ความมั่นใจจากภาพ A ของ Validation โดยตั้ง precision เป้าหมาย 99%
6. เลือกตามจำนวนข้อถูกของ A-only ก่อน แล้ว A-then-B จำนวนข้อที่ระบบตอบเองแต่ตอบผิด และ Validation loss
   รุ่นเดิมเป็นตัวเลือก epoch 0 เพื่อไม่บังคับใช้ checkpoint ที่แย่กว่า
7. เขียน `selection.json` และน้ำหนักที่เลือกให้เสร็จก่อนอ่านผลทำนาย Test
   จากนั้นประเมินทั้งรุ่นเดิม รุ่นเดิมที่ปรับ cutoff จาก Validation ปัจจุบัน และรุ่นที่เลือก

การแยกรุ่นเดิมที่ปรับ cutoff ช่วยแสดงว่าผลเปลี่ยนเพราะการฝึกหรือเพียงเปลี่ยนเกณฑ์ยอมตอบ
Test เดิมเคยมีส่วนในการวิเคราะห์พัฒนา จึงรายงานเป็น assisted development retest
ไม่อ้างเป็นผลทดสอบอิสระ หรือความแม่นยำของทั้ง 270 แผ่น
คลาส blank/multiple มีตัวอย่าง Train อย่างละสองข้อ ส่วน ambiguous ไม่มีตัวอย่างฝึก
ผลรวมที่สูงไม่ยืนยันความสามารถของคลาสเหล่านี้

## รันบนเครื่องนี้

เปิด PowerShell ที่โฟลเดอร์โปรเจกต์:

```powershell
$env:PYTHONPATH = "$PWD/.local_model_deps;$PWD/.local_cv_deps"
$env:PYTHONIOENCODING = 'utf-8'
& "$env:USERPROFILE/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe" tools/prepare_retraining.py
& "$env:USERPROFILE/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe" src/omr_retrain.py --data-dir presentation_build/retraining_v2 --output-dir presentation_build/retraining_v2/results_cpu
```

การรันซ้ำต้องใช้ output directory ใหม่เพื่อเก็บผลเดิมไว้
ตัวเตรียมข้อมูลรันซ้ำใช้ cache ได้ และไม่แก้คำตอบยืนยัน น้ำหนักเดิม หรือ split
ถ้าภาพใดจัดแนวไม่ได้จะหยุดก่อนสร้างแพ็กเกจ พร้อมรายการข้อผิดพลาดให้แก้ ไม่ทิ้งข้อมูลเงียบ ๆ

## รันบน Kaggle หากต้องการใช้ GPU

อัปโหลด `presentation_build/retraining_v2/omr_retraining_v2.zip` เป็น Dataset แบบ Private
เปิด `notebooks/omr_retraining_v2.ipynb` แนบ Dataset เปิด GPU ถ้ามี แล้ว Run All
ไม่ต้องนำภาพต้นฉบับทั้งหมดขึ้นใหม่ เพราะแพ็กเกจมีภาพตัดพร้อมข้อมูลอ้างอิงและน้ำหนักเดิมแล้ว
ดาวน์โหลด `retraining_results.zip` กลับมาเมื่อเสร็จ

## ผลที่ต้องเก็บ

- `history.json`: loss และผล Validation แต่ละ epoch
- `selection.json`: checkpoint ที่เลือก เหตุผล hyperparameters และเวลาฝึก
- `row_cnn.pt` / `model_config.json`: น้ำหนักที่เลือกและ cutoff สำหรับนำไปอ่านภาพ
- `baseline_test_predictions.csv`, `baseline_recalibrated_test_predictions.csv`, `selected_test_predictions.csv`
- `evaluation.json`: Accuracy, F1, confusion matrix, จำนวนผิด/รอตรวจ และการใช้ B
- `retraining_results.zip`: รวมผลเพื่อสำรองหรือนำกลับจาก Kaggle

น้ำหนักหลัก `models/row_cnn.pt` ยังเป็น baseline เดิม
การนำรุ่นที่เลือกไปอ่านภาพให้ระบุ `--model-dir` เป็นโฟลเดอร์ผลใหม่
คำตอบจากทั้งสองรุ่นยังเป็นร่าง ไม่ถูกบันทึกเป็นคำตอบที่คนตรวจแล้วโดยอัตโนมัติ

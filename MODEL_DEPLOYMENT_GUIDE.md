# คู่มือสถาปัตยกรรมการโหลดโมเดลและขั้นตอนการเปิดใช้โมเดล (Model Loading & Deployment Guide)

วันที่จัดทำ: 29 ตุลาคม 2026  
สถานะระบบปัจจุบัน: **คงเดิมที่ CNN v3 (ห้ามเปิดใช้โมเดลใหม่หรือดัดแปลงระบบจริงโดยไม่ได้รับอนุมัติ)**

---

## 1. การตรวจสอบเส้นทางการโหลดโมเดลในระบบจริง

จากการตรวจสอบซอร์สโค้ดของระบบทั้งสองส่วน (Local App และ Cloud Engine) พบว่า **การนำไฟล์น้ำหนักไปแทนที่ `models/row_cnn.pt` เพียงไฟล์เดียวจะไม่ทำให้ระบบเปลี่ยนรุ่นที่ใช้งาน** เนื่องจากกลไกความปลอดภัยและลำดับความสำคัญของแต่ละระบบ:

### 1.1 แอปพลิเคชันบนเครื่อง (Local Desktop App: `src/omr_app.py`)
ใน [`src/omr_app.py`](file:///C:/Users/USER/Desktop/BUU69/Project-Computer-Vision/src/omr_app.py) คลาส `OMRApplication`:
```python
v3 = self.root / 'models/retrained_v3_verified'
preferred = v3 if v3.is_dir() else self.root / 'models/retrained_v2_perspective'
self.model_dir = Path(model_dir or (preferred if preferred.is_dir() else self.root / 'models/retrained_v2'))
self.config = json.loads((self.model_dir / 'model_config.json').read_text(encoding='utf-8'))
self.model, self.device = load_trained_model(
    self.model_dir / self.config['weights_file'],
    expected_sha256=self.config['weights_sha256']
)
```
- **ข้อค้นพบสำคัญ**:
  1. แอปพลิเคชันบนเครื่องกำหนดลำดับความสำคัญของโฟลเดอร์โมเดล (Priority) โดยตรวจสอบ `models/retrained_v3_verified/` เป็นอันดับแรก
  2. หากโฟลเดอร์นี้มีอยู่ ระบบจะโหลด `row_cnn.pt` และ `model_config.json` จากโฟลเดอร์นี้เสมอ โดย **ไม่สนใจ `models/row_cnn.pt` ที่อยู่ที่โฟลเดอร์ราก (Root)**
  3. ฟังก์ชัน `load_trained_model()` จะตรวจสอบ SHA256 Checksum เทียบกับฟิลด์ `weights_sha256` ใน `model_config.json` หากไม่ตรง ระบบจะไม่ยอมโหลดโมเดล

### 1.2 ระบบประมวลผลบนคลาวด์ (Cloud Engine: `apps/engine/omr_engine/runtime.py`)
ใน [`apps/engine/omr_engine/runtime.py`](file:///C:/Users/USER/Desktop/BUU69/Project-Computer-Vision/apps/engine/omr_engine/runtime.py) คลาส `EngineRuntime`:
```python
MODEL_VERSION = 'confirmed-finetune-v3-risk-first'
MODEL_HASH = 'a5ddc52247efc28dcb8a806e6ffe3225d2f65ebb8a4a13740b30dad6062069b1'
...
manifest = self.store.read_json('system/v3/manifest.json', 1024 * 1024)
expected = {
    'manifest': ('system/v3/manifest.json', 'models/manifest.json', 1024 * 1024),
    'config': ('system/v3/model_config.json', 'models/model_config.json', 1024 * 1024),
    'weights': ('system/v3/row_cnn.pt', 'models/row_cnn.pt', 2 * 1024 * 1024),
    'references': ('system/v3/form_references.npz', 'data/metadata/form_references.npz', 10 * 1024 * 1024),
}
...
if config.get('model_version') != MODEL_VERSION or config.get('weights_sha256') != MODEL_HASH:
    raise EngineError('model_integrity', 'โมเดลไม่ใช่ CNN v3 ที่กำหนด', 503)
```
- **ข้อค้นพบสำคัญ**:
  1. Cloud Engine ไม่ได้อ่านไฟล์โมเดลจาก Local Workspace แต่ดึงไฟล์แพ็กเกจมาจาก Cloud Object Store ภายใต้คีย์ `system/v3/`
  2. โค้ดมีการล็อกค่าคงที่แบบฮาร์ดโค้ด (`MODEL_VERSION` และ `MODEL_HASH`) ไว้อย่างเข้มงวด
  3. หากนำไฟล์น้ำหนักอื่นไปวางที่ `models/row_cnn.pt` จะไม่มีผลต่อ Cloud Engine เลยแม้แต่น้อย และหากอัปโหลดขึ้น Cloud Store โดยไม่แก้ค่าคงที่ในโค้ด ระบบจะปฏิเสธการทำงานด้วยข้อผิดพลาด HTTP 503 (`model_integrity`) ทันที

---

## 2. ขั้นตอนมาตรฐานเมื่อต้องการเปลี่ยนหรือเปิดใช้โมเดลในอนาคต (Deployment Protocol)

> [!CAUTION]
> **ข้อพึงระวังขั้นสูงสุด**: ห้ามดำเนินการขั้นตอนด้านล่างนี้จนกว่าจะผ่านการทดสอบอิสระ (Independent Evaluation) ด้วยชุดกระดาษคำตอบใหม่ที่ไม่เคยเห็นมาก่อน และได้รับความเห็นชอบอย่างเป็นทางการ

หากในอนาคตผ่านการรับรองและได้รับคำสั่งให้อนุมัติเปิดใช้งานโมเดลรุ่นใหม่ จะต้องปฏิบัติตามขั้นตอนอย่างเป็นระบบดังนี้:

### ขั้นที่ 1: การอัปเดตระบบแอปพลิเคชันบนเครื่อง (Local Desktop App)
1. สร้างโฟลเดอร์โมเดลใหม่ เช่น `models/retrained_v4_verified/`
2. คัดลอก `row_cnn.pt` และ `model_config.json` ที่ระบุ `weights_sha256` ตรงกันเข้าไปในโฟลเดอร์ดังกล่าว
3. ปรับปรุง [`src/omr_app.py`](file:///C:/Users/USER/Desktop/BUU69/Project-Computer-Vision/src/omr_app.py) ให้จัดลำดับความสำคัญของโฟลเดอร์ใหม่เป็นอันดับแรก:
   ```python
   v4 = self.root / 'models/retrained_v4_verified'
   v3 = self.root / 'models/retrained_v3_verified'
   preferred = v4 if v4.is_dir() else (v3 if v3.is_dir() else ...)
   ```
4. รันชุดทดสอบระบบ [`tests/test_omr_app.py`](file:///C:/Users/USER/Desktop/BUU69/Project-Computer-Vision/tests/test_omr_app.py) เพื่อยืนยันว่าแอปอ่านผลได้อย่างถูกต้อง

### ขั้นที่ 2: การอัปเดตระบบ Cloud Engine
1. รันสคริปต์แพ็กเกจโมเดลเพื่อเตรียมไฟล์ Manifest และ Checksum:
   ```powershell
   python tools/package_vercel_engine.py
   ```
2. อัปโหลดชุดไฟล์ไปยัง Cloud Store ภายใต้ Namespace ใหม่ เช่น `system/v4/`
3. แก้ไขค่าคงที่ใน [`apps/engine/omr_engine/runtime.py`](file:///C:/Users/USER/Desktop/BUU69/Project-Computer-Vision/apps/engine/omr_engine/runtime.py):
   - ปรับ `MODEL_VERSION = 'confirmed-finetune-v4-single-a'`
   - ปรับ `MODEL_HASH = '<SHA256 ของน้ำหนัก v4 ใหม่>'`
   - ปรับคีย์สตอเรจใน `expected` เป็น `system/v4/...`
4. ทดสอบความสมบูรณ์ผ่าน Unit Test ของ Engine ก่อน Deploy

---

## 3. สรุปสถานะปัจจุบัน
- **Local App**: ใช้โมเดล **v3** จาก [`models/retrained_v3_verified/`](file:///C:/Users/USER/Desktop/BUU69/Project-Computer-Vision/models/retrained_v3_verified/)
- **Cloud Engine**: ล็อกที่ **v3** (`MODEL_HASH = a5ddc52247ef...`)
- **โมเดล v4 Candidate / Final Model**: ถูกเก็บกักกันไว้ใน [`presentation_build/retraining_v4_single_a_20261029/`](file:///C:/Users/USER/Desktop/BUU69/Project-Computer-Vision/presentation_build/retraining_v4_single_a_20261029/) โดยยังไม่ถูกเชื่อมต่อหรือเปิดใช้งานในระบบจริง

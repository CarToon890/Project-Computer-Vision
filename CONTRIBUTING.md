# แนวทางร่วมพัฒนา / Contributing

## เริ่มต้น / Getting started

Clone repository แล้วทำงานบน branch ของตนเองจาก `main` ตรวจ `git status` ก่อนเริ่ม งาน UX/UI ที่แยกไว้บน `codex/ux-ui-refinement` ยังไม่ได้รวมเข้า `main` อ่าน [คู่มือแอป](APP_RUNBOOK.md) และ [คู่มือสาธิต](DEMO_RUNBOOK.md) ก่อนตั้งค่าระบบเต็ม เพราะภาพต้นฉบับ น้ำหนักโมเดล และ credentials ไม่ได้มาพร้อม clone

Clone the repository and create a branch from `main`. The UX/UI branch is separate. Full inference requires local assets and configuration; the checks below do not.

## Dependency แยกตามส่วน / Dependencies by subsystem

- **เว็บ / Web:** Node.js 22 และ npm; `apps/web/package-lock.json` ล็อก dependency ติดตั้งด้วย `npm ci` ใน `apps/web` ส่วนนี้ใช้ Next.js
- **Engine:** Python 3.13; `apps/engine/pyproject.toml` และ `uv.lock` ระบุ dependency ของ engine รวม CPU PyTorch ดูวิธีตั้งค่าและ deployment ใน [คู่มือโมเดล](MODEL_DEPLOYMENT_GUIDE.md) การติดตั้ง engine ทั้งชุดไม่จำเป็นสำหรับ CI ด้านล่าง
- **Kaggle / การทดลอง:** `requirements.txt` ที่ root เป็นรายการสำหรับสภาพแวดล้อม Kaggle โดยไม่ได้ล็อกเวอร์ชัน ดู [KAGGLE_RUNBOOK.md](KAGGLE_RUNBOOK.md) ไม่ควรถือว่าเทียบเท่ากับ lockfile ของ engine

## ตรวจพื้นฐาน / Basic checks

ใช้ Node.js 22 และ Python 3.13 จาก root; เทสต์เหล่านี้ใช้ fixture หรือข้อมูลสังเคราะห์ ไม่ต้องใช้ภาพจริง น้ำหนักโมเดล หรือ secrets:

```sh
cd apps/web
npm ci
npm test
cd ../..
node --test tests/test_answer_review.mjs
python -m unittest discover -s tests -p test_answer_labels.py
python -m unittest discover -s tests -p test_answer_draft_supplement.py
```

GitHub Actions รันคำสั่งชุดเดียวกันบน Linux การตรวจนี้ไม่ได้ครอบคลุม inference หรือการเชื่อมต่อบริการจริง ดู [ขั้นตอนทดสอบระบบ](SYSTEM_TEST_RUNBOOK.md) สำหรับการทดสอบเพิ่มเติม

## ส่งการเปลี่ยนแปลง / Submit changes

สร้าง branch จาก `main`, ทำการเปลี่ยนแปลงที่เกี่ยวข้องกัน รัน checks ข้างต้น แล้วเปิด pull request ระบุสิ่งที่เปลี่ยน วิธีตรวจ และข้อจำกัดที่เหลือ อย่า commit secrets ภาพต้นฉบับ หรือโมเดลที่ถูกละเว้นโดย `.gitignore` ชุดข้อมูลที่ติดตามอยู่แล้วมีคำตอบและข้อมูลผู้ร่วมจัดทำ โปรดตรวจเนื้อหาก่อนเพิ่มข้อมูลใหม่

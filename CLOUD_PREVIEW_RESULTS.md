# ผลตรวจรับ OMR Cloud Preview — 28 ตุลาคม 2026

## ผลที่ผ่านจริง

Engine: `omr-cnn-engine`, Python 3.13, dependencies ตรึงด้วย `uv.lock` และ CPU-only
PyTorch. Vercel build เปิด Large Functions beta สำเร็จในทีม Hobby โดยไม่อัปเกรด
ไม่มีการสมัครแผนเสียเงิน ใช้ Neon `free_v3` และ Private Blob ที่สร้างสำหรับงานนี้

Engine Preview:
https://omr-cnn-engine-o0vvhvjq8-surachat18525-3005s-projects.vercel.app

S0035 และ S0106 แบบ A-only และ A+B รวม 4 กรณี กรณีละ 100 ข้อ ผล CNN และ CLA
ตรงกับ Windows baseline เดิมทั้งหมด รวม proposed answer, needs-review, เหตุผล,
การใช้ B และ pair check. ลายเซ็นปลอมถูกปฏิเสธ และการเรียกซ้ำคืนผลที่บันทึกแล้ว
เวลา HTTP สำหรับคำขออ่านในรอบนี้ประมาณ 5.5–11.9 วินาที ไม่ใช่การรับประกันเวลา
ทุกภาพหรือทุก cold start และไม่ใช่ independent accuracy evaluation

ผลละเอียดอยู่ในไฟล์ที่ไม่เข้า Git:
`presentation_build/vercel_engine_parity_20261028_fixed/comparison.json`

## เว็บและ API

Web Preview รุ่นล่าสุด:
https://omr-private-fe1ahbhns-surachat18525-3005s-projects.vercel.app
ตรวจ HTTP จริงแล้ว: หน้าเว็บ 200; API งาน 503 พร้อมข้อความให้เจ้าของตั้งรหัสผ่าน
ซึ่งเป็นการล็อกข้อมูลตามตั้งใจ ไม่ได้เปิดงานให้ผู้ที่ยังไม่เข้าสู่ระบบ

Next.js 16.4.3 มีหน้าเริ่มตรวจ ตรวจคำตอบ คะแนน/ส่งออก และประวัติงาน
พร้อมกล้องมือถือผ่าน file input capture, preview, HEIC fallback, และคำแนะนำไทย
มี scrypt password hash, cookie HttpOnly/Secure บน HTTPS, session 12 ชั่วโมง,
จำกัดรหัสผิด, ป้องกัน cross-origin mutation, และตรวจสิทธิ์ที่ API/ภาพทุกครั้ง

งานและคำตอบเก็บใน Neon. คำตอบโมเดลแยกจากคำตอบยืนยัน. Revision ป้องกันอีกแท็บ
เขียนทับ. CSV แยก CNN/CLA ก่อนคนตรวจ หลังคนตรวจ เฉลย และสถานะคะแนน
คะแนน final ต้องมีเฉลยครบและยืนยันโดยคนครบ 100 ข้อของวิธีนั้น

การทดสอบ localhost ใช้รหัส fixture ชั่วคราวเฉพาะ child process ผูก 127.0.0.1
ไม่ได้ตั้งรหัสนี้ใน Vercel และไม่ใช่รหัสส่วนตัวของผู้ใช้ เส้นทางที่ผ่านจริงคือ:
login → client upload ตรง Private Blob → เว็บ → OIDC/HMAC → Vercel engine →
บันทึกผล → เปิดงานต่อ → ยืนยัน/แก้คำตอบ → คะแนนชั่วคราว → CSV → logout

smoke report ผ่าน 18 checks รวมภาพที่ไม่ล็อกอินถูกปฏิเสธ และ revision เก่าถูกปฏิเสธ
อยู่ที่ `presentation_build/private_web_smoke_20261028/report.json`

ทดสอบซ้ำผ่าน file chooser และปุ่มอัปโหลดในเบราว์เซอร์จริงด้วย S0035 A สำเร็จ
เว็บอ่านผ่าน Vercel แล้วแสดงคำตอบ 100 ข้อ รอตรวจสัญญาณ 2 ข้อ คนยืนยัน 0 ข้อ
งานนี้ติดป้ายทดสอบเช่นกัน ไม่มีการนำคำตอบอัตโนมัติมานับเป็นคนตรวจ

resilience report ผ่านการจำลองภาพหมดอายุ, session หมดอายุ, lease งานค้าง,
สองงานชนกัน, พื้นที่ถึงเกณฑ์, cleanup และจำกัดการลองรหัสผิด
อยู่ที่ `presentation_build/private_web_smoke_20261028/resilience.json`
ตรวจแล้วว่า cleanup ไม่ลบ model objects และยังเก็บคำตอบ/เฉลยหลังภาพถูกลบ

งาน fixture ถูกติดป้าย `is_test`; คำตอบ/เฉลยที่จำลองไม่ใช่ human ground truth
ของ dataset ไม่ใช่คะแนนสอบจริง และไม่นำไปฝึกโมเดล

## สิทธิ์และอายุภาพ

ผู้ใช้อนุญาตเพิ่ม Trusted Sources เฉพาะ `omr-private-web` Preview/Development →
`omr-cnn-engine` Preview. ไม่มีสิทธิ์ข้ามไป Production และไม่ได้ปิด Protection
เว็บใช้ `@vercel/oidc` ส่ง short-lived token ร่วมกับ HMAC ฝั่งเซิร์ฟเวอร์

ภาพหมดอายุ 7 วัน: API ภาพและการยืนยันเพิ่มถูกปฏิเสธทันที แต่เฉลย/CSV ยังใช้ได้
cleanup endpoint ใช้ CRON_SECRET และลบเฉพาะ source/derived ที่หมดอายุ มี cron
วันละครั้งใน config. **ยังไม่ถือว่า daily cleanup เปิดใช้งานจริง** จน Production
ได้รับ environment ครบและผ่านการเปิดระบบ การทดสอบรอบนี้เรียก cleanup โดยตรง

ลบงาน: ลบคำตอบ/เฉลย/คะแนนและปิดสิทธิ์ดูงานทันที ส่วน image ledger เก็บถึงรอบ
retention เดิมเพื่อเก็บกวาดไฟล์ของ upload grant ที่ยังไม่หมดอายุได้ครบ
storage cap ปัจจุบัน 800,000,000 bytes รวมไฟล์โมเดลและ reservation ที่ค้าง

## หน้าจอและคีย์ลัด

หน้าเริ่มตรวจและหน้าตรวจคำตอบไม่ล้นแนวนอนที่ 375, 768, 1024, 1440 px
ภาพรอยฝนโหลดได้ทุกขนาด ทดสอบคลิกข้อ 2 → กด 4 → Enter → บันทึกและไปข้อ 3
ภาพของงานปัจจุบันใช้ sprite เดิมข้ามข้อและข้ามแท็บคะแนน ไม่ดาวน์โหลดใหม่ทุกข้อ
มี focus, error alert, loading, empty states, และคำเตือนผลชั่วคราว

หน่วยทดสอบ API/image 14 ข้อ รวม HEIC encode/decode และ chunked private download,
portable references 2 ข้อ, domain/password/scoring 3 ข้อผ่านแล้ว และ Next build ผ่าน

ภาพตรวจรับอยู่ที่ `presentation_build/private_web_smoke_20261028/start-*.jpg`
และ `review-*.jpg` (ไม่เข้า Git). คีย์ซูมของ IAB ไม่เปลี่ยน zoom จริง จึง **ยังไม่
อ้างว่าทดสอบ browser zoom 200% แล้ว**. ยังไม่มีการทดสอบกล้อง Android/iPhone จริง

## สิ่งที่ค้างก่อนเปิดใช้งาน

1. เจ้าของตั้งรหัสด้วยตัวเองตาม `OWNER_SETUP.md` ไม่ส่งรหัสในแชต
2. Redeploy Preview แล้วเจ้าของกรอกรหัสในเว็บด้วยตัวเอง เพื่อทดสอบ auth บน HTTPS
3. ตรวจ end-to-end จากเว็บ Preview จริงอีกครั้ง รวม upload callbacks ที่ป้องกันอยู่
4. ตรวจกล้อง Android/iPhone, zoom 200%, และกระดาษนอก dataset เมื่อมีอุปกรณ์/ภาพ
5. ตั้ง environment Production และสิทธิ์เชื่อมต่อที่จำเป็นเป็นขั้นเผยแพร่แยกต่างหาก

CLI จัด deployment แรกของเว็บเป็น Production อัตโนมัติแม้ระบุ Preview.
รุ่นนั้นไม่มี Production secrets/ฐานข้อมูลและเปิดงานไม่ได้ การยกเลิกไม่ทันเพราะ
build เสร็จแล้ว รอบถัดมามี guard ตรวจ post-first-deployment state และสร้าง Preview
แยกสำเร็จ Automatic approval เคยปฏิเสธ retry ก่อนมีหลักฐานนี้; ตรวจ source CLI
และสถานะ project แบบอ่านอย่างเดียวก่อนจึงได้รับอนุมัติให้ deploy แบบมี guard
ไม่ได้ bypass การปฏิเสธ และไม่ได้เปิด Production ให้ตรวจข้อสอบจริง

ไฟล์โมเดล v3, dataset photographs/pairs และ canonical labels ไม่เปลี่ยน
v4 ยังพักไว้ งานรอบนี้ยังไม่ได้ commit/push

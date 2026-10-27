# ผลทดลองเตรียม CNN v3 สำหรับ Vercel

วันที่ 28 ตุลาคม 2026

## สถานะ

ผ่านการแพ็กและรัน inference บน Linux container ในเครื่อง และเปรียบเทียบกับ
Windows เดิมแล้ว ยังไม่ได้ build/deploy หรือทดสอบบน Vercel จริง
ชุดทดลองเป็น CLI ไม่ใช่ HTTP API สำหรับเปิดให้ผู้ใช้งานออนไลน์

Vercel connector เชื่อมต่อบัญชีได้ แต่ไม่มีโปรเจกต์ OMR ในรายการที่อ่านได้
ไม่ได้แก้โปรเจกต์อื่น ไม่ได้สร้าง storage/database หรือบริการเสียเงิน

## สิ่งที่ทำ

- เพิ่มการส่งออก geometry, SIFT keypoints และ descriptors ที่ระบบเดิมใช้
  เป็น `form_references.npz` เพื่อไม่ต้องอ่าน dataset ทั้งชุดขณะ inference
- Archive ไม่มีภาพต้นฉบับหรือคำตอบอ้างอิง แต่เป็นข้อมูลอนุพันธ์ส่วนตัว
  ไม่ควรเผยแพร่เป็นไฟล์ public หรือถือว่าเป็นข้อมูลที่ anonymize แล้ว
- Primary reference และ Train fallback ใช้คุณลักษณะจากระบบเดิม ไม่คัดลอกรอยฝน
  ลงในภาพที่ผู้ใช้ส่งเข้า ไม่แก้น้ำหนักหรือ threshold ของโมเดล
- Local pipeline ยังคงใช้การอ่าน reference แบบเดิม หากไม่มี portable archive
- แพ็กเฉพาะโค้ด น้ำหนัก config และคุณลักษณะอ้างอิง รวม 5,030,386 bytes
  ก่อนรวม dependencies; น้ำหนัก v3 เดิม 1,150,885 bytes
- สร้าง Docker image และทดสอบด้วย 1 CPU / RAM จำกัด 2 GiB
  ภาพทดสอบ mount แบบ read-only และปิด networking ใน container ขณะอ่านภาพ

## ผลเปรียบเทียบรอบที่เลือก

ใช้ภาพ S0035 และ S0106 แผ่นละ A-only และ A+B รวม 4 กรณี กรณีละ 100 ข้อ
เป็นภาพพัฒนาที่เคยมีอยู่แล้ว ไม่ใช่ภาพใหม่หรือการประเมินอิสระ

- ทั้ง 4 กรณีอ่านครบ 100 ข้อ
- CNN: คำตอบ ข้อรอตรวจ เหตุผลรอตรวจ และการเลือกใช้ B ตรงกันทุกกรณี
- CLA: คำตอบ ข้อรอตรวจ เหตุผลรอตรวจ และการเลือกใช้ B ตรงกันทุกกรณี
- Pair consistency gate ตรงกันทั้ง 4 กรณี
- ความต่าง confidence สูงสุด CNN ประมาณ 2.3842e-7; CLA เท่ากับ 0 ในชุดนี้
- เป็นการเปรียบเทียบ 400 ผลรายข้อต่อวิธีที่มีการใช้ข้อเดิมซ้ำในสอง workflow
  ไม่ใช่คำตอบใหม่ 400 ข้อ และไม่ใช่การวัด accuracy

Process ใหม่ใน Docker ใช้เวลาภายในสคริปต์ประมาณ 10.45–26.03 วินาที
รวม import ไลบรารี โหลดโมเดล และอ่านภาพ Peak RSS ประมาณ 434–597 MiB
ตัวเลขนี้ไม่รวมเวลาเริ่ม Docker และไม่ใช่ cold-start/latency บน Vercel
ยังไม่มีผลทดสอบ warm-instance, concurrent requests หรือหลายผู้ใช้งาน

## ปัญหาที่พบและแก้แล้ว

การทดลองแรกใช้ torch 2.5.1+cpu, NumPy 2.1.3, OpenCV 4.10 และ Pillow 11
พบ CLA ของ S0106 A+B ข้อ 24 เปลี่ยนจาก `4` เป็น `blank` พร้อมแจ้งรอตรวจ
จึงไม่ยอมรับชุด runtime นี้และไม่แก้ threshold เพื่อซ่อนความต่าง

เปลี่ยนแพ็กเกจหลักให้ตรงกับเครื่อง Windows แล้วรันทั้ง 4 กรณีซ้ำ:

- Python image: `python:3.13-slim`
- torch: `2.14.1+cpu`
- numpy: `2.5.4`
- opencv-python-headless: `5.0.0.93`
- Pillow: `12.3.0`

ผลตัดสินของทั้งสองวิธีตรงกันแล้วในชุดทดลองนี้ การเปลี่ยนแพ็กเกจหลายรายการ
พร้อมกันไม่ได้พิสูจน์ว่าไลบรารีตัวเดียวเป็นสาเหตุ ต้องตรวจ parity อีกครั้ง
เมื่อเปลี่ยน runtime หรืออัปเดต dependency ในอนาคต

## สิ่งที่ยังต้องแก้ก่อนใช้บน Vercel

1. **ขนาด dependencies:** ชุดล่าสุดมี site-packages 1,159,848 KiB หรือประมาณ
   1.11 GiB ไม่รวม app/base image เกิน standard Python bundle 500 MB
   ต้องทดลอง Large Functions/Container หรือปรับขนาดอย่างมีผล parity รองรับ
   ไม่สรุปว่าต้องเปลี่ยนโมเดลหรือว่า Vercel รัน CNN ไม่ได้
2. **HTTP entrypoint:** CLI probe ยังไม่มี API และ local server เดิมยังเปิดงาน
   ผ่าน thread ที่อยู่ใน process เดียว ต้องเลือกวิธีประมวลผลให้จบใน request
   หรือกลไก background job ที่ทำต่อและ retry ได้อย่างเหมาะสม
3. **การเก็บงาน:** ผล ภาพ เฉลย และคำตอบที่คนแก้ยังต้องย้ายจาก local disk
   และหน่วยความจำไป private storage/database ที่คงอยู่ข้าม instance
4. **อัปโหลด:** ไม่ส่งภาพใหญ่เป็น Base64 ผ่าน Function; ใช้ private direct upload
   และ object ID ที่ผูกกับผู้ใช้/งาน พร้อมตรวจขนาดและชนิดไฟล์ฝั่งเซิร์ฟเวอร์
5. **สิทธิ์:** หน้า developer ที่ซ่อนด้วย CSS/query parameter ยังไม่ใช่ access control
   ต้องตรวจ identity, เจ้าของงาน และสิทธิ์ทุก endpoint/ไฟล์ก่อนเปิดออนไลน์
6. **HEIC และมือถือ:** Linux probe รอบนี้ใช้ JPEG ที่มีอยู่ในเครื่อง ยังไม่ได้แทนที่
   Windows HEIC converter หรือทดสอบ camera upload บนโทรศัพท์จริง
7. **แพ็กสำหรับเผยแพร่:** ต้องมี dependency lock, native libraries ที่จำเป็น,
   model/config/reference hash และไฟล์อ้างอิงครบ โดยไม่ส่ง dataset ส่วนตัวทั้งชุด

## หลักฐานและคำสั่ง

- ตัวแพ็ก: `tools/package_cloud_probe.py`
- สคริปต์อ่านบน Linux: `tools/cloud_probe.py`
- สคริปต์เทียบระบบเดิม: `tools/verify_cloud_probe.py`
- วิธีรัน: `deploy/cloud-probe/README.md`
- แพ็กที่ทดสอบ: `presentation_build/cloud_probe_v3_20261028_matched/`
- ผลล่าสุด: `presentation_build/cloud_probe_comparison_20261028_matched/comparison.json`
- ผลรอบเก่าที่พบความต่าง: `presentation_build/cloud_probe_comparison_20261028_r2/comparison.json`
- Docker image: `omr-v3-cloud-probe:matched-20261028`
- Image ID: `sha256:22c278bc50abc3da18ad79c989cb3f6e73d43860b646028d32215a59d9e536e5`
- Weight SHA-256: `a5ddc52247efc28dcb8a806e6ffe3225d2f65ebb8a4a13740b30dad6062069b1`
- Unit tests portable reference: 2 ผ่าน; geometry regression เดิม: 9 ผ่าน
- ตรวจ syntax ของสคริปต์ใหม่ผ่าน

ไฟล์ใน presentation_build และน้ำหนักโมเดลยังถูก Git ละเว้น
เอกสารและสคริปต์ใน workspace รอบนี้ยังไม่ได้ commit/push

## ขั้นถัดไป

ทดลอง API บน Vercel Preview โดยเริ่มจาก runtime ที่ผ่าน parity แล้ว และจัดการ
private uploads, persistence และสิทธิ์ให้พร้อมก่อนนำข้อมูลนักเรียนจริงไปใช้
ยืนยันค่าใช้จ่าย/บริการที่ต้อง provision ก่อนเปิด Production

อ้างอิงข้อจำกัดแพลตฟอร์มที่ตรวจวันที่ 28 ตุลาคม 2026:

- [Vercel Functions limits และ Large Functions](https://vercel.com/docs/functions/limitations)
- [Vercel Python runtime](https://vercel.com/docs/functions/runtimes/python)
- [Vercel Container runtime](https://vercel.com/docs/functions/runtimes/container)
- [Private client uploads](https://vercel.com/docs/vercel-blob/client-upload)

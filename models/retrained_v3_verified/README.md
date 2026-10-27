# รุ่นทดลอง v3 จากคำตอบที่คนตรวจแล้ว

รุ่นนี้ fine-tune ต่อจาก `models/retrained_v2_perspective` โดยใช้คำตอบยืนยัน
Train 5,591 ข้อและภาพ A/B, Validation 433 ข้อ และไม่ใช้คำตอบร่างเป็นเป้าหมาย
เลือก epoch 9 ตาม Validation ก่อนดู Test เกณฑ์ confidence และ preprocessing
คงเดิม การทดสอบ runtime ซ้ำบน Validation ใช้ pair consistency gate ทั้งแผ่น
และผ่านเกณฑ์ที่บันทึกไว้ก่อน Test เว็บบนเครื่องจึงเลือกโปรไฟล์นี้เป็นค่าเริ่มต้น
เมื่อโฟลเดอร์นี้มีอยู่ ให้เริ่มแอปใหม่เพื่อโหลดน้ำหนักล่าสุด

น้ำหนัก `row_cnn.pt` เป็นไฟล์ภายในเครื่องและถูก `.gitignore` ไม่ได้ขึ้น GitHub
v2 ยังคงอยู่ใน `models/retrained_v2_perspective` และไม่ได้เขียนทับ

รายละเอียดผลและข้อจำกัดอยู่ใน [รายงาน v3](../../V3_TRAINING_RESULTS.md)

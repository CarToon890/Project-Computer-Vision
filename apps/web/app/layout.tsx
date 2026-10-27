import type {Metadata} from 'next';
import './style.css';
export const metadata:Metadata={title:'OMR · ตรวจคำตอบ',description:'พื้นที่ส่วนตัวสำหรับอ่าน ตรวจยืนยัน และส่งออกคะแนนกระดาษคำตอบ'};
export default function Layout({children}:{children:React.ReactNode}) {return <html lang="th"><body>{children}</body></html>;}

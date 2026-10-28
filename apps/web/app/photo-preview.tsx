'use client';
import {useEffect,useState} from 'react';
export default function PhotoPreview({file,role}:{file?:File|null;role:string}) {
  const [src,setSrc]=useState(''),[failed,setFailed]=useState(false);
  useEffect(()=>{
    if(!file){setSrc('');return;}
    const url=URL.createObjectURL(file);setSrc(url);setFailed(false);
    return ()=>URL.revokeObjectURL(url);
  },[file]);
  if(!file||!src)return null;
  return failed?<p className="muted">แสดงภาพตัวอย่างไม่ได้ แต่ยังเลือกไฟล์นี้ได้</p>:<img className="preview" src={src} alt={`ภาพตัวอย่าง ${role}`} onError={()=>setFailed(true)}/>;
}

'use client';
import {useEffect,useRef,useState} from 'react';
import {upload} from '@vercel/blob/client';
import ExamKeys from './exam-keys';
import Sessions from './sessions';

type AnswerRow={question_no:number;proposed_answer:string;needs_review:boolean;selected_confidence:number;review_reasons:string};
type Job={id:string;status:string;revision:number;created_at:string;images_expires_at:string;images_expired?:boolean;error_message?:string;is_test?:boolean;
  session_sheet_id?:string|null;result?:{methods:Record<string,AnswerRow[]>;assets:Record<string,Record<string,string>>;model_version:string;pair_check:unknown;errors:Record<string,string>};
  sources:Record<string,string>;reviews:Record<string,Record<string,{answer:string}>>;grading?:{key:(string|null)[]};scores?:Record<string,{automatic:number;current:number;confirmed:number;final:boolean;completeKey:boolean}>};
type History=Pick<Job,'id'|'status'|'created_at'|'images_expires_at'|'error_message'|'is_test'>;
const labels:Record<string,string>={blank:'เว้นว่าง',multiple:'ฝนหลายช่อง',ambiguous:'ยังอ่านไม่ชัด',draft:'รอภาพ',ready:'พร้อมอ่าน',processing:'กำลังอ่าน',complete:'อ่านแล้ว',failed:'อ่านไม่สำเร็จ',interrupted:'หยุดกลางทาง'};
const mark=(s:string)=>labels[s]||s||'ยังไม่มีคำตอบ';
const date=(s:string)=>new Date(s).toLocaleString('th-TH',{dateStyle:'medium',timeStyle:'short'});
async function api(path:string,data?:unknown) {
  const res=await fetch('/api/'+path,{method:data===undefined?'GET':'POST',headers:data===undefined?{}:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data),cache:'no-store'});
  const result=await res.json();if(!res.ok)throw new Error(result.error||'เชื่อมต่อไม่ได้ กรุณาลองใหม่');return result;
}
async function demoSheet():Promise<File> {
  // Draw a synthetic form from geometry only; no student photo or labels are used.
  const canvas=document.createElement('canvas');canvas.width=1000;canvas.height=1333;
  const ctx=canvas.getContext('2d');if(!ctx)throw Error('อุปกรณ์นี้สร้างภาพตัวอย่างไม่ได้ กรุณาเลือกภาพเอง');
  ctx.fillStyle='white';ctx.fillRect(0,0,1000,1333);ctx.fillStyle='#111';
  for(const [x,y] of [[145,1168],[892,1160],[877,77]])ctx.fillRect(x-20,y-20,40,40);
  const xs=Array.from({length:20},(_,i)=>210+Math.floor(i/5)*170+(i%5)*25);
  for(const x of xs){ctx.fillRect(x-3,302,6,20);ctx.fillRect(x-3,1082,6,20);}
  ctx.font='14px sans-serif';ctx.textAlign='right';ctx.textBaseline='middle';
  for(let row=0;row<25;row++){
    const y=355+row*26+Math.floor(row/5)*15;
    ctx.fillRect(130,y-3,20,6);ctx.fillRect(880,y-3,20,6);
    for(let col=0;col<4;col++){
      const question=col*25+row+1;ctx.fillText(String(question),xs[col*5]-19,y);
      for(let option=0;option<5;option++){
        const x=xs[col*5+option];ctx.beginPath();ctx.arc(x,y,11,0,2*Math.PI);ctx.lineWidth=1.5;ctx.stroke();
        if(option===question%5){ctx.beginPath();ctx.arc(x,y,8,0,2*Math.PI);ctx.fill();}
      }
    }
  }
  const blob=await new Promise<Blob|null>(resolve=>canvas.toBlob(resolve,'image/png'));
  if(!blob)throw Error('สร้างภาพตัวอย่างไม่ได้ กรุณาเลือกภาพเอง');
  return new File([blob],'omr-demo.png',{type:'image/png'});
}
export default function Home() {
  const [logged,setLogged]=useState(false),[checking,setChecking]=useState(true),[password,setPassword]=useState('');
  const [temporaryAccess,setTemporaryAccess]=useState(false);
  const [demo,setDemo]=useState(false);
  const [tab,setTab]=useState('start'),[job,setJob]=useState<Job|null>(null),[history,setHistory]=useState<History[]>([]);
  const [moreBefore,setMoreBefore]=useState<string|null>(null);
  const [sessionId,setSessionId]=useState('');
  const [files,setFiles]=useState<Record<string,File>>({}),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[error,setError]=useState('');
  const errorRef=useRef<HTMLDivElement>(null);
  useEffect(()=>{api('me').then(result=>{setTemporaryAccess(!!result.temporaryPreviewAccess);setDemo(!!result.demo);setLogged(true);}).catch(()=>{}).finally(()=>setChecking(false));},[]);
  useEffect(()=>{if(error)errorRef.current?.focus();},[error]);
  async function perform(action:()=>Promise<void>) {setBusy(true);setError('');setMessage('');try{await action();}catch(e){setError(e instanceof Error?e.message:'เกิดข้อผิดพลาด กรุณาลองใหม่');}finally{setBusy(false);}}
  async function refreshHistory(before?:string){const data=await api('jobs'+(before?'?before='+before:''));setHistory(old=>before?[...old,...data.jobs.filter((r:History)=>!old.some(x=>x.id===r.id))]:data.jobs);setMoreBefore(data.nextBefore);}
  useEffect(()=>{if(logged)refreshHistory().catch(()=>setError('เปิดประวัติไม่ได้ กรุณาลองใหม่'));},[logged]);
  useEffect(()=>{if(job?.status!=='processing')return;const interval=setInterval(()=>{api('jobs/'+job.id).then(setJob).catch(()=>{});},5000);return()=>clearInterval(interval);},[job?.id,job?.status]);
  async function start() {
    if(!files.A)throw Error('เลือกหรือถ่ายภาพกระดาษคำตอบก่อนเริ่มอ่าน');
    let current=job && ['draft','ready','failed','interrupted'].includes(job.status)?job:await api('jobs',{});
    setJob(current);
    for(const role of ['A']) {
      const file=files[role];if(!file)continue;
      const ext=file.name.split('.').pop()?.toLowerCase()||'jpg';
      const type=file.type||({jpg:'image/jpeg',jpeg:'image/jpeg',png:'image/png',heic:'image/heic',heif:'image/heif'} as Record<string,string>)[ext];
      if(file.size>20*1024*1024)throw Error(`ภาพใหญ่เกิน 20 MiB กรุณาเลือกไฟล์ขนาดเล็กลง`);
      setMessage(`กำลังอัปโหลดภาพ…`);
      const grant=await api(`jobs/${current.id}/upload`,{role,size:file.size,type,ext});
      await upload(grant.pathname,file,{access:'private',handleUploadUrl:'/api/upload',contentType:type,multipart:file.size>5*1024*1024,
        onUploadProgress:({percentage})=>setMessage(`กำลังอัปโหลดภาพ ${Math.round(percentage)}%`)});
      current=await api(`jobs/${current.id}/upload-complete`,{pathname:grant.pathname});setJob(current);
    }
    setMessage('กำลังอ่านภาพ กรุณารอสักครู่ งานถูกบันทึกในประวัติแล้ว');
    setFiles({});
    try {const result=await api(`jobs/${current.id}/read`,{});setJob(result);setTab('review');setMessage('อ่านภาพเสร็จแล้ว ขั้นต่อไปตรวจรอยฝนและยืนยันคำตอบ จากนั้นไปที่คะแนนและส่งออก');await refreshHistory();}
    catch(e){try{setJob(await api('jobs/'+current.id));}catch{}throw e;}
  }
  function choose(role:string,file?:File){if(!file)return;setFiles(old=>({...old,[role]:file}));setJob(null);setError('');}
  function clearPhoto(role:string){setFiles(old=>{const next={...old};delete next[role];return next;});setJob(null);}
  const nav=[['start','เริ่มตรวจ'],['review','ตรวจคำตอบ'],['score','คะแนนและส่งออก'],['sessions','ตรวจเป็นชุด'],['history','ประวัติงาน']];
  return <><a className="skip" href="#main">ข้ามไปเนื้อหา</a><header><a className="brand" href="/">OMR<span>{demo?'เว็บสาธิตตรวจคำตอบ':'พื้นที่ตรวจคำตอบส่วนตัว'}</span></a>{logged&&!temporaryAccess&&<button onClick={()=>perform(async()=>{await api('logout',{});setLogged(false);setPassword('');setJob(null);setFiles({});setHistory([]);})} disabled={busy}>ออกจากระบบ</button>}</header>
    <main id="main">{error&&<div className="error" role="alert" tabIndex={-1} ref={errorRef}>{error}<button onClick={()=>setError('')} aria-label="ปิดข้อความผิดพลาด">ปิด</button></div>}
    {checking?<p role="status">กำลังตรวจการเข้าสู่ระบบ…</p>:!logged?<section className="login"><h1>กลับมาตรวจคำตอบต่อ</h1><p>เข้าสู่พื้นที่ส่วนตัวของคุณ งานและคำตอบที่บันทึกไว้จะยังอยู่ที่นี่</p><form onSubmit={e=>{e.preventDefault();perform(async()=>{await api('login',{password});setPassword('');setLogged(true);});}}><label htmlFor="password">รหัสผ่านส่วนตัว</label><input id="password" type="password" autoComplete="current-password" required value={password} onChange={e=>setPassword(e.target.value)}/><button className="primary" disabled={busy}>{busy?'กำลังเข้าสู่ระบบ…':'เข้าสู่ระบบ'}</button></form><p className="muted">สำหรับเจ้าของเว็บเท่านั้น ไม่มีการสมัครสมาชิก</p></section>:<>
    <nav aria-label="ขั้นตอนตรวจข้อสอบ">{nav.map(([key,label])=><button key={key} aria-current={tab===key?'page':undefined} onClick={()=>setTab(key)} disabled={busy||key==='review'&&!job?.result}>{label}</button>)}</nav>
    {demo&&<p className="notice">เว็บสาธิตโครงงาน · ภาพตัวอย่างสร้างด้วยคอมพิวเตอร์เพื่อสาธิตขั้นตอน ไม่ใช่ผลวัดความแม่นยำจริง หากเลือกภาพเอง กรุณาใช้ภาพที่ไม่มีข้อมูลส่วนตัว</p>}
    {message&&<p className="notice" role="status">{message}</p>}
    {job?.is_test&&<p className="notice">งานทดสอบระบบ · คำตอบยืนยันและเฉลยในงานนี้ใช้ทดสอบฟังก์ชันเท่านั้น ห้ามนำคะแนนไปตัดสินผลสอบ</p>}
    {tab==='start'&&<><div className="heading"><div><h1>ตรวจข้อสอบจากภาพกระดาษคำตอบ</h1><p>เริ่มจากถ่ายหรือเลือกภาพกระดาษ 1 แผ่น แล้วทำตามขั้นตอนบนหน้าจอ</p></div></div><ol className="workflow" aria-label="ขั้นตอนการใช้งาน"><li className="current"><strong>1. เลือกภาพ</strong><span>ถ่ายหรือเลือกไฟล์</span></li><li><strong>2. ตรวจคำตอบ</strong><span>ดูรอยฝนและยืนยัน</span></li><li><strong>3. คิดคะแนน</strong><span>ใส่เฉลยและส่งออก</span></li></ol><section className="workspace"><h2>เริ่มจากภาพกระดาษคำตอบ</h2><p className="muted">วางกระดาษบนพื้นเรียบ ให้เห็นจุดอ้างอิงครบ หลีกเลี่ยงแสงสะท้อนและเงาทับรอยฝน</p>{demo&&<button disabled={busy} onClick={()=>perform(async()=>choose('A',await demoSheet()))}>ใช้ภาพตัวอย่างสำหรับสาธิต</button>}<div className="upload-grid single-photo"><Photo role="A" file={files.A} choose={choose} clear={clearPhoto} disabled={busy}/></div>
    <p className="muted">JPEG, PNG หรือ HEIC · สูงสุด 20 MiB และ 24 ล้านพิกเซลต่อภาพ · ระบบจะไม่ย่อภาพให้เงียบ ๆ</p><div className="actions"><button className="primary" disabled={busy||!files.A||job?.status==='processing'} onClick={()=>perform(start)}>{busy?'กำลังทำงาน…':'อัปโหลดและอ่านคำตอบ'}</button>{job?.sources?.A&&['ready','failed','interrupted'].includes(job.status)&&<button disabled={busy} onClick={()=>perform(async()=>{setMessage('กำลังอ่านภาพที่บันทึกไว้…');const result=await api(`jobs/${job.id}/read`,{});setJob(result);setTab('review');await refreshHistory();})}>อ่านภาพที่บันทึกไว้ต่อ</button>}<button disabled={busy||job?.status==='processing'} onClick={()=>{setJob(null);setFiles({});setMessage('');}}>เริ่มแผ่นใหม่</button></div>{job?.status==='processing'&&<p role="status">งานกำลังอ่านอยู่ เปิดสถานะต่อได้จากประวัติงาน</p>}</section>
    <section className="guide"><h2>หลังจากเลือกภาพแล้วต้องทำอะไร?</h2><ol><li><strong>ถ่ายหรือเลือกภาพกระดาษคำตอบ</strong> ถ่ายให้เห็นกระดาษทั้งแผ่นและจุดอ้างอิงครบ</li><li><strong>ตรวจคำตอบจากรอยฝน</strong> เริ่มข้อที่ต้องตรวจเพิ่ม แล้วตรวจข้ออื่นด้วย โมเดลอาจมั่นใจแต่ตอบผิดได้</li><li><strong>สร้างหรือเลือกเฉลย</strong> ถ่ายใบเฉลย ตรวจและยืนยัน แล้วนำมาใช้คิดคะแนน</li><li><strong>ส่งออกผล CSV</strong> คะแนนเป็นช่วงจนตรวจข้อที่ระบบแจ้งเตือนครบ</li></ol></section></>}
    {job?.result&&<div hidden={tab!=='review'}><Review job={job} setJob={setJob} perform={perform} busy={busy} active={tab==='review'} inSession={!!job.session_sheet_id} onNext={()=>setTab(job.session_sheet_id?'sessions':'score')}/></div>}
    {tab==='score'&&<div>{job?.session_sheet_id&&<p className="notice">งานนี้อยู่ในชุดตรวจ เปลี่ยนเฉลยและดูคะแนนได้ที่หน้าตรวจเป็นชุด</p>}<ExamKeys job={job?.result&&!job.session_sheet_id?job:null} setJob={setJob} perform={perform} busy={busy}/>{job?.result&&!job.session_sheet_id&&<details><summary>กรอกเฉลยด้วยตนเอง / งานเดิม</summary><Grading job={job} setJob={setJob} perform={perform} busy={busy} demo={demo}/></details>}</div>}
    {tab==='sessions'&&<Sessions selectedId={sessionId} setSelectedId={setSessionId} perform={perform} busy={busy} demo={demo} onOpenJob={async(id)=>{setJob(await api('jobs/'+id));setTab('review');}}/>}
    {tab==='history'&&<section><div className="section-title"><h1>ประวัติงาน</h1><button disabled={busy} onClick={()=>perform(refreshHistory)}>อัปเดตประวัติ</button></div><p className="muted">ภาพเก็บ 7 วัน คำตอบ เฉลย และคะแนนยังเปิดต่อและส่งออกได้หลังภาพหมดอายุ</p>{!history.length?<div className="empty"><h2>ยังไม่มีงานตรวจ</h2><p>เริ่มจากภาพกระดาษคำตอบหนึ่งแผ่น งานจะบันทึกไว้ที่นี่</p><button className="primary" onClick={()=>setTab('start')}>เริ่มตรวจแผ่นแรก</button></div>:<div className="history">{history.map((item,i)=><article key={item.id}><div><h2>กระดาษคำตอบ · {date(item.created_at)}{item.is_test?' · งานทดสอบระบบ':''}</h2><p>{labels[item.status]||item.status} · {new Date(item.images_expires_at)>new Date()?`ดูภาพได้ถึง ${date(item.images_expires_at)}`:'ภาพหมดอายุแล้ว'}</p></div><button disabled={busy} onClick={()=>perform(async()=>{const current=await api('jobs/'+item.id);setJob(current);setFiles({});setTab(current.result?'review':'start');setMessage(current.result?'เปิดงานที่บันทึกไว้แล้ว':'งานนี้ยังอ่านไม่เสร็จ เลือกภาพใหม่หรือกดอ่านต่อ');})}>เปิดงาน{ i===0?'ล่าสุด':''}</button><DeleteJobButton jobId={item.id} busy={busy} perform={perform} onDeleted={async()=>{if(job?.id===item.id)setJob(null);await refreshHistory();setMessage('ลบคำตอบ เฉลย และคะแนนแล้ว ปิดการเข้าถึงภาพแล้ว');}}/></article>)}</div>}{moreBefore&&<button disabled={busy} onClick={()=>perform(()=>refreshHistory(moreBefore))}>โหลดงานเก่าเพิ่มเติม</button>}</section>}
    <footer>ภาพเปิดดูได้ 7 วัน และลบในรอบทำความสะอาดประจำวันถัดไป · คำตอบและคะแนนเก็บต่อจนสั่งลบ<br/>ใช้เฉพาะบริการแผนฟรี · ผลอ่านอัตโนมัติต้องตรวจยืนยันก่อนนำคะแนนไปใช้จริง</footer>
    </>}</main></>;
}
function DeleteJobButton({jobId,onDeleted,perform,busy}:{jobId:string;onDeleted:()=>Promise<void>;perform:(f:()=>Promise<void>)=>Promise<void>;busy:boolean}) {
  return <button disabled={busy} onClick={()=>{
    if(!window.confirm('ลบคำตอบ เฉลย และคะแนนของงานนี้ถาวรหรือไม่? ภาพจะเปิดดูไม่ได้ทันที และไฟล์จะลบตามรอบเก็บ 7 วัน'))return;
    perform(async()=>{const response=await fetch(`/api/jobs/${jobId}`,{method:'DELETE'});const result=await response.json();if(!response.ok)throw Error(result.error);await onDeleted();});
  }}>ลบงาน</button>;
}
function Photo({role,file,choose,clear,disabled}:{role:string;file?:File;choose:(r:string,f?:File)=>void;clear:(r:string)=>void;disabled:boolean}) {
  const [preview,setPreview]=useState(''),[unavailable,setUnavailable]=useState(false);
  useEffect(()=>{if(!file){setPreview('');return;}const value=URL.createObjectURL(file);setPreview(value);setUnavailable(false);return()=>URL.revokeObjectURL(value);},[file]);
  return <div className="photo"><h3>ภาพกระดาษคำตอบ</h3><p>วางกระดาษให้เรียบ ถ่ายตรงจากด้านบน และให้เห็นกระดาษครบทั้งแผ่น</p>{preview&&!unavailable?<img className="preview" src={preview} alt="ภาพกระดาษคำตอบที่เลือก" onError={()=>setUnavailable(true)}/>:file&&<p>เลือกไฟล์แล้ว หากเครื่องเปิด HEIC ไม่ได้ ระบบจะแปลงหลังอัปโหลด</p>}<div className="actions"><label className="file-button">เลือกภาพ<input disabled={disabled} type="file" accept="image/jpeg,image/png,image/heic,image/heif,.heic,.heif" onChange={e=>choose(role,e.target.files?.[0])}/></label><label className="file-button">ถ่ายภาพ<input disabled={disabled} type="file" accept="image/*" capture="environment" onChange={e=>choose(role,e.target.files?.[0])}/></label></div>{file&&<button disabled={disabled} onClick={()=>clear(role)}>นำภาพนี้ออก</button>}<p className="filename">{file?file.name:'ยังไม่ได้เลือกภาพ'}</p></div>;
}
function Review({job,setJob,perform,busy,active,onNext,inSession}:{job:Job;setJob:(j:Job)=>void;perform:(f:()=>Promise<void>)=>Promise<void>;busy:boolean;active:boolean;onNext:()=>void;inSession:boolean}) {
  const [method,setMethod]=useState('cnn'),[filter,setFilter]=useState('all'),[q,setQ]=useState(1),[answer,setAnswer]=useState('');
  const [images,setImages]=useState<Record<string,string>>({}),[loaded,setLoaded]=useState<Record<string,boolean>>({}),[imageError,setImageError]=useState(''),[expired,setExpired]=useState(job.images_expired||false);
  const rows=job.result!.methods[method],human=job.reviews?.[method]||{},row=rows[q-1];
  const confirmed=Object.keys(human).length,risks=rows.filter(r=>r.needs_review&&!human[r.question_no]).length;
  const visible=rows.filter(r=>filter==='all'||filter==='risk'&&r.needs_review&&!human[r.question_no]||filter==='pending'&&!human[r.question_no]||filter==='done'&&human[r.question_no]);
  useEffect(()=>{setAnswer(human[q]?.answer||'');},[q,method,job.revision,job.id]);
  useEffect(()=>{setMethod('cnn');setFilter('all');setQ(job.result!.methods.cnn.find(r=>!job.reviews?.cnn?.[r.question_no])?.question_no||1);},[job.id]);
  useEffect(()=>{setExpired(job.images_expired||new Date(job.images_expires_at)<=new Date());},[job.images_expired,job.images_expires_at]);
  useEffect(()=>{
    setImages({});setLoaded({});setImageError('');if(expired)return;
    const urls:string[]=[],controller=new AbortController();
    Promise.all(Object.keys(job.result!.assets).map(async role=>{const response=await fetch(`/api/jobs/${job.id}/image?role=${role}&view=rows`,{signal:controller.signal});if(!response.ok)throw Error('เปิดภาพไม่ได้ กรุณาโหลดงานล่าสุด');const url=URL.createObjectURL(await response.blob());urls.push(url);return [role,url];})).then(items=>setImages(Object.fromEntries(items))).catch(e=>{if(e.name!=='AbortError')setImageError(e.message);});
    const timeout=setTimeout(()=>setExpired(true),Math.max(0,new Date(job.images_expires_at).getTime()-Date.now()));
    return()=>{controller.abort();clearTimeout(timeout);urls.forEach(URL.revokeObjectURL);};
  },[job.id,expired]);
  const canConfirm=!expired&&!busy&&!!Object.keys(images).length&&Object.keys(images).every(role=>loaded[role])&&!imageError&&visible.some(r=>r.question_no===q);
  function move(delta:number){const position=visible.findIndex(r=>r.question_no===q);const next=visible[position+delta];if(next)setQ(next.question_no);}
  async function confirm(){const chosen=answer||row.proposed_answer;if(!['1','2','3','4','5','blank','multiple'].includes(chosen))throw Error('ข้อนี้ยังอ่านไม่ชัด กรุณาเลือกคำตอบจากภาพเอง');const updated=await api(`jobs/${job.id}/review`,{revision:job.revision,method,question:q,answer:chosen});setJob(updated);const candidates=visible.filter(r=>r.question_no!==q);const next=candidates.find(r=>r.question_no>q)||candidates[0];if(next)setQ(next.question_no);}
  useEffect(()=>{
    function shortcut(e:KeyboardEvent){const target=e.target as HTMLElement;if(!active||target.closest('input,textarea,select,a')||e.ctrlKey||e.altKey||e.metaKey)return;
      if(/^[1-5]$/.test(e.key)){setAnswer(e.key);e.preventDefault();}
      else if(e.key.toLowerCase()==='b')setAnswer('blank');else if(e.key.toLowerCase()==='m')setAnswer('multiple');
      else if(e.key==='ArrowRight'||e.key==='.')move(1);else if(e.key==='ArrowLeft')move(-1);
      else if(e.key==='Escape')setAnswer(human[q]?.answer||'');
      else if(e.key==='Enter'&&canConfirm&&(!target.closest('button')||target.closest('.answer-choices')||target.closest('.question-grid button[aria-current="true"]'))){e.preventDefault();perform(confirm);}
    }window.addEventListener('keydown',shortcut);return()=>window.removeEventListener('keydown',shortcut);
  });
  return <><div className="section-title"><h1>ตรวจรอยฝนและยืนยันคำตอบ</h1><button disabled={busy} onClick={()=>perform(async()=>setJob(await api('jobs/'+job.id)))}>โหลดงานล่าสุด</button></div><p>ยืนยันโดยคนแล้ว <strong>{confirmed}/100 ข้อ</strong> · โมเดลแจ้งให้ตรวจเพิ่ม {risks} ข้อ</p><p className="notice">ตรวจข้อที่ระบบแจ้งเตือนและแก้คำตอบได้ทุกข้อ ระบบอาจอ่านผิดแม้ไม่แจ้งเตือน</p>{expired&&<p className="error">ภาพหมดอายุแล้ว ยืนยันเพิ่มไม่ได้ แต่ยังดูคำตอบและส่งออกผลได้</p>}
    <div className="filters" aria-label="กรองข้อคำตอบ">{[['all','ทุกข้อ',100],['risk','ต้องตรวจเพิ่ม',risks],['pending','ยังไม่ยืนยัน',100-confirmed],['done','ยืนยันแล้ว',confirmed]].map(([key,label,count])=><button key={key} aria-pressed={filter===key} onClick={()=>{setFilter(String(key));const next=rows.find(r=>key==='all'||key==='risk'&&r.needs_review&&!human[r.question_no]||key==='pending'&&!human[r.question_no]||key==='done'&&human[r.question_no]);if(next)setQ(next.question_no);}}>{label} ({count})</button>)}</div>
    <div className="next-step"><div><strong>{inSession?'ขั้นต่อไป: กลับชุดตรวจ':'ขั้นต่อไป: ใส่เฉลย'}</strong><p>{inSession?'กลับไปดูคะแนนและตรวจใบถัดไป':'ตรวจข้อที่ระบบแจ้งเตือน แล้วเลือกเฉลยเพื่อดูคะแนน'}</p></div><button className="primary" disabled={busy} onClick={onNext}>{inSession?'กลับไปชุดตรวจ':'ต่อไป: ใส่เฉลยและดูคะแนน'}</button></div><div className="review-layout"><aside aria-label="เลือกข้อ"><div className="question-grid">{visible.map(r=><button key={r.question_no} aria-label={`ข้อ ${r.question_no} ${human[r.question_no]?'ยืนยันแล้ว':r.needs_review?'ต้องตรวจเพิ่ม':'ยังไม่ยืนยัน'}`} aria-current={q===r.question_no?'true':undefined} className={human[r.question_no]?'done':r.needs_review?'risk':''} onClick={()=>setQ(r.question_no)}>{r.question_no}{human[r.question_no]&&<small>ยืนยัน</small>}</button>)}</div>{!visible.length&&<p>ไม่มีข้อในตัวกรองนี้</p>}</aside>
    <section className="question" hidden={!visible.some(r=>r.question_no===q)}><div className="section-title"><h2>ข้อ {q}</h2><span>{human[q]?'ยืนยันแล้ว':'ยังไม่ยืนยัน'}</span></div>{imageError&&<p role="alert" className="error">{imageError}</p>}{!expired&&Object.entries(images).map(([role,src])=><figure key={role}><figcaption>รอยฝนบนกระดาษ{role==='B'?' (ภาพเดิมเพิ่มเติม)':''}</figcaption><div className="strip"><img src={src} onLoad={()=>setLoaded(old=>({...old,[role]:true}))} onError={()=>setImageError('เปิดภาพรอยฝนไม่ได้ กรุณาโหลดงานล่าสุด')} alt={`รอยฝนข้อ ${q} ภาพ ${role}`} style={{top:`-${(q-1)*100}%`}}/></div><a target="_blank" rel="noreferrer" href={`/api/jobs/${job.id}/image?role=${role}&view=registered`}>เปิดภาพกระดาษเต็มเพื่อซูม</a></figure>)}{!expired&&!Object.keys(images).length&&!imageError&&<p role="status">กำลังเปิดภาพรอยฝน…</p>}
    <p>คำตอบที่ระบบอ่านได้: <strong>{mark(row.proposed_answer)}</strong>{row.needs_review?' · ต้องตรวจเพิ่มเติม':''}</p><div className="answer-choices" aria-label="เลือกคำตอบที่เห็นจากกระดาษ">{['1','2','3','4','5','blank','multiple'].map(value=><button key={value} disabled={busy||expired} aria-pressed={answer===value} className={row.proposed_answer===value?'suggested':''} onClick={()=>setAnswer(value)}>{mark(value)}{row.proposed_answer===value&&<small>โมเดลเสนอ</small>}</button>)}</div>
    <div className="actions"><button className="primary" disabled={!canConfirm} onClick={()=>perform(confirm)}>ยืนยัน {mark(answer||row.proposed_answer)} และไปข้อถัดไป</button><button disabled={busy} onClick={()=>move(-1)}>ข้อก่อนหน้า</button><button disabled={busy} onClick={()=>move(1)}>ข้อถัดไป</button></div><p className="muted">คีย์ลัดเมื่อไม่ได้โฟกัสปุ่ม: 1–5 เลือก · B เว้นว่าง · M หลายช่อง · Enter ยืนยัน · ลูกศรเปลี่ยนข้อ</p></section></div>
    <details className="developer"><summary>เครื่องมือนักพัฒนา · CNN / CLA</summary><label>วิธีอ่าน <select value={method} onChange={e=>{setMethod(e.target.value);setFilter('all');}}><option value="cnn">CNN v3</option><option value="cla">CLA</option></select></label><p>รุ่น {job.result!.model_version} · confidence ข้อนี้ {row.selected_confidence?.toFixed(4)}</p><p>สัญญาณตรวจเพิ่ม: {row.review_reasons||'ไม่มี'}</p><pre>{JSON.stringify(job.result!.pair_check,null,2)}</pre></details></>;
}
function Grading({job,setJob,perform,busy,demo}:{job:Job;setJob:(j:Job)=>void;perform:(f:()=>Promise<void>)=>Promise<void>;busy:boolean;demo:boolean}) {
  const [text,setText]=useState((job.grading?.key||[]).map(v=>v||'-').join(' '));
  useEffect(()=>setText((job.grading?.key||[]).map(v=>v||'-').join(' ')),[job.id]);
  const scores=job.scores?.cnn;
  async function save(value=text){const tokens=value.trim()?value.trim().split(/\s+/):[];if(tokens.length>100||tokens.some(x=>!/^([1-5]|-)$/.test(x)))throw Error('ใส่เฉลย 1–5 คั่นด้วยช่องว่าง ใช้ - แทนข้อที่ยังไม่มี สูงสุด 100 ข้อ');const key=Array.from({length:100},(_,i)=>tokens[i]&&tokens[i]!=='-'?tokens[i]:null);setJob(await api(`jobs/${job.id}/score`,{revision:job.revision,key}));}
  return <section><h1>ใส่เฉลยและดูคะแนน</h1><p>ขั้นตอนสุดท้าย: ใส่เฉลยข้อสอบตามลำดับข้อ 1–100 แล้วกดคำนวณคะแนน</p><div className="workspace"><label htmlFor="key"><strong>เฉลยข้อสอบจริง</strong></label><p id="key-help" className="muted">คั่นด้วยช่องว่าง ใช้ - แทนข้อที่ยังไม่มี อย่าข้ามตำแหน่งกลางชุด</p><textarea id="key" rows={5} aria-describedby="key-help" value={text} onChange={e=>setText(e.target.value)} placeholder="กรอกเฉลยตามลำดับข้อ"/><button className="primary" disabled={busy} onClick={()=>perform(()=>save())}>บันทึกเฉลยและคำนวณคะแนน</button>{demo&&<p><button disabled={busy} onClick={()=>perform(async()=>{const example=Array.from({length:100},(_,i)=>String(((i+1)%5)+1)).join(' ');setText(example);await save(example);})}>ใส่และคำนวณเฉลยภาพตัวอย่าง</button><span className="muted"> สำหรับภาพตัวอย่างที่ระบบสร้างเท่านั้น</span></p>}</div>
    <section className="score"><h2>{scores?.final?'คะแนนหลังยืนยันครบ':'คะแนนชั่วคราว'}</h2>{!scores?.completeKey?<p>เฉลยยังไม่ครบ 100 ข้อ กรุณากรอกให้ครบก่อนสรุปคะแนน</p>:<><p className="score-value">{scores?.current}<span> / 100</span></p><p>คะแนนอัตโนมัติจาก CNN ก่อนคนตรวจ {scores?.automatic}/100 · ยืนยันคำตอบแล้ว {scores?.confirmed}/100 ข้อ</p></>}{!scores?.final&&<p>คะแนนยังใช้ตัดสินผลสอบไม่ได้ ต้องมีเฉลยครบและคนยืนยันคำตอบครบทุกข้อ</p>}<a className="button" href={`/api/jobs/${job.id}/export`}>ดาวน์โหลดผล CSV</a><p className="muted">CSV แยกคำตอบ CNN/CLA เดิม คำตอบหลังคนตรวจ เฉลย และสถานะคะแนน</p></section></section>;
}

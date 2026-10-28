'use client';
import {useEffect,useState} from 'react';
import {uploadPhotos} from '../lib/upload-photos';

type Key={id:string;name:string;answers:string[];rules:{full:number;penalty:number};created_at:string;version:number};
async function api(path:string,data?:unknown,method?:string) {
  const res=await fetch('/api/'+path,{method:method || (data===undefined?'GET':'POST'),headers:data===undefined?{}:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data),cache:'no-store'});
  const body=await res.json();if(!res.ok)throw Error(body.error||'เกิดข้อผิดพลาด กรุณาลองใหม่');return body;
}
const fmt=(n:number)=>new Intl.NumberFormat('th-TH',{maximumFractionDigits:3}).format(n);
export default function ExamKeys({job,setJob,perform,busy}:{job:any;setJob:(j:any)=>void;perform:(f:()=>Promise<void>)=>Promise<void>;busy:boolean}) {
  const [keys,setKeys]=useState<Key[]>([]),[selected,setSelected]=useState(''),[name,setName]=useState(''),[files,setFiles]=useState<Record<string,File>>({});
  const [draft,setDraft]=useState<any>(null),[answers,setAnswers]=useState<string[]>([]),[question,setQuestion]=useState(1);
  const [full,setFull]=useState('100'),[penalty,setPenalty]=useState('0'),[message,setMessage]=useState('');
  const [expanded,setExpanded]=useState(false),[editId,setEditId]=useState('');
  async function refresh(){const r=await api('exam-keys');setKeys(r.keys);}
  useEffect(()=>{refresh().catch(()=>setMessage('โหลดรายการเฉลยไม่ได้ กรุณาลองใหม่'));},[]);
  function select(id:string){setSelected(id);const k=keys.find(x=>x.id===id);if(k){setFull(String(k.rules.full));setPenalty(String(k.rules.penalty));}}
  function getRules(){const f=Number(full),p=Number(penalty);if(!Number.isFinite(f)||f<=0||!Number.isFinite(p)||p<0||full.trim()===''||penalty.trim()==='')throw Error('กรอกคะแนนเต็มมากกว่า 0 และคะแนนหักตั้งแต่ 0 ขึ้นไป');return {full:f,penalty:p};}
  async function readSheet(){
    if(!files.A)throw Error('กรุณาเลือกภาพใบเฉลย A');
    const current=draft && !draft.result ? draft : await api('jobs',{});setDraft(current);
    await uploadPhotos(current.id,[{role:'A',file:files.A},...(files.B?[{role:'B' as const,file:files.B}]:[])],api,setMessage);
    setMessage('กำลังอ่านใบเฉลย…');const read=await api(`jobs/${current.id}/read`,{});
    if(!read.result?.methods?.cnn || read.result.methods.cnn.length!==100)throw Error('อ่านใบเฉลยไม่ครบ กรุณาใช้ภาพใหม่');
    setDraft(read);setAnswers(read.result.methods.cnn.map((r:any)=>/^[1-5]$/.test(r.proposed_answer)?r.proposed_answer:''));setQuestion(1);setMessage('ตรวจภาพและแก้คำตอบก่อนยืนยันเฉลยทั้งชุด');
  }
  async function save(){
    const k=await api('exam-keys',{name,answers,rules:getRules(),parentId:editId || undefined});await refresh();setSelected(k.id);setExpanded(false);setDraft(null);setAnswers([]);setFiles({});setEditId('');setMessage('บันทึกเฉลยแล้ว เลือกใช้กับกระดาษคำตอบได้ทันที');
  }
  async function apply(){if(!selected)throw Error('กรุณาเลือกเฉลย');setJob(await api(`jobs/${job.id}/apply-key`,{keyId:selected,revision:job.revision,rules:getRules()}));setMessage('บันทึกเฉลยและคำนวณคะแนนแล้ว');}
  const score=job?.riskScores?.cnn, row=draft?.result?.methods?.cnn?.[question-1], remaining=answers.filter(a=>!/^[1-5]$/.test(a)).length;
  return <section className="exam-keys"><h2>เฉลยจากภาพกระดาษ</h2><p>ถ่ายใบเฉลยที่ฝนคำตอบถูกไว้ ตรวจและยืนยัน แล้วใช้เฉลยเดียวกันกับกระดาษนักเรียนหลายใบ</p>
    {message&&<p className="notice" role="status">{message}</p>}
    <div className="actions"><button disabled={busy} onClick={()=>{setExpanded(!expanded);setDraft(null);setAnswers([]);setEditId('');setName('');setFiles({});}}>{expanded?'ปิดการสร้างเฉลย':'สร้างเฉลยจากภาพ'}</button><button disabled={busy} onClick={()=>perform(refresh)}>โหลดรายการเฉลย</button></div>
    {expanded&&<div className="workspace"><h3>{editId?'แก้ไขเป็นเฉลยฉบับใหม่':'สร้างเฉลยจากภาพ'}</h3><label>ชื่อวิชาหรือชุดสอบ <input maxLength={120} value={name} onChange={e=>setName(e.target.value)} /></label>
      {!draft?.result&&!editId&&<><p>ใช้กระดาษแบบเดียวกับนักเรียน ถ่ายให้เห็นทั้งแผ่น</p><div className="upload-grid">{['A','B'].map(role=><div className="photo" key={role}><h3>ภาพ {role} {role==='B'?'(ไม่บังคับ)':''}</h3><div className="actions"><label className="file-button">เลือกภาพ<input disabled={busy} type="file" accept="image/jpeg,image/png,image/heic,image/heif,.heic,.heif" onChange={e=>{const f=e.target.files?.[0];if(f)setFiles(old=>({...old,[role]:f}));}}/></label><label className="file-button">ถ่ายภาพ<input disabled={busy} type="file" accept="image/*" capture="environment" onChange={e=>{const f=e.target.files?.[0];if(f)setFiles(old=>({...old,[role]:f}));}}/></label></div><p>{files[role]?.name||'ยังไม่ได้เลือกภาพ'}</p>{files[role]&&<button onClick={()=>setFiles(old=>{const n={...old};delete n[role];return n;})}>นำภาพออก</button>}</div>)}</div><button className="primary" disabled={busy||!files.A} onClick={()=>perform(readSheet)}>อ่านใบเฉลย</button></>}
      {(draft?.result||editId)&&<><p>ตรวจคำตอบทุกข้อและแก้ไขข้อที่ต้องการ ก่อนกดยืนยันทั้งชุด · ยังไม่มีคำตอบ {remaining} ข้อ</p>{draft?.result?.pair_check?.blocked&&<p className="error">ภาพ A และ B ขัดแย้งกันมาก ระบบไม่นำภาพ B มาใช้ กรุณาตรวจภาพ</p>}{Object.entries(draft?.result?.errors || {}).map(([role,error])=><p className="error" key={role}>ภาพ {role}: {String(error)}</p>)}<div className="review-layout"><div className="question-grid" aria-label="เลือกข้อเฉลย">{answers.map((a,i)=><button key={i} aria-current={question===i+1?'true':undefined} className={draft?.result?.methods?.cnn?.[i]?.needs_review||!a?'risk':''} onClick={()=>setQuestion(i+1)}>{i+1}<small>{a||'ตรวจ'}</small></button>)}</div><div className="question"><h3>ข้อ {question}</h3>{row?.needs_review&&<p className="notice">ระบบแจ้งให้ตรวจข้อนี้</p>}{draft?.result&&Object.keys(draft.result.assets||{}).map(role=><figure key={role}><figcaption>รอยฝนภาพ {role}</figcaption><div className="strip"><img src={`/api/jobs/${draft.id}/image?role=${role}&view=rows`} alt={`รอยฝนข้อ ${question} ภาพ ${role}`} style={{top:`-${(question-1)*100}%`}}/></div></figure>)}<div className="answer-choices">{['1','2','3','4','5'].map(v=><button key={v} aria-pressed={answers[question-1]===v} onClick={()=>setAnswers(old=>old.map((a,i)=>i===question-1?v:a))}>{v}</button>)}</div><div className="actions"><button disabled={question===1} onClick={()=>setQuestion(question-1)}>ข้อก่อนหน้า</button><button disabled={question===100} onClick={()=>setQuestion(question+1)}>ข้อถัดไป</button></div></div></div><button className="primary" disabled={busy||remaining>0||!name.trim()} onClick={()=>perform(save)}>ยืนยันและบันทึกเฉลยทั้งชุด</button></>}
    </div>}
    <div className="workspace"><label htmlFor="saved-key">เลือกเฉลยที่บันทึกไว้</label><select id="saved-key" value={selected} onChange={e=>select(e.target.value)}><option value="">เลือกชุดเฉลย</option>{keys.map(k=><option key={k.id} value={k.id}>{k.name} · ฉบับ {k.version} · {new Date(k.created_at).toLocaleDateString('th-TH')}</option>)}</select>
      {selected&&<div className="actions"><button disabled={busy} onClick={()=>{const k=keys.find(x=>x.id===selected);if(!k)return;setName(k.name);setAnswers([...k.answers]);setQuestion(1);setDraft(null);setEditId(k.id);setExpanded(true);}}>แก้เป็นฉบับใหม่</button><button disabled={busy} onClick={()=>{if(window.confirm('ลบเฉลยนี้? งานที่ใช้ไปแล้วจะเก็บผลเดิม'))perform(async()=>{await api('exam-keys/'+selected,undefined,'DELETE');setSelected('');await refresh();});}}>ลบเฉลย</button></div>}
      <div className="score-settings"><label>คะแนนเต็ม <input type="number" min="0.001" step="any" value={full} onChange={e=>setFull(e.target.value)}/></label><label>คะแนนต่อข้อถูก <input type="number" min="0.00001" step="any" value={full===''?'':String(Number(full)/100)} onChange={e=>setFull(e.target.value===''?'':String(Number(e.target.value)*100))}/></label><label>หักต่อข้อผิด <input type="number" min="0" step="any" value={penalty} onChange={e=>setPenalty(e.target.value)}/></label></div>
      <p className="muted">ข้อเว้นว่างได้ 0 · ฝนหลายช่องที่ตรวจแล้วนับเป็นข้อผิด</p>{!job&&<p className="muted">เปิดงานกระดาษคำตอบก่อนเพื่อใช้เฉลยและดูคะแนน</p>}<button className="primary" disabled={busy||!selected||!job} onClick={()=>perform(apply)}>ใช้เฉลยและคำนวณคะแนน</button></div>
    {score&&<section className="score"><h2>{score.ready?'คะแนนพร้อมใช้':'คะแนนเบื้องต้น'}</h2><p className="score-value">{fmt(score.min)}{score.unresolved?` – ${fmt(score.max)}`:''} <span>/ {fmt(score.full)}</span></p>{!score.unresolved&&score.raw<0&&<p className="muted">คะแนนจริงก่อนปรับขั้นต่ำ: {fmt(score.raw)}</p>}{score.unresolved>0&&score.rawMin<0&&<p className="muted">คะแนนต่ำสุดก่อนปรับขั้นต่ำ: {fmt(score.rawMin)}</p>}<p>ถูก {score.correct} · ผิด {score.incorrect} · เว้นว่าง {score.blank} · รอตรวจ {score.unresolved} ข้อ</p><p>{score.ready?'ตรวจข้อที่ระบบแจ้งเตือนแล้ว คำตอบบางข้ออาจยังไม่ได้ตรวจโดยคน':'ตรวจข้อที่ระบบแจ้งเตือนเพื่อสรุปคะแนน'}</p><a className="button" href={`/api/jobs/${job.id}/export`}>ดาวน์โหลดผล CSV</a></section>}
  </section>;
}

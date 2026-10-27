import { randomBytes, createHmac } from 'node:crypto';
import { head, get, del } from '@vercel/blob';
import { getVercelOidcToken } from '@vercel/oidc';
import { pool, transaction, AppError, requireId } from './db';
import { ANSWERS, score } from './scoring.mjs';
export const id = () => randomBytes(16).toString('hex');
export async function job(jobId: string) {
  requireId(jobId);
  const {rows:[row]} = await pool().query('SELECT *,images_expires_at<=now() AS images_expired FROM omr_jobs WHERE id=$1', [jobId]);
  if (!row || row.deleted_at) throw new AppError(404, 'ไม่พบงานนี้');
  if (row.status === 'processing') {
    const {rowCount} = await pool().query('SELECT singleton FROM omr_engine_slot WHERE job_id=$1 AND expires_at>now()', [jobId]);
    if (!rowCount) {
      await pool().query("UPDATE omr_jobs SET status='interrupted', error_code='interrupted',error_message='งานหยุดกลางทาง กรุณาลองอ่านใหม่' WHERE id=$1 AND status='processing' AND attempt_id=$2", [jobId, row.attempt_id]);
      row.status = 'interrupted';
    }
  }
  return {...row, scores:score(row.result, row.reviews, row.grading?.key || [])};
}
export async function reserveUpload(jobId: string, data: {role:string;size:number;type:string;ext:string}) {
  requireId(jobId);
  const {role,size,type,ext} = data;
  if (!['A','B'].includes(role) || !Number.isInteger(size) || size < 1 || size > 20*1024*1024
    || !['image/jpeg','image/png','image/heic','image/heif'].includes(type)
    || !['jpg','jpeg','png','heic','heif'].includes(ext)) throw new AppError(422, 'เลือก JPEG, PNG หรือ HEIC ขนาดไม่เกิน 20 MiB');
  const pathname = `jobs/${jobId}/sources/${id()}.${ext}`;
  await transaction(async db => {
    // All storage mutations lock usage before job to avoid an inversion.
    const {rows:[usage]} = await db.query('SELECT * FROM omr_storage_usage WHERE singleton FOR UPDATE');
    const {rows:[row]} = await db.query('SELECT *,images_expires_at<=now() AS expired FROM omr_jobs WHERE id=$1 FOR UPDATE', [jobId]);
    if (!row || row.deleted_at || !['draft','ready','failed','interrupted'].includes(row.status)) throw new AppError(409, 'งานนี้เริ่มอ่านแล้ว กรุณาสร้างงานใหม่เพื่อเปลี่ยนภาพ');
    if (row.expired) throw new AppError(410, 'ภาพหมดอายุแล้ว กรุณาสร้างงานใหม่');
    if (Number(usage.used_bytes)+size > Number(usage.cap_bytes)) throw new AppError(409, 'พื้นที่โควตาฟรีถึง 80% แล้ว กรุณาสำรองและลบงานเก่าก่อนอัปโหลด');
    await db.query("INSERT INTO omr_blobs(pathname,job_id,bytes,status,kind,expires_at) VALUES($1,$2,$3,'reserved','source',$4)", [pathname,jobId,size,row.images_expires_at]);
    await db.query('UPDATE omr_storage_usage SET used_bytes=used_bytes+$1 WHERE singleton', [size]);
    await db.query("UPDATE omr_jobs SET status='draft',sources=jsonb_set(sources,ARRAY[$2],to_jsonb($3::text)),revision=revision+1 WHERE id=$1", [jobId,role,pathname]);
  });
  return {pathname};
}
export async function uploadGrant(pathname: string) {
  if (!/^jobs\/[a-f0-9]{32}\/sources\/[a-f0-9]{32}\.(jpg|jpeg|png|heic|heif)$/.test(pathname)) throw new AppError(403, 'ไฟล์นี้ไม่ได้รับสิทธิ์อัปโหลด');
  const {rows:[row]} = await pool().query("SELECT b.bytes,b.job_id FROM omr_blobs b JOIN omr_jobs j ON j.id=b.job_id WHERE b.pathname=$1 AND b.status='reserved' AND b.kind='source' AND b.expires_at>now() AND j.status='draft' AND j.sources ?| ARRAY['A','B'] AND (j.sources->>'A'=$1 OR j.sources->>'B'=$1)", [pathname]);
  if (!row) throw new AppError(403, 'สิทธิ์อัปโหลดหมดอายุ กรุณาเลือกภาพอีกครั้ง');
  return {jobId:row.job_id, bytes:Number(row.bytes)};
}
export async function completeUpload(jobId: string, pathname: string) {
  requireId(jobId);
  await job(jobId);
  const {rows:[allowed]} = await pool().query("SELECT * FROM omr_blobs WHERE pathname=$1 AND job_id=$2 AND kind='source' AND expires_at>now()", [pathname,jobId]);
  if (!allowed) throw new AppError(403, 'ไฟล์นี้ไม่ใช่ของงานนี้ หรือภาพหมดอายุแล้ว');
  const metadata = await head(pathname);
  if (metadata.pathname !== pathname || metadata.size > Number(allowed.bytes)) throw new AppError(422, 'ขนาดภาพไม่ตรงกับสิทธิ์ที่ได้รับ');
  await transaction(async db => {
    await db.query('SELECT singleton FROM omr_storage_usage WHERE singleton FOR UPDATE');
    const {rows:[row]} = await db.query('SELECT * FROM omr_blobs WHERE pathname=$1 AND expires_at>now() FOR UPDATE', [pathname]);
    if (!row || row.status === 'deleting') throw new AppError(410, 'ภาพหมดอายุแล้ว');
    if (row.status === 'reserved') {
      await db.query('UPDATE omr_storage_usage SET used_bytes=used_bytes-$1 WHERE singleton', [Number(row.bytes)-metadata.size]);
      await db.query("UPDATE omr_blobs SET status='live',bytes=$2 WHERE pathname=$1", [pathname,metadata.size]);
    }
    await db.query("UPDATE omr_jobs j SET status='ready' WHERE id=$1 AND status='draft' AND sources ? 'A' AND NOT EXISTS (SELECT 1 FROM jsonb_each_text(j.sources) s LEFT JOIN omr_blobs b ON b.pathname=s.value AND b.job_id=j.id AND b.status='live' WHERE b.pathname IS NULL)", [jobId]);
  });
}
export async function read(jobId: string) {
  const current = await job(jobId);
  if (current.images_expired) throw new AppError(410, 'ภาพครบอายุ 7 วัน กรุณาเริ่มงานใหม่');
  if (current.status === 'complete') return current;
  const origin = process.env.OMR_ENGINE_URL, secret = process.env.OMR_SIGNING_SECRET;
  if (!origin || !secret) throw new AppError(503, 'ระบบอ่านภาพยังไม่ได้ตั้งค่า');
  const url = new URL(origin);
  if (url.protocol !== 'https:' || !url.hostname.endsWith('.vercel.app') || url.pathname !== '/') throw new AppError(503, 'ปลายทางระบบอ่านภาพไม่ถูกต้อง');
  const body = JSON.stringify({job_id:jobId,attempt_id:id()}), timestamp = String(Math.floor(Date.now()/1000));
  const headers: Record<string,string> = {'Content-Type':'application/json','x-omr-timestamp':timestamp,
    'x-omr-signature': createHmac('sha256',secret).update(timestamp+'.'+body).digest('hex')};
  // Engine Preview remains protected. Use scoped Trusted Sources for this web project.
  const oidc = await getVercelOidcToken();
  if (oidc) headers['x-vercel-trusted-oidc-idp-token'] = oidc;
  const response = await fetch(new URL('/infer',url), {method:'POST',headers,body,signal:AbortSignal.timeout(185000),cache:'no-store',redirect:'error'});
  const content = response.headers.get('content-type') || '';
  if (!content.includes('application/json')) throw new AppError(503, 'ระบบอ่านภาพยังไม่อนุญาตการเชื่อมต่อจากเว็บนี้');
  const result = await response.json();
  if (!response.ok) throw new AppError(response.status,result.error?.message || 'อ่านภาพไม่สำเร็จ กรุณาลองใหม่');
  return job(jobId);
}
export async function review(jobId: string, data: {revision:number;method:string;question:number;answer:string}) {
  requireId(jobId);
  if (!Number.isInteger(data.revision) || !['cnn','cla'].includes(data.method) || !Number.isInteger(data.question)
    || data.question<1 || data.question>100 || !ANSWERS.includes(data.answer)) throw new AppError(422, 'คำตอบไม่ถูกต้อง');
  const {rowCount} = await pool().query("UPDATE omr_jobs SET reviews=jsonb_set(reviews,ARRAY[$2,$3],$4::jsonb),revision=revision+1 WHERE id=$1 AND revision=$5 AND status='complete' AND images_expires_at>now()", [jobId,data.method,String(data.question),JSON.stringify({answer:data.answer,confirmed_at:new Date().toISOString()}),data.revision]);
  if (!rowCount) throw new AppError(409, 'งานเปลี่ยนจากอีกแท็บ หรือภาพหมดอายุ กรุณาโหลดงานล่าสุดก่อนยืนยัน');
  return job(jobId);
}
export async function saveKey(jobId: string, data: {revision:number;key:unknown[]}) {
  requireId(jobId);
  if (!Number.isInteger(data.revision) || !Array.isArray(data.key) || data.key.length!==100 || data.key.some(x=>x!==null && !/^[1-5]$/.test(String(x)))) throw new AppError(422, 'เฉลยต้องเป็น 1–5 จำนวน 100 ข้อ ช่องที่ยังไม่มีให้เว้นว่าง');
  const {rowCount} = await pool().query("UPDATE omr_jobs SET grading=$3::jsonb,revision=revision+1 WHERE id=$1 AND revision=$2 AND status='complete'", [jobId,data.revision,JSON.stringify({key:data.key.map(x=>x===null?null:String(x))})]);
  if (!rowCount) throw new AppError(409, 'งานเปลี่ยนจากอีกแท็บ กรุณาโหลดงานล่าสุด');
  return job(jobId);
}
export async function image(jobId: string, role: string, view: string) {
  if (!['A','B'].includes(role) || !['input','registered','rows'].includes(view)) throw new AppError(404, 'ไม่พบภาพนี้');
  const current = await job(jobId);
  if (current.images_expired) throw new AppError(410, 'ภาพหมดอายุแล้ว ยังดูคำตอบและส่งออกผลได้');
  const pathname = current.result?.assets?.[role]?.[view];
  if (!pathname) throw new AppError(404, 'ไม่มีภาพนี้');
  const {rowCount} = await pool().query("SELECT pathname FROM omr_blobs WHERE pathname=$1 AND job_id=$2 AND status='live' AND expires_at>now()", [pathname,jobId]);
  if (!rowCount) throw new AppError(410, 'ภาพหมดอายุแล้ว');
  const blob = await get(pathname,{access:'private'});
  if (!blob || blob.statusCode!==200) throw new AppError(404, 'ไม่พบภาพนี้');
  return new Response(blob.stream, {headers:{'Content-Type':'image/jpeg','Cache-Control':'private, no-store'}});
}
async function cleanupBatch() {
  const {rows} = await pool().query("SELECT pathname FROM omr_blobs WHERE kind IN ('source','derived') AND expires_at<=now() ORDER BY expires_at LIMIT 100");
  if (!rows.length) return {deleted:0};
  const keys = rows.map(r=>r.pathname);
  await pool().query("UPDATE omr_blobs SET status='deleting' WHERE pathname=ANY($1) AND kind<>'model' AND expires_at<=now()", [keys]);
  await del(keys);
  const deleted = await transaction(async db => {
    await db.query('SELECT singleton FROM omr_storage_usage WHERE singleton FOR UPDATE');
    const {rows} = await db.query("DELETE FROM omr_blobs WHERE pathname=ANY($1) AND kind<>'model' AND expires_at<=now() RETURNING bytes", [keys]);
    await db.query('UPDATE omr_storage_usage SET used_bytes=GREATEST(0,used_bytes-$1) WHERE singleton', [rows.reduce((n,r)=>n+Number(r.bytes),0)]);
    await db.query('DELETE FROM omr_sessions WHERE expires_at<=now()');
    await db.query("DELETE FROM omr_login_attempts WHERE window_start<now()-interval '1 day'");
    return rows.length;
  });
  return {deleted};
}
export async function cleanup() {
  const deadline=Date.now()+150000;
  let deleted=0;
  do {
    const batch=await cleanupBatch();deleted+=batch.deleted;
    if(!batch.deleted)return {deleted,more:false};
  }while(Date.now()<deadline);
  return {deleted,more:true};
}
export async function deleteJob(jobId:string) {
  requireId(jobId);
  await transaction(async db=>{
    const {rows:[slot]}=await db.query('SELECT *,expires_at>now() AS active FROM omr_engine_slot WHERE singleton FOR UPDATE');
    if(slot.job_id===jobId&&slot.active)throw new AppError(409,'งานนี้กำลังอ่านอยู่ กรุณารอให้เสร็จก่อนลบ');
    await db.query('SELECT singleton FROM omr_storage_usage WHERE singleton FOR UPDATE');
    const {rows:[current]}=await db.query('SELECT id FROM omr_jobs WHERE id=$1 AND deleted_at IS NULL FOR UPDATE',[jobId]);
    if(!current)throw new AppError(404,'ไม่พบงานนี้');
    await db.query("UPDATE omr_jobs SET deleted_at=now(),images_expires_at=now(),status='draft',sources='{}',result=NULL,reviews='{\"cnn\":{},\"cla\":{}}',grading=NULL,error_code=NULL,error_message=NULL,revision=revision+1 WHERE id=$1",[jobId]);
    await db.query('UPDATE omr_engine_slot SET job_id=NULL,attempt_id=NULL,expires_at=NULL WHERE singleton AND job_id=$1',[jobId]);
    // Keep image ledger until its original retention deadline. Outstanding short
    // upload grants cannot leave untracked files after an immediate ledger delete.
  });
}

import {pool,transaction,AppError,requireId} from './db';
import {id} from './jobs';
import {getKey,validateRules} from './exam-keys';
import {riskScore} from './scoring.mjs';

type Owner=string|null;
function revision(value:unknown){if(!Number.isInteger(value)||Number(value)<0)throw new AppError(422,'ข้อมูลงานไม่ถูกต้อง');return value;}
function label(value:unknown,max=120){if(typeof value!=='string'||value.trim().length>max)throw new AppError(422,'ชื่อยาวเกินไปหรือไม่ถูกต้อง');return value.trim();}
async function lockSession(db:any, sessionId:string,owner:Owner, rev:unknown){
  const {rows}=await db.query('SELECT * FROM omr_exam_sessions WHERE id=$1 AND demo_owner_hash IS NOT DISTINCT FROM $2 AND deleted_at IS NULL FOR UPDATE',[requireId(sessionId),owner]);
  if(!rows.length)throw new AppError(404,'ไม่พบชุดตรวจ');
  if(rows[0].revision!==revision(rev))throw new AppError(409,'ชุดตรวจเปลี่ยนจากอีกแท็บ กรุณาโหลดข้อมูลใหม่');
  return rows[0];
}
async function snapshot(data:any,owner:Owner){const k=await getKey(data.keyId,owner);return {key:k.answers,keyId:k.id,name:k.name,version:k.version,rules:validateRules(data.rules||k.rules),policy:'risk-reviewed-v1'};}
export async function list(owner:Owner){const {rows}=await pool().query(`SELECT s.id,s.name,s.revision,s.created_at,s.grading,count(i.id)::int AS sheet_count FROM omr_exam_sessions s LEFT JOIN omr_session_sheets i ON i.session_id=s.id WHERE s.demo_owner_hash IS NOT DISTINCT FROM $1 AND s.deleted_at IS NULL GROUP BY s.id ORDER BY s.created_at DESC`,[owner]);return rows;}
export async function get(sessionId:string,owner:Owner){
  return transaction(async db=>{
  const {rows:[session]}=await db.query('SELECT * FROM omr_exam_sessions WHERE id=$1 AND demo_owner_hash IS NOT DISTINCT FROM $2 AND deleted_at IS NULL FOR SHARE',[requireId(sessionId),owner]);
  if(!session)throw new AppError(404,'ไม่พบชุดตรวจ');
  const {rows}=await db.query(`SELECT i.id,i.ordinal,i.student_label,i.current_job_id,CASE WHEN j.status='processing' AND NOT EXISTS (SELECT 1 FROM omr_engine_slot slot WHERE slot.job_id=j.id AND slot.expires_at>now()) THEN 'interrupted' ELSE j.status END AS status,j.result,j.reviews,j.grading,j.revision AS job_revision,j.images_expires_at,j.images_expires_at<=now() AS images_expired,j.error_message FROM omr_session_sheets i JOIN omr_jobs j ON j.id=i.current_job_id WHERE i.session_id=$1 ORDER BY i.ordinal`,[sessionId]);
  return {...session,sheets:rows.map(r=>({id:r.id,ordinal:r.ordinal,student_label:r.student_label,current_job_id:r.current_job_id,status:r.status,job_revision:r.job_revision,images_expires_at:r.images_expires_at,images_expired:r.images_expired,error_message:r.error_message,pair_check:r.result?.pair_check||null,reading_errors:r.result?.errors||{},score:r.result?riskScore(r.result,r.reviews,r.grading).cnn:null}))};
  });
}
export async function create(data:any,owner:Owner){const name=label(data.name);if(!name)throw new AppError(422,'กรุณาตั้งชื่อชุดตรวจ');const grading=await snapshot(data,owner),sessionId=id();await transaction(async db=>{await db.query('INSERT INTO omr_exam_sessions(id,name,demo_owner_hash,grading) VALUES($1,$2,$3,$4::jsonb)',[sessionId,name,owner,JSON.stringify(grading)]);await db.query('INSERT INTO omr_session_grading_history(session_id,revision,grading) VALUES($1,0,$2::jsonb)',[sessionId,JSON.stringify(grading)]);});return get(sessionId,owner);}
export async function newSheet(sessionId:string,data:any,owner:Owner,isTest:boolean){
  await transaction(async db=>{const session=await lockSession(db,sessionId,owner,data.revision);const sheetId=id(),jobId=id(),student=label(data.studentLabel||'');
    const {rows:[next]}=await db.query('SELECT coalesce(max(ordinal),0)+1 AS ordinal FROM omr_session_sheets WHERE session_id=$1',[sessionId]);
    await db.query('INSERT INTO omr_jobs(id,demo_owner_hash,is_test,grading) VALUES($1,$2,$3,$4::jsonb)',[jobId,owner,isTest,JSON.stringify(session.grading)]);
    await db.query('INSERT INTO omr_session_sheets(id,session_id,ordinal,student_label,current_job_id) VALUES($1,$2,$3,$4,$5)',[sheetId,sessionId,next.ordinal,student,jobId]);
    await db.query('UPDATE omr_jobs SET session_sheet_id=$2 WHERE id=$1',[jobId,sheetId]);
    await db.query('UPDATE omr_exam_sessions SET revision=revision+1 WHERE id=$1',[sessionId]);
  });return get(sessionId,owner);
}
export async function updateLabel(sessionId:string,sheetId:string,data:any,owner:Owner){await transaction(async db=>{await lockSession(db,sessionId,owner,data.revision);const result=await db.query('UPDATE omr_session_sheets SET student_label=$3 WHERE id=$1 AND session_id=$2',[requireId(sheetId),sessionId,label(data.studentLabel)]);if(!result.rowCount)throw new AppError(404,'ไม่พบกระดาษ');await db.query('UPDATE omr_exam_sessions SET revision=revision+1 WHERE id=$1',[sessionId]);});return get(sessionId,owner);}
export async function replacement(sessionId:string,sheetId:string,data:any,owner:Owner,isTest:boolean){await transaction(async db=>{const session=await lockSession(db,sessionId,owner,data.revision);const {rows:[sheet]}=await db.query('SELECT i.*,j.images_expires_at<=now() AS expired FROM omr_session_sheets i JOIN omr_jobs j ON j.id=i.current_job_id WHERE i.id=$1 AND i.session_id=$2 FOR UPDATE OF i',[requireId(sheetId),sessionId]);if(!sheet)throw new AppError(404,'ไม่พบกระดาษ');if(!sheet.expired)throw new AppError(409,'ภาพเดิมยังไม่หมดอายุ');const jobId=id();await db.query('INSERT INTO omr_jobs(id,demo_owner_hash,is_test,grading,session_sheet_id) VALUES($1,$2,$3,$4::jsonb,$5)',[jobId,owner,isTest,JSON.stringify(session.grading),sheetId]);await db.query('UPDATE omr_session_sheets SET current_job_id=$2 WHERE id=$1',[sheetId,jobId]);await db.query('UPDATE omr_exam_sessions SET revision=revision+1 WHERE id=$1',[sessionId]);});return get(sessionId,owner);}
export async function changeGrading(sessionId:string,data:any,owner:Owner){const grading=await snapshot(data,owner);await transaction(async db=>{const session=await lockSession(db,sessionId,owner,data.revision);const next=session.revision+1;await db.query('UPDATE omr_exam_sessions SET grading=$2::jsonb,revision=$3 WHERE id=$1',[sessionId,JSON.stringify(grading),next]);await db.query('INSERT INTO omr_session_grading_history(session_id,revision,grading) VALUES($1,$2,$3::jsonb)',[sessionId,next,JSON.stringify(grading)]);await db.query('UPDATE omr_jobs SET grading=$2::jsonb,revision=revision+1 WHERE id IN (SELECT current_job_id FROM omr_session_sheets WHERE session_id=$1)',[sessionId,JSON.stringify(grading)]);});return get(sessionId,owner);}
export async function remove(sessionId:string,data:any,owner:Owner){await transaction(async db=>{
  await lockSession(db,sessionId,owner,data.revision);
  const {rows:[slot]}=await db.query('SELECT *,expires_at>now() AS active FROM omr_engine_slot WHERE singleton FOR UPDATE');
  if(slot.active && slot.job_id){const found=await db.query('SELECT j.id FROM omr_jobs j JOIN omr_session_sheets i ON i.id=j.session_sheet_id WHERE i.session_id=$1 AND j.id=$2',[sessionId,slot.job_id]);if(found.rowCount)throw new AppError(409,'มีงานกำลังอ่านอยู่ กรุณารอให้เสร็จก่อนลบ');}
  await db.query('SELECT singleton FROM omr_storage_usage WHERE singleton FOR UPDATE');
  await db.query(`UPDATE omr_jobs SET deleted_at=now(),images_expires_at=now(),status='draft',sources='{}',result=NULL,reviews='{"cnn":{},"cla":{}}',grading=NULL,error_code=NULL,error_message=NULL,revision=revision+1 WHERE session_sheet_id IN (SELECT id FROM omr_session_sheets WHERE session_id=$1)`,[sessionId]);
  await db.query("UPDATE omr_session_sheets SET student_label='' WHERE session_id=$1",[sessionId]);
  await db.query('DELETE FROM omr_session_grading_history WHERE session_id=$1',[sessionId]);
  await db.query("UPDATE omr_exam_sessions SET name='',grading='{}'::jsonb,deleted_at=now(),revision=revision+1 WHERE id=$1",[sessionId]);
});}
export async function exportSummary(sessionId:string,owner:Owner){const session=await get(sessionId,owner);const safe=(x:any)=>{let s=String(x??'');if(/^[\t\r\n ]*[=+@-]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';};const lines=[['ordinal','student','status','score_min','score_max','score_full','unresolved','key_name']];for(const row of session.sheets)lines.push([row.ordinal,row.student_label,row.score?(row.score.ready?'ready':'provisional'):row.status,row.score?.min??'',row.score?.max??'',row.score?.full??'',row.score?.unresolved??'',session.grading.name]);return '\ufeff'+lines.map(r=>r.map(safe).join(',')).join('\r\n');}

import { pool, AppError, requireId } from './db';
import { id } from './jobs';

const validKey = (key: unknown) => Array.isArray(key) && key.length === 100 && key.every(x => typeof x === 'string' && /^[1-5]$/.test(x));
export function validateRules(r: any) {
  if (!r || typeof r.full !== 'number' || !Number.isFinite(r.full) || r.full <= 0 || r.full > 1000000 || typeof r.penalty !== 'number' || !Number.isFinite(r.penalty) || r.penalty < 0 || r.penalty > 1000000) throw new AppError(422, 'กรอกคะแนนเต็มมากกว่า 0 และคะแนนหักตั้งแต่ 0 ขึ้นไป');
  return {full:r.full, penalty:r.penalty};
}
export async function listKeys(owner: string | null) {
  const {rows}=await pool().query('SELECT id,name,answers,rules,created_at,parent_id,version FROM omr_exam_keys WHERE deleted_at IS NULL AND demo_owner_hash IS NOT DISTINCT FROM $1 ORDER BY created_at DESC', [owner]);
  return rows;
}
export async function createKey(data: any, owner: string | null) {
  const name=typeof data.name==='string'?data.name.trim():'';
  if (!name || name.length>120 || !validKey(data.answers)) throw new AppError(422,'ใส่ชื่อเฉลยและคำตอบ 1–5 ให้ครบ 100 ข้อ');
  const rules=validateRules(data.rules), keyId=id();
  const parent=data.parentId ? await getKey(data.parentId,owner) : null;
  const {rows}=await pool().query('INSERT INTO omr_exam_keys(id,name,answers,rules,demo_owner_hash,parent_id,version) VALUES($1,$2,$3::jsonb,$4::jsonb,$5,$6,$7) RETURNING id,name,answers,rules,created_at,parent_id,version',[keyId,name,JSON.stringify(data.answers),JSON.stringify(rules),owner,parent?.id || null,parent ? parent.version+1 : 1]);
  return rows[0];
}
export async function getKey(keyId: string, owner: string | null) {
  const {rows}=await pool().query('SELECT id,name,answers,rules,created_at,parent_id,version FROM omr_exam_keys WHERE id=$1 AND deleted_at IS NULL AND demo_owner_hash IS NOT DISTINCT FROM $2',[requireId(keyId),owner]);
  if (!rows.length) throw new AppError(404,'ไม่พบเฉลย');
  return rows[0];
}
export async function deleteKey(keyId: string, owner: string | null) {
  const {rowCount}=await pool().query('UPDATE omr_exam_keys SET deleted_at=now() WHERE id=$1 AND deleted_at IS NULL AND demo_owner_hash IS NOT DISTINCT FROM $2',[requireId(keyId),owner]);
  if (!rowCount) throw new AppError(404,'ไม่พบเฉลย');
}
export async function applyKey(jobId: string, data: any, owner: string | null) {
  const key=await getKey(data.keyId,owner), rules=validateRules(data.rules || key.rules);
  if (!Number.isInteger(data.revision)) throw new AppError(422,'ข้อมูลรุ่นงานไม่ถูกต้อง');
  const snapshot={key:key.answers, keyId:key.id, name:key.name, version:key.version, rules, policy:'risk-reviewed-v1'};
  const {rowCount}=await pool().query("UPDATE omr_jobs SET grading=$3::jsonb,revision=revision+1 WHERE id=$1 AND revision=$2 AND status='complete'",[requireId(jobId),data.revision,JSON.stringify(snapshot)]);
  if (!rowCount) throw new AppError(409,'งานเปลี่ยนจากอีกแท็บ กรุณาโหลดงานล่าสุด');
  const {job}=await import('./jobs'); return job(jobId);
}

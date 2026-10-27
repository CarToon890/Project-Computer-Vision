import { createHash, createHmac, randomBytes } from 'node:crypto';
import { cookies } from 'next/headers';
import { pool, transaction, AppError } from './db';
import { verifyPassword } from './password.mjs';
const COOKIE = '__Host-omr-session';
const LOCAL_COOKIE = 'omr-session-local';
const secure = process.env.NODE_ENV === 'production';
const cookieName = () => secure ? COOKIE : LOCAL_COOKIE;
const digest = (value: string) => createHash('sha256').update(value).digest('hex');
export function sameOrigin(request: Request) {
  // Next's internal dev URL can be localhost even when the browser uses
  // 127.0.0.1. Host is the browser-facing authority; browsers cannot forge it.
  let valid=false;
  try {
    const origin=new URL(request.headers.get('origin') || '');
    valid=origin.host===request.headers.get('host') && origin.protocol===(process.env.VERCEL?'https:':new URL(request.url).protocol);
  } catch {}
  if (!valid) throw new AppError(403, 'กรุณาเปิดเว็บใหม่แล้วลองอีกครั้ง');
}
export async function owner() {
  if (!process.env.OMR_OWNER_PASSWORD_HASH) throw new AppError(503, 'เจ้าของเว็บต้องตั้งรหัสผ่านส่วนตัวก่อนใช้งาน');
  const token = (await cookies()).get(cookieName())?.value;
  if (!token || !/^[a-f0-9]{64}$/.test(token)) throw new AppError(401, 'กรุณาเข้าสู่ระบบอีกครั้ง');
  const result = await pool().query('SELECT token_hash FROM omr_sessions WHERE token_hash=$1 AND expires_at>now() AND password_version=$2',
    [digest(token), digest(process.env.OMR_OWNER_PASSWORD_HASH)]);
  if (!result.rowCount) throw new AppError(401, 'เซสชันหมดอายุ กรุณาเข้าสู่ระบบอีกครั้ง');
}
export async function login(request: Request, password: unknown) {
  sameOrigin(request);
  const stored = process.env.OMR_OWNER_PASSWORD_HASH, secret = process.env.OMR_AUTH_SECRET;
  if (!stored || !secret) throw new AppError(503, 'เจ้าของเว็บต้องตั้งรหัสผ่านส่วนตัวก่อนใช้งาน');
  // Vercel supplies this header. Ignore spoofable forwarded IP chains.
  const ip = process.env.VERCEL ? request.headers.get('x-vercel-forwarded-for') || 'unknown' : 'local';
  const key = createHmac('sha256', secret).update(ip).digest('hex');
  const ok = await transaction(async db => {
    await db.query('INSERT INTO omr_login_attempts(ip_hash,window_start) VALUES($1,now()) ON CONFLICT DO NOTHING', [key]);
    const {rows:[attempt]} = await db.query('SELECT *, window_start > now()-interval \'15 minutes\' AS active FROM omr_login_attempts WHERE ip_hash=$1 FOR UPDATE', [key]);
    if (attempt.active && attempt.failures >= 5) throw new AppError(429, 'ลองรหัสผ่านหลายครั้งแล้ว กรุณารอ 15 นาที');
    if (!attempt.active) await db.query('UPDATE omr_login_attempts SET window_start=now(), failures=0 WHERE ip_hash=$1', [key]);
    const valid = typeof password === 'string' && verifyPassword(password, stored);
    await db.query('UPDATE omr_login_attempts SET failures=CASE WHEN $2 THEN 0 ELSE failures+1 END WHERE ip_hash=$1', [key, valid]);
    return valid;
  });
  if (!ok) throw new AppError(401, 'รหัสผ่านไม่ถูกต้อง');
  const token = randomBytes(32).toString('hex');
  await pool().query("INSERT INTO omr_sessions(token_hash,password_version,expires_at) VALUES($1,$2,now()+interval '12 hours')", [digest(token), digest(stored)]);
  (await cookies()).set(cookieName(), token, {secure, httpOnly:true, sameSite:'strict', path:'/', maxAge:43200});
}
export async function logout() {
  const jar = await cookies(), token = jar.get(cookieName())?.value;
  if (token) await pool().query('DELETE FROM omr_sessions WHERE token_hash=$1', [digest(token)]);
  jar.delete(cookieName());
}

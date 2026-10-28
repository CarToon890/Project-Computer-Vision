import { timingSafeEqual } from 'node:crypto';
import { handleUpload, type HandleUploadBody } from '@vercel/blob/client';
import { AppError, pool, requireId } from '../../../lib/db';
import { owner, login, logout, sameOrigin, temporaryPreviewAccess, isDemo, demoOwner } from '../../../lib/auth';
import * as jobs from '../../../lib/jobs';
import * as examKeys from '../../../lib/exam-keys';
import * as sessions from '../../../lib/exam-sessions';
import { exportCsv } from '../../../lib/scoring.mjs';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 200;

async function json(request: Request, limit=32768) {
  const reader = request.body?.getReader();
  if (!reader) throw new AppError(422,'ไม่มีข้อมูลคำขอ');
  let size=0; const chunks:Uint8Array[]=[];
  for (;;) { const {value,done}=await reader.read(); if(done)break; size+=value.length;
    if(size>limit) { await reader.cancel(); throw new AppError(413,'คำขอใหญ่เกินไป'); } chunks.push(value); }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
  catch { throw new AppError(422,'ข้อมูลคำขอไม่ถูกต้อง'); }
}
function response(value: unknown,status=200) { return Response.json(value,{status,headers:{'Cache-Control':'no-store'}}); }
async function dispatch(request: Request, context: {params:Promise<{path:string[]}>}) {
  try {
    const path=(await context.params).path, method=request.method;
    async function demoJob(jobId:string) {
      if(!isDemo())return;
      const identity=await demoOwner();
      const result=await pool().query('SELECT id FROM omr_jobs WHERE id=$1 AND demo_owner_hash=$2 AND deleted_at IS NULL',[requireId(jobId),identity]);
      if(!result.rowCount)throw new AppError(404,'ไม่พบงานนี้');
    }
    if (path.join('/')==='cleanup' && method==='GET') {
      const expected='Bearer '+(process.env.CRON_SECRET || ''), actual=request.headers.get('authorization') || '';
      if(!process.env.CRON_SECRET || expected.length!==actual.length || !timingSafeEqual(Buffer.from(expected),Buffer.from(actual))) throw new AppError(401,'ไม่ได้รับอนุญาต');
      return response(await jobs.cleanup());
    }
    if(path.join('/')==='upload' && method==='POST') {
      const body=await json(request) as HandleUploadBody;
      const result=await handleUpload({body, request,
        onBeforeGenerateToken:async pathname=>{
          sameOrigin(request); await owner();
          const grant=await jobs.uploadGrant(pathname);
          await demoJob(grant.jobId);
          return {allowedContentTypes:['image/jpeg','image/png','image/heic','image/heif'],
            maximumSizeInBytes:grant.bytes, addRandomSuffix:false, allowOverwrite:false,
            validUntil:Date.now()+5*60*1000, tokenPayload:JSON.stringify({jobId:grant.jobId,pathname})};
        },
        onUploadCompleted:async ({blob,tokenPayload})=>{
          // SDK authenticates Blob callbacks; browser sessions are not forwarded.
          const payload=JSON.parse(tokenPayload || '{}');
          if(payload.pathname!==blob.pathname || !payload.jobId) throw new AppError(403,'ไฟล์ไม่ตรงกับสิทธิ์');
          await jobs.completeUpload(payload.jobId,blob.pathname);
        },
      });
      return response(result);
    }
    if(method!=='GET') sameOrigin(request);
    if(path.join('/')==='login' && method==='POST') {await login(request,(await json(request,2048)).password);return response({ok:true});}
    if(path.join('/')==='logout' && method==='POST') {await logout();return response({ok:true});}
    await owner();
    if(path.join('/')==='me' && method==='GET') {if(isDemo())await demoOwner(true);return response({ok:true,temporaryPreviewAccess:temporaryPreviewAccess()||isDemo(),demo:isDemo()});}
    if(path[0]==='sessions') {
      const identity=isDemo()?await demoOwner():null;
      if(path.length===1 && method==='GET') return response({sessions:await sessions.list(identity)});
      if(path.length===1 && method==='POST') return response(await sessions.create(await json(request),identity),201);
      if(path.length>=2) {
        const sid=requireId(path[1]);
        if(path.length===2 && method==='GET') return response(await sessions.get(sid,identity));
        if(path.length===2 && method==='DELETE') {await sessions.remove(sid,await json(request),identity);return response({ok:true});}
        if(path.length===3 && path[2]==='sheets' && method==='POST') return response(await sessions.newSheet(sid,await json(request),identity,isDemo()),201);
        if(path.length===3 && path[2]==='grading' && method==='POST') return response(await sessions.changeGrading(sid,await json(request),identity));
        if(path.length===3 && path[2]==='export' && method==='GET') return new Response(await sessions.exportSummary(sid,identity),{headers:{'Content-Type':'text/csv; charset=utf-8','Content-Disposition':`attachment; filename="omr-class-${sid}.csv"`,'Cache-Control':'no-store'}});
        if(path.length===5 && path[2]==='sheets' && path[4]==='label' && method==='POST') return response(await sessions.updateLabel(sid,path[3],await json(request),identity));
        if(path.length===5 && path[2]==='sheets' && path[4]==='replacement' && method==='POST') return response(await sessions.replacement(sid,path[3],await json(request),identity,isDemo()),201);
      }
    }
    if(path[0]==='exam-keys') {
      const identity=isDemo()?await demoOwner():null;
      if(path.length===1 && method==='GET') return response({keys:await examKeys.listKeys(identity)});
      if(path.length===1 && method==='POST') return response(await examKeys.createKey(await json(request),identity),201);
      if(path.length===2 && method==='DELETE') {await examKeys.deleteKey(path[1],identity);return response({ok:true});}
    }
    if(path[0]==='jobs' && path.length===1) {
      if(method==='GET') {
        const before=new URL(request.url).searchParams.get('before');if(before)requireId(before);
        const demoId=isDemo()?await demoOwner():null;
        const {rows}=await pool().query('SELECT id,status,created_at,images_expires_at,error_message,revision,is_test FROM omr_jobs WHERE deleted_at IS NULL AND ($2::text IS NULL OR demo_owner_hash=$2) AND ($1::text IS NULL OR (created_at,id)<(SELECT created_at,id FROM omr_jobs WHERE id=$1 AND ($2::text IS NULL OR demo_owner_hash=$2))) ORDER BY created_at DESC,id DESC LIMIT 101',[before,demoId]);
        return response({jobs:rows.slice(0,100),nextBefore:rows.length>100?rows[99].id:null});
      }
      if(method==='POST') {const jobId=jobs.id();await pool().query('INSERT INTO omr_jobs(id,demo_owner_hash,is_test) VALUES($1,$2,$3)',[jobId,isDemo()?await demoOwner():null,isDemo()]);return response(await jobs.job(jobId),201);}
    }
    if(path[0]==='jobs' && path[1]) {
      const jobId=requireId(path[1]);
      await demoJob(jobId);
      if(path.length===2 && method==='GET') return response(await jobs.job(jobId));
      if(path.length===2 && method==='DELETE') {await jobs.deleteJob(jobId);return response({ok:true});}
      if(path.length===3) {
        if(path[2]==='upload' && method==='POST') return response(await jobs.reserveUpload(jobId,await json(request)));
        if(path[2]==='upload-complete' && method==='POST') {await jobs.completeUpload(jobId,(await json(request)).pathname);return response(await jobs.job(jobId));}
        if(path[2]==='read' && method==='POST') return response(await jobs.read(jobId));
        if(path[2]==='review' && method==='POST') return response(await jobs.review(jobId,await json(request)));
        if(path[2]==='apply-key' && method==='POST') return response(await examKeys.applyKey(jobId,await json(request),isDemo()?await demoOwner():null));
        if(path[2]==='score' && method==='POST') return response(await jobs.saveKey(jobId,await json(request)));
        if(path[2]==='image' && method==='GET') {const search=new URL(request.url).searchParams;return await jobs.image(jobId,search.get('role')||'A',search.get('view')||'rows');}
        if(path[2]==='export' && method==='GET') return new Response(exportCsv(await jobs.job(jobId)),{headers:{'Content-Type':'text/csv; charset=utf-8','Content-Disposition':`attachment; filename="omr-${jobId}.csv"`,'Cache-Control':'no-store'}});
      }
    }
    throw new AppError(404,'ไม่พบหน้าหรือคำขอนี้');
  } catch(error) {
    if(error instanceof AppError) return response({error:error.message},error.status);
    console.error('OMR API failure:',error instanceof Error?error.name:'UnknownError');
    return response({error:'ระบบยังไม่พร้อม กรุณาลองใหม่ งานที่บันทึกแล้วจะยังอยู่ในประวัติ'},503);
  }
}
export {dispatch as GET,dispatch as POST,dispatch as DELETE};

import {upload} from '@vercel/blob/client';

type Api=(path:string,data:unknown)=>Promise<any>;
type Photo={role:'A'|'B';file:File};
/** Reserve both files before upload: a completed A must not make a partly uploaded B ready. */
export async function uploadPhotos(jobId:string,photos:Photo[],api:Api,onProgress:(message:string)=>void){
  if(!photos.some(p=>p.role==='A')||photos.length>2||new Set(photos.map(p=>p.role)).size!==photos.length)throw Error('เลือกภาพ A และภาพ B ได้อย่างละหนึ่งภาพ');
  const prepared=photos.map(({role,file})=>{
    const ext=file.name.split('.').pop()?.toLowerCase()||'jpg';
    const type=file.type||({jpg:'image/jpeg',jpeg:'image/jpeg',png:'image/png',heic:'image/heic',heif:'image/heif'} as Record<string,string>)[ext];
    if(file.size<1||file.size>20*1024*1024)throw Error('ภาพต้องมีขนาดไม่เกิน 20 MiB และไม่เป็นไฟล์ว่าง');
    if(!['jpg','jpeg','png','heic','heif'].includes(ext)||!['image/jpeg','image/png','image/heic','image/heif'].includes(type))throw Error('รองรับ JPEG, PNG หรือ HEIC');
    return {role,file,type,ext};
  });
  const entries=[];
  for(const {role,file,type,ext} of prepared){
    const grant=await api(`jobs/${jobId}/upload`,{role,size:file.size,type,ext});
    entries.push({role,file,type,pathname:grant.pathname});
  }
  // Wait for every upload to settle before reporting failure, so no background transfer
  // can race a retry or a user action after the operation is shown as finished.
  const results=await Promise.allSettled(entries.map(async ({role,file,type,pathname})=>{
    await upload(pathname,file,{access:'private',handleUploadUrl:'/api/upload',contentType:type,multipart:file.size>5*1024*1024,
      onUploadProgress:({percentage})=>onProgress(`กำลังอัปโหลดภาพ ${role} ${Math.round(percentage)}%`)});
    await api(`jobs/${jobId}/upload-complete`,{pathname});
  }));
  const error=results.find((result):result is PromiseRejectedResult=>result.status==='rejected');
  if(error)throw error.reason;
}

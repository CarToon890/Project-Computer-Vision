// Uses only a fresh demo cookie and explicitly selected test images. Jobs are marked deleted after reading.
import {upload} from '@vercel/blob/client';
import {readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {createHmac,randomBytes} from 'node:crypto';
import {spawn} from 'node:child_process';
const base=process.env.OMR_BENCH_URL;
if(base!=='https://omr-project-demo.vercel.app')throw Error('Set OMR_BENCH_URL explicitly to the demo origin');
const manifest=JSON.parse(await readFile(process.argv[2],'utf8'));const reportPath=process.argv[3];
const limit=Number(process.argv[4]||10), selected=[...new Set(manifest.map(x=>x.sheet_id))].slice(0,limit);
const me=await fetch(base+'/api/me');const cookie=me.headers.get('set-cookie')?.split(';')[0];if(!me.ok||!cookie)throw Error('No demo cookie');
async function api(p,data,method){const r=await fetch(base+'/api/'+p,{method:method|| (data===undefined?'GET':'POST'),headers:{cookie,origin:base,...(data===undefined?{}:{'content-type':'application/json'})},body:data===undefined?undefined:JSON.stringify(data)});const j=await r.json();if(!r.ok)throw Error(`${p}: HTTP ${r.status} ${j.error}`);return j}
const engine=process.env.OMR_BENCH_ENGINE_URL;
async function readEngine(jobId){
 if(!engine)return api(`jobs/${jobId}/read`,{});
 if(!/^https:\/\/omr-demo-engine-[a-z0-9-]+\.vercel\.app$/.test(engine)||!process.env.OMR_SIGNING_SECRET)throw Error('Invalid preview or missing signing secret');
 const payload=JSON.stringify({job_id:jobId,attempt_id:randomBytes(16).toString('hex')}), timestamp=String(Math.floor(Date.now()/1000));
 const signature=createHmac('sha256',process.env.OMR_SIGNING_SECRET).update(timestamp+'.'+payload).digest('hex');
 const config=['silent','show-error','max-time = 190','write-out = "\\n%{http_code}"','request = "POST"','header = "Content-Type: application/json"',`header = "x-omr-timestamp: ${timestamp}"`,`header = "x-omr-signature: ${signature}"`,'data = '+JSON.stringify(payload)].join('\n');
 const result=await new Promise((resolve,reject)=>{let out='';const child=spawn('npx.cmd',['--yes','vercel@latest','curl',engine+'/infer','--','--config','-'],{shell:true,stdio:['pipe','pipe','pipe']});child.stdout.on('data',c=>out+=c);child.stderr.resume();child.on('error',reject);child.on('close',code=>code?reject(Error('Preview request failed: '+code)):resolve(out));child.stdin.end(config);});
 const split=result.trim().lastIndexOf('\n');const status=Number(result.slice(split+1)),data=JSON.parse(result.slice(0,split));if(status!==200)throw Error('Preview HTTP '+status+' '+(data.error?.message||''));return {result:data};
}
const cases=[];
for(const sheet of selected) for(const roles of [['A'],['A','B']]) {
 let job;const started=performance.now();const c={sheet_id:sheet,variant:roles.join('+'),upload_ms:0};
 try{job=await api('jobs',{});c.create_ms=performance.now()-started;
  const uploadStart=performance.now();
  const entries=[];
  for(const role of roles){const item=manifest.find(x=>x.sheet_id===sheet&&x.role===role);if(!item)throw Error('missing image');const body=await readFile(item.path);const ext=path.extname(item.path).slice(1).toLowerCase();const type=ext==='png'?'image/png':'image/jpeg';const grant=await api(`jobs/${job.id}/upload`,{role,size:body.length,type,ext});const itemToUpload={body,type,pathname:grant.pathname};entries.push(itemToUpload);
    if(!process.env.OMR_BENCH_PARALLEL){await upload(itemToUpload.pathname,itemToUpload.body,{access:'private',handleUploadUrl:base+'/api/upload',contentType:itemToUpload.type,multipart:itemToUpload.body.length>5*1024*1024,headers:{cookie,origin:base}});await api(`jobs/${job.id}/upload-complete`,{pathname:itemToUpload.pathname});}}
  if(process.env.OMR_BENCH_PARALLEL){const uploads=await Promise.allSettled(entries.map(async item=>{await upload(item.pathname,item.body,{access:'private',handleUploadUrl:base+'/api/upload',contentType:item.type,multipart:item.body.length>5*1024*1024,headers:{cookie,origin:base}});await api(`jobs/${job.id}/upload-complete`,{pathname:item.pathname});}));const failed=uploads.find(x=>x.status==='rejected');if(failed)throw failed.reason;}
  c.upload_ms=performance.now()-uploadStart;
  const t=performance.now();const result=await readEngine(job.id);c.read_ms=performance.now()-t;c.total_ms=performance.now()-started;c.engine_s=result.result?.elapsed_seconds;c.timings=result.result?.timings;c.pair_check=result.result?.pair_check;c.methods={};for(const m of ['cnn','cla'])c.methods[m]=result.result.methods[m].map(x=>({proposed_answer:x.proposed_answer,needs_review:x.needs_review,review_reasons:x.review_reasons,used_B:x.used_B}));
 }catch(e){c.error=e.message;}finally{if(job)try{await api('jobs/'+job.id,undefined,'DELETE')}catch(e){c.cleanup_error=e.message}}
 cases.push(c);await writeFile(reportPath,JSON.stringify({url:base,cases},null,2));console.log(sheet,c.variant,c.error||Math.round(c.total_ms)+' ms');
}

// Real local browser/API -> private Blob -> protected Vercel engine -> Neon.
// The fixture password is only injected into this loopback-bound child process.
// It is never installed in Vercel or written to a credential file.
import {spawn} from 'node:child_process';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {parseEnv} from 'node:util';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {hashPassword} from '../apps/web/lib/password.mjs';
const root=process.cwd(),web=resolve('apps/web'),origin='http://127.0.0.1:3017';
const password='loopback-only-integration-fixture-20261028';
const env={...process.env,...parseEnv(readFileSync(resolve(web,'.env.local'),'utf8')),
  OMR_OWNER_PASSWORD_HASH:hashPassword(password),NEXT_TELEMETRY_DISABLED:'1'};
const out=resolve('presentation_build/private_web_smoke_20261028');mkdirSync(out,{recursive:true});
const server=spawn(process.execPath,[resolve(web,'node_modules/next/dist/bin/next'),'dev','--hostname','127.0.0.1','--port','3017'],{cwd:web,env,stdio:['ignore','pipe','pipe']});
server.stdout.on('data',chunk=>process.stdout.write(chunk));server.stderr.on('data',()=>{});
process.on('SIGINT',()=>{server.kill();process.exit(0);});
let ready=false;
for(let i=0;i<40;i++){await new Promise(r=>setTimeout(r,500));try{const r=await fetch(origin);if(r.ok){ready=true;break;}}catch{}}
if(!ready){server.kill();throw Error('Loopback server did not start');}
const report={purpose:'functional_test_not_human_label_verification',checks:{}};
let cookie='';
async function request(path,data,options={}){
  const headers={...(data===undefined?{}:{'Content-Type':'application/json',Origin:origin}),...(cookie?{Cookie:cookie}:{}),...options.headers};
  const r=await fetch(origin+'/api/'+path,{method:data===undefined?'GET':'POST',headers,body:data===undefined?undefined:JSON.stringify(data)});
  return r;
}
function check(name,value){report.checks[name]=!!value;if(!value)throw Error('Failed check: '+name);}
try{
  check('anonymous_jobs_rejected',(await request('jobs')).status===401);
  const wrong=await request('login',{password:'incorrect'});
  if(wrong.status!==401)console.log(JSON.stringify({wrong_password_http:wrong.status,response:await wrong.json()}));
  check('wrong_password_rejected',wrong.status===401);
  let r=await request('login',{password});check('login',r.status===200);cookie=r.headers.get('set-cookie').split(';')[0];
  check('csrf_rejected',(await request('jobs',{}, {headers:{Origin:'https://example.invalid'}})).status===403);
  const created=await (await request('jobs',{})).json();check('draft_saved',created.status==='draft');
  const sample=readFileSync(resolve('presentation_build/cloud_probe_comparison_20261028_matched/samples/S0035_A.jpg'));
  const grant=await (await request(`jobs/${created.id}/upload`,{role:'A',size:sample.length,type:'image/jpeg',ext:'jpg'})).json();
  check('source_reserved',!!grant.pathname);
  const client=await import(pathToFileURL(resolve(web,'node_modules/@vercel/blob/dist/client.js')));
  const nativeFetch=globalThis.fetch;
  globalThis.fetch=async(input,init)=>{
    const url=typeof input==='string'?input:input instanceof URL?input.href:input.url;
    if(url.startsWith(origin+'/'))return nativeFetch(input,{...init,headers:{...init?.headers,Cookie:cookie,Origin:origin}});
    return nativeFetch(input,init);
  };
  try{await client.upload(grant.pathname,new File([sample],'private-fixture.jpg',{type:'image/jpeg'}),{access:'private',contentType:'image/jpeg',handleUploadUrl:origin+'/api/upload',headers:{Cookie:cookie,Origin:origin}});}
  finally{globalThis.fetch=nativeFetch;}
  const uploaded=await (await request(`jobs/${created.id}/upload-complete`,{pathname:grant.pathname})).json();check('ready_saved',uploaded.status==='ready');
  r=await request(`jobs/${created.id}/read`,{});const job=await r.json();
  if(r.status!==200)throw Error(`Engine through web HTTP ${r.status}: ${job.error}`);
  check('private_end_to_end_read',job.status==='complete'&&job.result.methods.cnn.length===100);
  check('v3',job.result.model_version==='confirmed-finetune-v3-risk-first');
  const baseline=JSON.parse(readFileSync(resolve('presentation_build/cloud_probe_comparison_20261028_matched/S0035_A-only_windows.json'),'utf8'));
  check('cnn_cla_match_baseline',['cnn','cla'].every(method=>job.result.methods[method].every((row,i)=>['proposed_answer','needs_review','review_reasons','used_B'].every(key=>row[key]===baseline.methods[method][i][key]))));
  const loaded=await (await request(`jobs/${created.id}`)).json();check('reload_restores_result',loaded.result.model_sha256===job.result.model_sha256);
  const image=await request(`jobs/${created.id}/image?role=A&view=rows`);check('private_image',image.status===200&&image.headers.get('cache-control').includes('no-store'));
  await image.arrayBuffer();
  const reviewed=await (await request(`jobs/${created.id}/review`,{revision:job.revision,method:'cnn',question:1,answer:'blank'})).json();
  check('human_separate',reviewed.reviews.cnn['1'].answer==='blank'&&reviewed.result.methods.cnn[0].proposed_answer===job.result.methods.cnn[0].proposed_answer);
  check('stale_revision_rejected',(await request(`jobs/${created.id}/review`,{revision:job.revision,method:'cnn',question:2,answer:'1'})).status===409);
  const scored=await (await request(`jobs/${created.id}/score`,{revision:reviewed.revision,key:Array(100).fill('1')})).json();check('score_provisional',scored.scores.cnn.final===false&&scored.scores.cnn.confirmed===1);
  const csv=await (await request(`jobs/${created.id}/export`)).text();check('csv_separates_model_and_human',csv.includes('cnn_model')&&csv.includes('cnn_human')&&csv.includes('provisional'));
  const anonymous=await fetch(origin+`/api/jobs/${created.id}/image?role=A&view=rows`);check('anonymous_image_rejected',anonymous.status===401);
  report.job_id=created.id;report.origin=origin;
  await request('logout',{});check('logout_revokes_session',(await request('me')).status===401);
  writeFileSync(resolve(out,'report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));console.log('LOCAL_SMOKE_READY: loopback server stays open for the browser inspection; Ctrl+C stops only this test server.');
}catch(error){
  writeFileSync(resolve(out,'report.json'),JSON.stringify(report,null,2));server.kill();
  let message=error.message;for(const [key,value] of Object.entries(env))if(value?.length>6&&/SECRET|TOKEN|PASSWORD|DATABASE|POSTGRES/.test(key))message=message.replaceAll(value,'[redacted]');
  console.error(error.name,message.slice(-1500));process.exit(1);
}

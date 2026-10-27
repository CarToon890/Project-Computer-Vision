// Use only with smoke_private_web.mjs's loopback fixture server running.
import {readFileSync,writeFileSync} from 'node:fs';
import {parseEnv} from 'node:util';
import {createRequire} from 'node:module';
import {createHash,createHmac,randomBytes} from 'node:crypto';
import {resolve} from 'node:path';
const require=createRequire(resolve('apps/web/package.json'));
const {Pool}=require('pg');
const config=parseEnv(readFileSync('apps/web/.env.local','utf8'));
const url=new URL(config.DATABASE_URL);url.searchParams.set('sslmode','verify-full');
const pool=new Pool({connectionString:url.href,max:2});
const origin='http://127.0.0.1:3017',password='loopback-only-integration-fixture-20261028';
let cookie='',fixtures=[],lease=null,originalCap=null;
const report={purpose:'failure_and_expiry_simulation_not_accuracy',checks:{}};
function check(name,value){report.checks[name]=!!value;if(!value)throw Error('Failed check: '+name);}
async function request(path,data,method=data===undefined?'GET':'POST',extra={}){
  return fetch(origin+'/api/'+path,{method,headers:{'Content-Type':'application/json',Origin:origin,...(cookie?{Cookie:cookie}:{}),...extra},body:method==='GET'?undefined:JSON.stringify(data||{})});
}
async function signIn(){const response=await request('login',{password});check('fixture_login',response.status===200);cookie=response.headers.get('set-cookie').split(';')[0];}
try{
  await signIn();
  for(let i=0;i<2;i++){const job=await (await request('jobs',{})).json();fixtures.push(job.id);await pool.query('UPDATE omr_jobs SET is_test=true WHERE id=$1',[job.id]);}
  const [a,b]=fixtures;
  const rows=Array.from({length:100},(_,i)=>({question_no:i+1,proposed_answer:'1',needs_review:false}));
  await pool.query("UPDATE omr_jobs SET status='complete',result=$2,images_expires_at=now()-interval '1 second' WHERE id=$1",[a,JSON.stringify({methods:{cnn:rows,cla:rows},assets:{}})]);
  check('expired_image_denied',(await request(`jobs/${a}/image?role=A&view=rows`)).status===410);
  check('expired_review_denied',(await request(`jobs/${a}/review`,{revision:0,method:'cnn',question:1,answer:'1'})).status===409);
  check('expired_results_exportable',(await request(`jobs/${a}/export`)).status===200);
  let r=await request(`jobs/${a}/score`,{revision:0,key:Array(100).fill('1')});check('expired_key_and_score_retained',r.status===200);

  // Reserve the real singleton only if it is idle. Never overwrite another run.
  const db=await pool.connect();
  try{
    await db.query('BEGIN');const {rows:[slot]}=await db.query('SELECT *,expires_at>now() AS active FROM omr_engine_slot WHERE singleton FOR UPDATE');
    if(slot.active)throw Error('An actual inference is active; lock test cancelled');
    lease=randomBytes(16).toString('hex');
    await db.query("UPDATE omr_engine_slot SET job_id=$1,attempt_id=$2,expires_at=now()+interval '90 seconds' WHERE singleton",[a,lease]);
    await db.query("UPDATE omr_jobs SET status='processing',attempt_id=$2 WHERE id=$1",[a,lease]);await db.query('COMMIT');
  }catch(e){await db.query('ROLLBACK');throw e;}finally{db.release();}
  const concurrent=await request(`jobs/${b}/read`,{}),concurrentError=await concurrent.json();
  check('second_job_blocked_by_database_lease',concurrent.status===409&&typeof concurrentError.error==='string'&&concurrentError.error.includes('มีงาน'));
  await pool.query("UPDATE omr_engine_slot SET expires_at=now()-interval '1 second' WHERE singleton AND attempt_id=$1",[lease]);
  const interrupted=await (await request(`jobs/${a}`)).json();check('stale_processing_becomes_interrupted',interrupted.status==='interrupted');
  await pool.query('UPDATE omr_engine_slot SET job_id=NULL,attempt_id=NULL,expires_at=NULL WHERE singleton AND attempt_id=$1',[lease]);lease=null;

  const {rows:[usage]}=await pool.query('SELECT used_bytes,cap_bytes FROM omr_storage_usage WHERE singleton');originalCap=usage.cap_bytes;
  await pool.query('UPDATE omr_storage_usage SET cap_bytes=GREATEST(used_bytes,1) WHERE singleton');
  check('quota_blocks_new_upload',(await request(`jobs/${b}/upload`,{role:'A',size:1,type:'image/jpeg',ext:'jpg'})).status===409);
  await pool.query('UPDATE omr_storage_usage SET cap_bytes=$1 WHERE singleton',[originalCap]);originalCap=null;

  const {rows:[other]}=await pool.query("SELECT count(*)::int AS n FROM omr_blobs WHERE kind<>'model' AND expires_at<=now() AND job_id<>$1",[a]);
  if(other.n)throw Error('Other expired user files exist; cleanup test will not delete them');
  const {put,head}=require('@vercel/blob');
  const pathname=`jobs/${a}/sources/${randomBytes(16).toString('hex')}.jpg`,content=Buffer.from('expiry-test-only');
  await pool.query("INSERT INTO omr_blobs(pathname,job_id,bytes,status,kind,expires_at) VALUES($1,$2,$3,'reserved','source',now()-interval '1 second')",[pathname,a,content.length]);
  await pool.query('UPDATE omr_storage_usage SET used_bytes=used_bytes+$1 WHERE singleton',[content.length]);
  await put(pathname,content,{access:'private',addRandomSuffix:false,allowOverwrite:false,token:config.BLOB_READ_WRITE_TOKEN});
  const {rows:[before]}=await pool.query("SELECT count(*)::int AS n FROM omr_blobs WHERE kind='model'");
  r=await request('cleanup',undefined,'GET',{Authorization:'Bearer '+config.CRON_SECRET});
  const cleaned=await r.json();check('expired_blob_removed',r.status===200&&cleaned.deleted>=1);
  const {rows:[after]}=await pool.query("SELECT count(*)::int AS n FROM omr_blobs WHERE kind='model'");
  check('model_objects_preserved',before.n===after.n&&!!(await head('system/v3/manifest.json',{token:config.BLOB_READ_WRITE_TOKEN})));
  check('cleanup_keeps_answers_and_key',(await request(`jobs/${a}/export`)).status===200);
  for(const jobId of fixtures){check('delete_own_fixture_'+jobId.slice(0,6),(await request(`jobs/${jobId}`,{},'DELETE')).status===200);check('deleted_job_hidden_'+jobId.slice(0,6),(await request(`jobs/${jobId}`)).status===404);}

  const token=cookie.split('=')[1];await pool.query("UPDATE omr_sessions SET expires_at=now()-interval '1 second' WHERE token_hash=$1",[createHash('sha256').update(token).digest('hex')]);
  check('expired_session_rejected',(await request('me')).status===401);
  for(let i=0;i<5;i++)check('wrong_password_'+i,(await request('login',{password:'incorrect'})).status===401);
  check('password_attempts_throttled',(await request('login',{password:'incorrect'})).status===429);
  const localKey=createHmac('sha256',config.OMR_AUTH_SECRET).update('local').digest('hex');
  await pool.query('DELETE FROM omr_login_attempts WHERE ip_hash=$1',[localKey]);
  await signIn();await request('logout',{});
  writeFileSync('presentation_build/private_web_smoke_20261028/resilience.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}catch(e){let message=e.message;for(const [key,value]of Object.entries(config))if(value.length>6&&/TOKEN|SECRET|DATABASE|PASSWORD/.test(key))message=message.replaceAll(value,'[redacted]');console.error(e.name,message.slice(-1200));process.exitCode=1;}
finally{
  if(lease)await pool.query('UPDATE omr_engine_slot SET job_id=NULL,attempt_id=NULL,expires_at=NULL WHERE singleton AND attempt_id=$1',[lease]);
  if(originalCap!==null)await pool.query('UPDATE omr_storage_usage SET cap_bytes=$1 WHERE singleton',[originalCap]);
  await pool.end();
}

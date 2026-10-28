// Configure the separate free demo engine without exposing credentials.
import {loadEnvFile} from 'node:process';
import {readFileSync,appendFileSync} from 'node:fs';
import {randomBytes,createHash} from 'node:crypto';
import {resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
const [cli,python]=process.argv.slice(2),root=process.cwd(),bundle=resolve('presentation_build/omr_demo_20261028');
const project=resolve(bundle,'engine'),envfile=resolve(project,'.env.local');
if(!cli||!python)throw Error('Expected CLI and Python paths');
const linked=JSON.parse(readFileSync(resolve(project,'.vercel/project.json'),'utf8'));
if(linked.projectName!=='omr-demo-engine'||linked.orgId!=='team_zYK3JQ8mj7CZKXONoTxcbMJH')throw Error('Wrong project');
loadEnvFile(envfile);
if(!process.env.DATABASE_URL||!process.env.BLOB_READ_WRITE_TOKEN)throw Error('Demo database and Blob are not linked');
process.env.OMR_SIGNING_SECRET=process.env.OMR_SIGNING_SECRET||randomBytes(32).toString('hex');
appendFileSync(envfile,`\nOMR_SIGNING_SECRET="${process.env.OMR_SIGNING_SECRET}"\n`);
const values={OMR_SIGNING_SECRET:process.env.OMR_SIGNING_SECRET,OMR_MODEL_MANIFEST_SHA256:createHash('sha256').update(readFileSync(resolve(bundle,'system_upload/manifest.json'))).digest('hex'),VERCEL_SUPPORT_LARGE_FUNCTIONS:'1'};
for(const [name,value] of Object.entries(values))for(const environment of ['preview','production']){
  const result=spawnSync(process.execPath,[cli,'env','add',name,environment,'--force','--scope',linked.orgId],{cwd:project,input:value,encoding:'utf8'});
  if(result.status!==0)throw Error(`Unable to configure ${name} for ${environment}`);
  console.log(`Configured ${name} for ${environment}`);
}
for(const [script,args] of [['tools/apply_cloud_schema.py',[]],['tools/publish_vercel_runtime.py',['--bundle',bundle]]]){
  const result=spawnSync(python,[script,...args],{cwd:root,env:process.env,encoding:'utf8'});
  if(result.status!==0)throw Error(`${script} failed; diagnostic suppressed to protect credentials`);
  console.log(`${script}: completed`);
}

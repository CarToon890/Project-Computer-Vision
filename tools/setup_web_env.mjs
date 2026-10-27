// Connect only the already-provisioned free resources. No billing APIs are used.
import {readFileSync,appendFileSync} from 'node:fs';
import {parseEnv} from 'node:util';
import {randomBytes} from 'node:crypto';
import {resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
const [cli,origin]=process.argv.slice(2);
if(!cli || !origin)throw Error('Usage: setup_web_env.mjs <cli-js> <engine-preview-origin>');
const target=new URL(origin);
if(target.protocol!=='https:'||!target.hostname.endsWith('.vercel.app')||target.pathname!=='/')throw Error('Expected exact engine Preview origin');
const root=process.cwd(),project=resolve(root,'apps/web'),envfile=resolve(project,'.env.local');
const engine=parseEnv(readFileSync(resolve(root,'apps/engine/.env.local'),'utf8'));
const existing=parseEnv(readFileSync(envfile,'utf8'));
const values={OMR_ENGINE_URL:target.origin,OMR_AUTH_SECRET:existing.OMR_AUTH_SECRET||randomBytes(32).toString('hex'),
  CRON_SECRET:existing.CRON_SECRET||randomBytes(32).toString('hex')};
for(const key of ['DATABASE_URL','BLOB_READ_WRITE_TOKEN','OMR_SIGNING_SECRET']){
  if(!engine[key])throw Error(`Engine key missing: ${key}`);values[key]=engine[key];
}
for(const [name,value] of Object.entries(values)){
  if(existing[name]!==value)appendFileSync(envfile,`\n${name}=${JSON.stringify(value)}\n`);
  const result=spawnSync(process.execPath,[cli,'env','add',name,'preview','--force','--scope','team_zYK3JQ8mj7CZKXONoTxcbMJH'],{cwd:project,input:value,encoding:'utf8',env:process.env});
  if(result.status!==0)throw Error(`Could not configure ${name}; credential values are hidden`);
  console.log(`Web Preview configured: ${name}`);
}
console.log('Free resources linked by server environment. Owner password is still required; web remains locked.');

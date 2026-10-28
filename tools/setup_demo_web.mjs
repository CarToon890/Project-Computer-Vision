// Point the public demo only at its separate free database, Blob, and engine.
import {readFileSync,appendFileSync} from 'node:fs';
import {parseEnv} from 'node:util';
import {randomBytes} from 'node:crypto';
import {resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
const cli=process.argv[2],root=resolve('presentation_build/omr_demo_20261028');
const engine=parseEnv(readFileSync(resolve(root,'engine/.env.local'),'utf8'));
const web=resolve(root,'web'),linked=JSON.parse(readFileSync(resolve(web,'.vercel/project.json'),'utf8'));
if(!cli||linked.projectName!=='omr-project-demo'||linked.orgId!=='team_zYK3JQ8mj7CZKXONoTxcbMJH')throw Error('Wrong demo project');
const values={OMR_DEMO_MODE:'1',OMR_ENGINE_URL:'https://omr-demo-engine.vercel.app',CRON_SECRET:randomBytes(32).toString('hex'),OMR_AUTH_SECRET:randomBytes(32).toString('hex')};
for(const key of ['DATABASE_URL','BLOB_READ_WRITE_TOKEN','OMR_SIGNING_SECRET']){if(!engine[key])throw Error(`Missing ${key}`);values[key]=engine[key];}
for(const [name,value] of Object.entries(values)){
  appendFileSync(resolve(web,'.env.local'),`\n${name}=${JSON.stringify(value)}\n`);
  for(const environment of ['production','preview']){
    const result=spawnSync(process.execPath,[cli,'env','add',name,environment,'--force','--scope',linked.orgId],{cwd:web,input:value,encoding:'utf8'});
    if(result.status!==0)throw Error(`Cannot configure ${name} in ${environment}; credentials hidden`);
    console.log(`Configured ${name} for ${environment}`);
  }
}

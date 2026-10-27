// Guard the first-deployment behavior of Vercel CLI 65.4.0.
import {spawnSync} from 'node:child_process';
import {resolve} from 'node:path';
const cli=process.argv[2];
if(!cli)throw Error('Usage: deploy_web_preview.mjs <cli-js>');
const project='prj_mGvauZoABWAqQi7qP4hgmdhF3UBz',team='team_zYK3JQ8mj7CZKXONoTxcbMJH';
const probe=spawnSync(process.execPath,[cli,'api',`/v9/projects/${project}?teamId=${team}`],{encoding:'utf8'});
if(probe.status!==0)throw Error('Cannot verify deployment target; nothing deployed');
const state=JSON.parse(probe.stdout);
if(state.id!==project||state.targets?.production?.id!=='dpl_2bcBiYo8Bqh3FVxE4bhPYkZrp1WG'||state.targets.production.readyState!=='READY')
  throw Error('Project is not in the verified post-first-deployment state; nothing deployed');
console.log('Verified: first deployment already exists. CLI documents subsequent --environment preview deployments as Preview. Production is not promoted.');
const result=spawnSync(process.execPath,[cli,'deploy','--environment','preview','--yes','--scope',team],{
  cwd:resolve('apps/web'),stdio:'inherit',env:process.env});
process.exit(result.status??1);

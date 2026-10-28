// Run in a private local terminal. Never supply a password as a command argument.
import {writeFileSync,existsSync,readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {hashPassword} from '../apps/web/lib/password.mjs';
const root=resolve(fileURLToPath(new URL('..',import.meta.url)));
const cli=process.argv[2]||resolve(process.env.LOCALAPPDATA||'', 'npm-cache/_npx/50e9ffea52bc6e2a/node_modules/vercel/dist/index.js');
if(!existsSync(cli))throw Error('Pinned Vercel CLI was not found. Ask Codex to locate it before setting a password.');
const linked=JSON.parse(readFileSync(resolve(root,'apps/web/.vercel/project.json'),'utf8'));
if(linked.projectId!=='prj_mGvauZoABWAqQi7qP4hgmdhF3UBz'||linked.orgId!=='team_zYK3JQ8mj7CZKXONoTxcbMJH')throw Error('Web project linkage changed. No credential has been entered or sent.');
if(!cli || !process.stdin.isTTY)throw Error('Run in an interactive private terminal: node tools/set_owner_password.mjs <vercel-cli-js>');
async function hidden(prompt){
  process.stdout.write(prompt);
  process.stdin.setRawMode(true);process.stdin.resume();
  return new Promise((resolve,reject)=>{
    let value='';const input=chunk=>{for(const ch of chunk.toString('utf8')){
      if(ch==='\u0003'){finish();reject(Error('Cancelled'));return;}
      if(ch==='\r'||ch==='\n'){finish();resolve(value);return;}
      if(ch==='\u007f'||ch==='\b'){value=value.slice(0,-1);continue;}
      if(ch>=' '){if(value.length+ch.length>256){finish();reject(Error('Password exceeds 256 characters. Nothing saved.'));return;}value+=ch;}
    }};
    function finish(){process.stdin.off('data',input);process.stdin.setRawMode(false);process.stdin.pause();process.stdout.write('\n');}
    process.stdin.on('data',input);
  });
}
const first=await hidden('Set your private password (12–256 characters, input hidden): ');
const second=await hidden('Confirm password (input hidden): ');
if(first!==second)throw Error('Passwords do not match. Nothing saved.');
const hash=hashPassword(first);
// Local handoff only: no network required in the user's terminal. The ignored
// file contains a one-way hash, not the password. Codex installs it to Preview.
writeFileSync(resolve(root,'apps/web/.env.owner-password-hash'),hash,{encoding:'utf8',mode:0o600});
console.log('เตรียมรหัสเรียบร้อยแล้ว บอก Codex ว่า “ตั้งแล้ว” เพื่อเชื่อมกับเว็บ');

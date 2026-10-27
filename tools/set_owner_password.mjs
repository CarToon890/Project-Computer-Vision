// Run in a private local terminal. Never supply a password as a command argument.
import {appendFileSync,existsSync,readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
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
const result=spawnSync(process.execPath,[cli,'env','add','OMR_OWNER_PASSWORD_HASH','preview','--force','--scope','team_zYK3JQ8mj7CZKXONoTxcbMJH'],{cwd:resolve(root,'apps/web'),input:hash,encoding:'utf8'});
if(result.status!==0){
  const diagnostic=(result.stderr||'')+' '+(result.stdout||'')+' '+(result.error?.message||'');
  let reason='ไม่ทราบสาเหตุแน่ชัด';
  if(/not logged in|not authenticated|unauthorized|invalid token|login/i.test(diagnostic)) reason='การเข้าสู่ระบบ Vercel ไม่พร้อม';
  else if(/eacces|eperm|access denied|permission denied|operation not permitted/i.test(diagnostic)) reason='คำสั่งถูกจำกัดสิทธิ์หรือการเชื่อมต่อ';
  else if(/enotfound|econn|network|fetch failed|fetch failed|timed?\s*out|timeout|certificate/i.test(diagnostic)) reason='เชื่อมต่อ Vercel ไม่สำเร็จ';
  else if(/forbidden|403|not authorized/i.test(diagnostic)) reason='บัญชีไม่มีสิทธิ์แก้ environment variable ของโปรเจกต์';
  console.error(`บันทึกไม่สำเร็จ: ${reason} (รหัส ${result.status ?? 'ไม่มี'})`);
  console.error('ไม่มีการแสดงรหัสผ่านหรือ hash กรุณาส่งเฉพาะข้อความนี้ให้ Codex ตรวจต่อ');
  process.exit(1);
}
// Next's dotenv-expand would otherwise interpret the scrypt $ delimiters.
appendFileSync(resolve(root,'apps/web/.env.local'),`\nOMR_OWNER_PASSWORD_HASH="${hash.replaceAll('$','\\$')}"\n`);
console.log('Password hash saved to Preview and ignored local environment. Redeploy Preview to activate it. Existing sessions are revoked by the new hash.');

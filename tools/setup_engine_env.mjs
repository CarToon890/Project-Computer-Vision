// Secrets stay in the ignored local env file and child-process stdin, never argv/logs.
import { loadEnvFile } from 'node:process';
import { readFileSync, appendFileSync } from 'node:fs';
import { randomBytes, createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const [cli, python, bundle] = process.argv.slice(2);
if (!cli || !python || !bundle) throw Error('Usage: setup_engine_env.mjs <vercel-cli-js> <python> <deployment-bundle>');
const root = process.cwd();
const project = resolve(root, 'apps/engine');
const envfile = resolve(project, '.env.local');
loadEnvFile(envfile);
for (const key of ['DATABASE_URL', 'BLOB_READ_WRITE_TOKEN']) {
  if (!process.env[key]) throw Error(`Linked environment is missing ${key}`);
}
if (!process.env.OMR_SIGNING_SECRET) {
  process.env.OMR_SIGNING_SECRET = randomBytes(32).toString('hex');
  appendFileSync(envfile, `\nOMR_SIGNING_SECRET="${process.env.OMR_SIGNING_SECRET}"\n`);
}
const manifest = readFileSync(resolve(bundle, 'system_upload/manifest.json'));
const manifestHash = createHash('sha256').update(manifest).digest('hex');
const values = { OMR_SIGNING_SECRET: process.env.OMR_SIGNING_SECRET,
  OMR_MODEL_MANIFEST_SHA256: manifestHash, VERCEL_SUPPORT_LARGE_FUNCTIONS: '1' };
for (const [name, value] of Object.entries(values)) {
  const result = spawnSync(process.execPath, [cli, 'env', 'add', name, 'preview', '--force',
    '--scope', 'team_zYK3JQ8mj7CZKXONoTxcbMJH'], { cwd: project, input: value, encoding: 'utf8', env: process.env });
  if (result.status !== 0) throw Error(`Could not set ${name}; CLI exit ${result.status}. Values were not logged.`);
  console.log(`Preview environment configured: ${name}`);
}
for (const [script, args] of [['tools/apply_cloud_schema.py', []], ['tools/publish_vercel_runtime.py', ['--bundle', resolve(bundle)]]]) {
  const result = spawnSync(python, [script, ...args], { cwd: root, env: process.env, encoding: 'utf8' });
  if (result.status !== 0) {
    // Redact every loaded secret before reporting diagnostics.
    let diagnostic = result.stderr || result.stdout || 'No diagnostic';
    for (const [name, value] of Object.entries(process.env)) {
      if (value && value.length > 6 && /TOKEN|PASSWORD|SECRET|DATABASE_URL|POSTGRES_URL|PGHOST/.test(name)) diagnostic = diagnostic.replaceAll(value, '[redacted]');
    }
    throw Error(`${script} failed: ${diagnostic.slice(-2500)}`);
  }
  console.log(`${script}: completed`);
}
console.log('Engine Preview secrets and private model are ready. No credential values were printed.');

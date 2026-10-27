"""Private Preview parity check. Never writes dataset labels or changes image pairs.

Run with the linked engine's environment loaded by Node --env-file. Test images
are private, expire in seven days, and are counted against the storage cap.
"""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
TEAM = 'team_zYK3JQ8mj7CZKXONoTxcbMJH'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment', required=True)
    parser.add_argument('--cli', required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from urllib.parse import urlsplit
    url = urlsplit(args.deployment)
    if url.scheme != 'https' or not url.hostname.endswith('.vercel.app') or url.path not in {'', '/'}:
        raise SystemExit('Expected an exact HTTPS Preview origin.')
    if args.output.exists():
        raise SystemExit('Report already exists; choose a new directory.')
    for key in ('OMR_SIGNING_SECRET', 'DATABASE_URL', 'BLOB_READ_WRITE_TOKEN'):
        if not os.environ.get(key):
            raise SystemExit(f'Missing linked key: {key}')
    args.output.mkdir(parents=True)
    import psycopg
    from psycopg.types.json import Jsonb
    from vercel.blob.sync import put_blob

    def request(path, data=None, valid_signature=True):
        options = ['silent', 'show-error', 'max-time = 190', 'write-out = "\\n%{http_code}"']
        if data is not None:
            body = json.dumps(data, separators=(',', ':'))
            timestamp = str(int(time.time()))
            signature = hmac.new(os.environ['OMR_SIGNING_SECRET'].encode(),
                                 (timestamp + '.' + body).encode(), hashlib.sha256).hexdigest()
            if not valid_signature:
                signature = '0' * 64
            # Pass signature through stdin, never process arguments or log output.
            options += ['request = "POST"', 'header = "Content-Type: application/json"',
                        f'header = "x-omr-timestamp: {timestamp}"',
                        f'header = "x-omr-signature: {signature}"',
                        'data = ' + json.dumps(body)]
        process = subprocess.run(['node', args.cli, '--scope', TEAM, 'curl',
                                  args.deployment.rstrip('/') + path, '--', '--config', '-'],
                                 input='\n'.join(options), capture_output=True, text=True,
                                 encoding='utf-8', cwd=ROOT / 'apps/engine', timeout=215)
        if process.returncode:
            raise RuntimeError(f'Preview request failed (curl exit {process.returncode}); no secrets logged.')
        body, status = process.stdout.strip().rsplit('\n', 1)
        try:
            return int(status), json.loads(body)
        except (ValueError, TypeError):
            raise RuntimeError(f'Preview returned a non-JSON response (HTTP {status}).') from None

    report = {'purpose': 'functional_parity_not_independent_accuracy',
              'deployment': args.deployment, 'cases': [], 'security': {}}
    status, health = request('/health')
    if status != 200 or not health.get('configured'):
        raise RuntimeError('Engine is not configured.')
    status, invalid = request('/infer', {'job_id': uuid4().hex, 'attempt_id': uuid4().hex}, False)
    report['security']['forged_signature_rejected'] = status == 401
    if status != 401:
        raise RuntimeError('Unsigned requests must be rejected.')

    def save():
        (args.output / 'comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    save()
    for sid in ('S0035', 'S0106'):
        for variant, roles in [('A-only', ('A',)), ('A+B', ('A', 'B'))]:
            job_id, attempt_id = uuid4().hex, uuid4().hex
            sources, contents = {}, {}
            for role in roles:
                sample = next((args.baseline / 'samples').glob(f'{sid}_{role}.*'))
                key = f'jobs/{job_id}/sources/{uuid4().hex}{sample.suffix.lower()}'
                sources[role], contents[key] = key, sample.read_bytes()
            with psycopg.connect(os.environ['DATABASE_URL'], sslmode='require', connect_timeout=10) as conn:
                usage = conn.execute('SELECT used_bytes,cap_bytes FROM omr_storage_usage WHERE singleton FOR UPDATE').fetchone()
                size = sum(map(len, contents.values()))
                if usage[0] + size > usage[1]:
                    raise RuntimeError('Free storage cap reached. No upload performed.')
                conn.execute('INSERT INTO omr_jobs(id,sources,is_test) VALUES(%s,%s,true)', (job_id, Jsonb(sources)))
                for key, content in contents.items():
                    conn.execute("INSERT INTO omr_blobs(pathname,job_id,bytes,status,kind,expires_at) SELECT %s,id,%s,'reserved','source',images_expires_at FROM omr_jobs WHERE id=%s", (key, len(content), job_id))
                conn.execute('UPDATE omr_storage_usage SET used_bytes=used_bytes+%s WHERE singleton', (size,))
            for key, content in contents.items():
                put_blob(key, content, access='private', content_type='image/jpeg', add_random_suffix=False, allow_overwrite=False)
            with psycopg.connect(os.environ['DATABASE_URL'], sslmode='require', connect_timeout=10) as conn:
                conn.execute("UPDATE omr_blobs SET status='live' WHERE job_id=%s", (job_id,))
                conn.execute("UPDATE omr_jobs SET status='ready' WHERE id=%s", (job_id,))
            started = time.perf_counter()
            status, result = request('/infer', {'job_id': job_id, 'attempt_id': attempt_id})
            case = {'sheet_id': sid, 'variant': variant, 'job_id': job_id,
                    'http_status': status, 'request_seconds': time.perf_counter() - started}
            if status != 200:
                case['error'] = result.get('error')
                report['cases'].append(case)
                save()
                raise RuntimeError(f'{sid} {variant}: inference returned HTTP {status}: {case["error"]}')
            (args.output / f'{sid}_{variant.replace("+", "_")}_vercel.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            baseline = json.loads((args.baseline / f'{sid}_{variant.replace("+", "_")}_windows.json').read_text(encoding='utf-8'))
            case['comparison'] = {}
            for method in ('cnn', 'cla'):
                actual, expected = result['methods'][method], baseline['methods'][method]
                differences = [a['question_no'] for a, b in zip(actual, expected)
                               if any(a[k] != b[k] for k in ('proposed_answer', 'needs_review', 'review_reasons', 'used_B'))]
                case['comparison'][method] = {'question_count': len(actual), 'different_decision_questions': differences}
            case['pair_check_same'] = result['pair_check'] == baseline['pair_check']
            case['model_version'] = result['model_version']
            case['model_sha256'] = result['model_sha256']
            status, cached = request('/infer', {'job_id': job_id, 'attempt_id': uuid4().hex})
            case['repeat_returns_saved_result'] = status == 200 and cached == result
            report['cases'].append(case)
            save()
            print(json.dumps(case), flush=True)
    report['all_decisions_match'] = all(c['pair_check_same'] and c['repeat_returns_saved_result']
        and all(v['question_count'] == 100 and not v['different_decision_questions'] for v in c['comparison'].values()) for c in report['cases'])
    save()
    print(json.dumps({'report': str(args.output / 'comparison.json'), 'all_decisions_match': report['all_decisions_match']}))


if __name__ == '__main__':
    main()

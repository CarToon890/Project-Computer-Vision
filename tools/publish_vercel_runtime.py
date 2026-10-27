"""Publish verified private v3 artifacts after free Blob/Postgres are linked."""
import argparse
import hashlib
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    args = parser.parse_args()
    root = args.bundle.resolve() / 'system_upload'
    raw = (root / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    items = []
    for info in manifest['files'].values():
        key = info['key']
        if key not in {'system/v3/model_config.json', 'system/v3/row_cnn.pt', 'system/v3/form_references.npz'}:
            raise SystemExit('Unexpected model object path; nothing uploaded.')
        content = (root / key.split('/')[-1]).read_bytes()
        if hashlib.sha256(content).hexdigest() != info['sha256']:
            raise SystemExit('Model checksum mismatch; nothing uploaded.')
        items.append((key, content))
    items.append(('system/v3/manifest.json', raw))
    if not os.environ.get('DATABASE_URL') or not os.environ.get('BLOB_READ_WRITE_TOKEN'):
        raise SystemExit('Link the free database and private Blob store first. Required keys are missing.')
    import psycopg
    from vercel.blob.sync import get_blob, put_blob
    from vercel.blob import BlobNotFoundError
    for key, content in items:
        with psycopg.connect(os.environ['DATABASE_URL'], sslmode='require') as conn:
            usage = conn.execute('SELECT used_bytes,cap_bytes FROM omr_storage_usage WHERE singleton FOR UPDATE').fetchone()
            recorded = conn.execute('SELECT bytes FROM omr_blobs WHERE pathname=%s', (key,)).fetchone()
            if not recorded:
                if usage[0] + len(content) > usage[1]:
                    raise SystemExit('Free storage allowance reached; nothing further uploaded.')
                conn.execute("INSERT INTO omr_blobs(pathname,bytes,status,kind) VALUES(%s,%s,'reserved','model')", (key, len(content)))
                conn.execute('UPDATE omr_storage_usage SET used_bytes=used_bytes+%s WHERE singleton', (len(content),))
            elif recorded[0] != len(content):
                raise SystemExit('An immutable v3 object already has a different size; preserved existing data.')
        try:
            existing = get_blob(key, access='private').body
        except BlobNotFoundError:
            put_blob(key, content, access='private', content_type='application/octet-stream',
                     add_random_suffix=False, allow_overwrite=False)
        else:
            if hashlib.sha256(existing).digest() != hashlib.sha256(content).digest():
                raise SystemExit('An immutable v3 object has different content; preserved existing data.')
        with psycopg.connect(os.environ['DATABASE_URL'], sslmode='require') as conn:
            conn.execute("UPDATE omr_blobs SET status='live' WHERE pathname=%s", (key,))
    # This is a checksum, not a password or access token.
    print(json.dumps({'published_objects': len(items), 'access': 'private',
                      'OMR_MODEL_MANIFEST_SHA256': hashlib.sha256(raw).hexdigest()}))


if __name__ == '__main__':
    main()

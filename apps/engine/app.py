"""Vercel FastAPI entrypoint. No background threads survive the response."""
import json
import os
import sys
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from omr_engine.security import EngineError, ID, verify_request

REQUIRED = ('DATABASE_URL', 'BLOB_READ_WRITE_TOKEN', 'OMR_SIGNING_SECRET',
            'OMR_MODEL_MANIFEST_SHA256')


@lru_cache(maxsize=1)
def service():
    from omr_engine.repository import PostgresJobs
    from omr_engine.runtime import ModelRuntime
    from omr_engine.service import EngineService
    from omr_engine.storage import PrivateBlobStore
    if not all(os.environ.get(key) for key in REQUIRED):
        raise EngineError('not_configured', 'ระบบอ่านภาพยังไม่ได้ตั้งค่าครบ', 503)
    store = PrivateBlobStore()
    runtime = ModelRuntime(store, 'system/v3/manifest.json', os.environ['OMR_MODEL_MANIFEST_SHA256'])
    return EngineService(PostgresJobs(os.environ['DATABASE_URL']), runtime, store)


def create_app(provider=service, signing_secret=None):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(EngineError)
    async def engine_error(request, error):
        return JSONResponse({'error': {'code': error.code, 'message': error.message}},
                            status_code=error.status, headers={'Cache-Control': 'no-store'})

    @app.get('/health')
    def health():
        ready = all(os.environ.get(key) for key in REQUIRED)
        return JSONResponse({'service': 'omr-cnn-engine', 'configured': ready},
                            headers={'Cache-Control': 'no-store'})

    @app.post('/infer')
    async def infer(request: Request):
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise EngineError('invalid_request', 'รองรับ JSON เท่านั้น', 415)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 2048:
                raise EngineError('request_too_large', 'คำขอมีขนาดเกินที่รองรับ', 413)
        verify_request(bytes(body), request.headers.get('x-omr-timestamp'),
                       request.headers.get('x-omr-signature'),
                       signing_secret if signing_secret is not None else os.environ.get('OMR_SIGNING_SECRET', ''))
        try:
            value = json.loads(body)
            valid = isinstance(value, dict) and set(value) == {'job_id', 'attempt_id'}
            if not valid or any(not isinstance(value[k], str) or not ID.fullmatch(value[k]) for k in value):
                raise ValueError()
        except (ValueError, TypeError):
            raise EngineError('invalid_request', 'ต้องระบุรหัสงานและรหัสครั้งที่อ่านอย่างถูกต้อง', 422) from None
        result = await run_in_threadpool(provider().infer, value['job_id'], value['attempt_id'])
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})

    return app


app = create_app()

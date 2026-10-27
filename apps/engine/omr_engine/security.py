import hashlib
import hmac
import re
import time

ID = re.compile(r'^[a-f0-9]{32}$')


class EngineError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def verify_request(body, timestamp, signature, secret, now=None):
    if len(secret.encode()) < 32:
        raise EngineError('not_configured', 'ระบบอ่านภาพยังไม่พร้อม', 503)
    try:
        stamp = int(timestamp)
    except (ValueError, TypeError):
        raise EngineError('unauthorized', 'คำขอไม่ผ่านการยืนยัน', 401) from None
    if abs((time.time() if now is None else now) - stamp) > 60:
        raise EngineError('unauthorized', 'คำขอหมดอายุ', 401)
    expected = hmac.new(secret.encode(), str(stamp).encode() + b'.' + body,
                        hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(expected, signature):
        raise EngineError('unauthorized', 'คำขอไม่ผ่านการยืนยัน', 401)


def source_key(job_id, value):
    pattern = rf'jobs/{job_id}/sources/[a-f0-9]{{32}}\.(?:jpg|jpeg|png|heic|heif)'
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise EngineError('invalid_source', 'ไฟล์ภาพไม่ได้อยู่ในงานนี้', 422)
    return value

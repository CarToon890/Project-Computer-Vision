import logging
import threading

from .security import EngineError

log = logging.getLogger('omr.engine')


class EngineService:
    def __init__(self, repository, runtime, store):
        self.repository, self.runtime, self.store = repository, runtime, store
        self.guard = threading.Lock()

    def infer(self, job_id, attempt_id):
        if not self.guard.acquire(blocking=False):
            raise EngineError('busy', 'มีงานกำลังอ่านอยู่ กรุณารอสักครู่', 409)
        claimed = False
        try:
            job, cached = self.repository.claim(job_id, attempt_id)
            if cached is not None:
                return cached
            claimed = True
            result, files = self.runtime.read(job, attempt_id)
            self.repository.reserve_artifacts(job_id, attempt_id, files)
            for key, body in files.items():
                self.store.put(key, body)
            self.repository.complete(job_id, attempt_id, result)
            return result
        except Exception as exception:
            error = exception if isinstance(exception, EngineError) else EngineError('read_failed', 'อ่านภาพไม่สำเร็จ กรุณาลองใหม่', 503)
            if claimed:
                try:
                    self.repository.fail(job_id, attempt_id, error)
                except Exception:
                    log.error('Could not mark failure; lease will expire', extra={'job_id': job_id})
            if not isinstance(exception, EngineError):
                log.error('Inference failed', extra={'job_id': job_id, 'exception_type': type(exception).__name__})
            raise error from None
        finally:
            if claimed:
                try:
                    self.repository.release(job_id, attempt_id)
                except Exception:
                    log.error('Could not release lease; lease will expire', extra={'job_id': job_id})
            self.guard.release()

import logging
import threading
import time

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
            stage = time.perf_counter()
            self.repository.reserve_artifacts(job_id, attempt_id, files)
            reserve_seconds = time.perf_counter() - stage
            stage = time.perf_counter()
            for key, body in files.items():
                self.store.put(key, body)
            if 'timings' in result:
                result['timings']['reserve_seconds'] = reserve_seconds
                result['timings']['artifact_upload_seconds'] = time.perf_counter() - stage
            stage = time.perf_counter()
            self.repository.complete(job_id, attempt_id, result)
            log.info('omr_completion_seconds=%.4f', time.perf_counter() - stage)
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

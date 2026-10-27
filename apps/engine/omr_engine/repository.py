from contextlib import contextmanager

from .security import EngineError


class PostgresJobs:
    def __init__(self, dsn):
        self.dsn = dsn

    @contextmanager
    def connection(self):
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(self.dsn, sslmode='require', connect_timeout=8,
                             row_factory=dict_row) as conn:
            yield conn

    def claim(self, job_id, attempt_id):
        with self.connection() as conn:
            slot = conn.execute('SELECT *, expires_at > now() AS active FROM omr_engine_slot WHERE singleton FOR UPDATE').fetchone()
            job = conn.execute('SELECT *, images_expires_at <= now() AS expired FROM omr_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
            if job is None:
                raise EngineError('not_found', 'ไม่พบงานนี้', 404)
            if job['expired']:
                raise EngineError('images_expired', 'ภาพครบอายุ 7 วัน กรุณาเริ่มงานใหม่', 410)
            if job['status'] == 'complete':
                return job, job['result']
            if slot['active']:
                raise EngineError('busy', 'มีงานกำลังอ่านอยู่ กรุณารอและเปิดสถานะงานต่อ', 409)
            if slot['job_id']:
                conn.execute("UPDATE omr_jobs SET status='interrupted', error_code='interrupted', error_message='งานอ่านภาพหยุดกลางทาง กรุณาลองใหม่' WHERE id=%s AND status='processing' AND attempt_id=%s",
                             (slot['job_id'], slot['attempt_id']))
            if job['status'] not in {'ready', 'failed', 'interrupted', 'processing'} or 'A' not in job['sources']:
                raise EngineError('not_ready', 'กรุณาอัปโหลดภาพ A ให้เรียบร้อยก่อน', 409)
            # Every input must have a confirmed upload belonging to this job.
            if set(job['sources']) - {'A', 'B'}:
                raise EngineError('invalid_source', 'รายการภาพไม่ถูกต้อง', 422)
            for key in job['sources'].values():
                row = conn.execute("SELECT pathname FROM omr_blobs WHERE pathname=%s AND job_id=%s AND kind='source' AND status='live'", (key, job_id)).fetchone()
                if not row:
                    raise EngineError('not_ready', 'ภาพยังอัปโหลดไม่เสร็จ', 409)
            conn.execute("UPDATE omr_engine_slot SET job_id=%s,attempt_id=%s,expires_at=now()+interval '210 seconds' WHERE singleton", (job_id, attempt_id))
            conn.execute("UPDATE omr_jobs SET status='processing',attempt_id=%s,error_code=NULL,error_message=NULL WHERE id=%s", (attempt_id, job_id))
            return job, None

    def _fence(self, conn, job_id, attempt_id):
        row = conn.execute('SELECT singleton FROM omr_engine_slot WHERE singleton AND job_id=%s AND attempt_id=%s AND expires_at>now() FOR UPDATE', (job_id, attempt_id)).fetchone()
        if not row:
            raise EngineError('interrupted', 'งานนี้หมดเวลาหรือมีการเริ่มใหม่แล้ว', 409)

    def reserve_artifacts(self, job_id, attempt_id, files):
        with self.connection() as conn:
            self._fence(conn, job_id, attempt_id)
            usage = conn.execute('SELECT * FROM omr_storage_usage WHERE singleton FOR UPDATE').fetchone()
            size = sum(len(content) for content in files.values())
            if usage['used_bytes'] + size > usage['cap_bytes']:
                raise EngineError('storage_quota', 'พื้นที่โควตาฟรีใกล้เต็ม กรุณาสำรองและลบงานเก่าก่อน', 409)
            expiry = conn.execute('SELECT images_expires_at FROM omr_jobs WHERE id=%s', (job_id,)).fetchone()['images_expires_at']
            for key, content in files.items():
                if not key.startswith(f'jobs/{job_id}/attempts/{attempt_id}/'):
                    raise EngineError('invalid_artifact', 'ตำแหน่งผลอ่านไม่ถูกต้อง', 500)
                conn.execute("INSERT INTO omr_blobs(pathname,job_id,bytes,status,kind,expires_at) VALUES(%s,%s,%s,'reserved','derived',%s)", (key, job_id, len(content), expiry))
            conn.execute('UPDATE omr_storage_usage SET used_bytes=used_bytes+%s WHERE singleton', (size,))

    def complete(self, job_id, attempt_id, result):
        from psycopg.types.json import Jsonb
        with self.connection() as conn:
            self._fence(conn, job_id, attempt_id)
            conn.execute("UPDATE omr_blobs SET status='live' WHERE job_id=%s AND pathname LIKE %s", (job_id, f'jobs/{job_id}/attempts/{attempt_id}/%'))
            conn.execute("UPDATE omr_jobs SET status='complete',result=%s,revision=revision+1 WHERE id=%s AND attempt_id=%s", (Jsonb(result), job_id, attempt_id))

    def fail(self, job_id, attempt_id, error):
        with self.connection() as conn:
            conn.execute("UPDATE omr_jobs SET status='failed',error_code=%s,error_message=%s WHERE id=%s AND attempt_id=%s AND status='processing'", (error.code, error.message, job_id, attempt_id))

    def release(self, job_id, attempt_id):
        with self.connection() as conn:
            conn.execute('UPDATE omr_engine_slot SET job_id=NULL,attempt_id=NULL,expires_at=NULL WHERE singleton AND job_id=%s AND attempt_id=%s', (job_id, attempt_id))

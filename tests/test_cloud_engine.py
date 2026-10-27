"""Private engine HTTP boundary and durable-service contracts; no cloud secrets."""
import hashlib
import hmac
import io
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/engine'))
sys.path.insert(0, str(ROOT / 'src'))
from fastapi.testclient import TestClient
from app import create_app
from omr_engine.runtime import prepare_image
from omr_engine.security import EngineError, source_key
from omr_engine.service import EngineService
from omr_engine.storage import PrivateBlobStore
from PIL import Image

SECRET = 'test-only-signing-secret-with-over-32-characters'
JOB = 'a' * 32
ATTEMPT = 'b' * 32


class EngineHTTPTests(unittest.TestCase):
    def setUp(self):
        self.service = Mock()
        self.service.infer.return_value = {'id': JOB, 'methods': {'cnn': []}}
        self.provider = Mock(return_value=self.service)
        self.client = TestClient(create_app(self.provider, SECRET))

    def request(self, value=None, stamp=None, secret=SECRET, raw=None):
        body = raw if raw is not None else json.dumps(value or {'job_id': JOB, 'attempt_id': ATTEMPT}).encode()
        stamp = str(int(time.time()) if stamp is None else stamp)
        signature = hmac.new(secret.encode(), stamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
        return self.client.post('/infer', content=body, headers={
            'Content-Type': 'application/json', 'X-OMR-Timestamp': stamp, 'X-OMR-Signature': signature})

    def test_signed_request_finishes_before_returning_and_is_not_cacheable(self):
        response = self.request()
        self.assertEqual(response.status_code, 200)
        self.service.infer.assert_called_once_with(JOB, ATTEMPT)
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_forged_or_old_signature_does_not_load_service(self):
        self.assertEqual(self.request(secret='wrong').status_code, 401)
        self.assertEqual(self.request(stamp=int(time.time()) - 120).status_code, 401)
        self.provider.assert_not_called()

    def test_no_caller_supplied_url_or_extra_fields(self):
        response = self.request({'job_id': JOB, 'attempt_id': ATTEMPT, 'image_url': 'http://localhost/private'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.request(raw=b'{broken').status_code, 422)
        self.assertEqual(self.request(raw=b'x' * 2049).status_code, 413)
        self.provider.assert_not_called()

    def test_busy_and_expired_job_errors_retain_status_without_details(self):
        for code, status in [('busy', 409), ('images_expired', 410)]:
            self.service.infer.side_effect = EngineError(code, 'คำแนะนำ', status)
            response = self.request()
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()['error']['code'], code)

    def test_source_paths_cannot_escape_job_or_fetch_network_urls(self):
        valid = f'jobs/{JOB}/sources/{ATTEMPT}.jpg'
        self.assertEqual(source_key(JOB, valid), valid)
        for value in ['https://example.com/a.jpg', '../secret', valid.replace(JOB, 'c' * 32)]:
            with self.assertRaises(EngineError):
                source_key(JOB, value)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.repository, self.runtime, self.store = Mock(), Mock(), Mock()
        self.repository.claim.return_value = ({'id': JOB}, None)
        self.runtime.read.return_value = ({'id': JOB}, {'derived': b'image'})
        self.service = EngineService(self.repository, self.runtime, self.store)

    def test_completed_attempt_returns_saved_result_without_rereading_or_uploading(self):
        self.repository.claim.return_value = ({'id': JOB}, {'saved': True})
        self.assertEqual(self.service.infer(JOB, ATTEMPT), {'saved': True})
        self.runtime.read.assert_not_called()
        self.store.put.assert_not_called()
        self.repository.release.assert_not_called()

    def test_storage_is_reserved_before_upload_and_success_saved_before_response(self):
        events = []
        self.repository.reserve_artifacts.side_effect = lambda *a: events.append('reserve')
        self.store.put.side_effect = lambda *a: events.append('upload')
        self.repository.complete.side_effect = lambda *a: events.append('complete')
        self.repository.release.side_effect = lambda *a: events.append('release')
        self.assertEqual(self.service.infer(JOB, ATTEMPT), {'id': JOB})
        self.assertEqual(events, ['reserve', 'upload', 'complete', 'release'])

    def test_upload_failure_never_marks_complete_and_always_releases_lease(self):
        self.store.put.side_effect = OSError('secret-storage-diagnostic')
        with self.assertRaises(EngineError) as raised:
            self.service.infer(JOB, ATTEMPT)
        self.assertNotIn('secret', raised.exception.message)
        self.repository.complete.assert_not_called()
        self.repository.fail.assert_called_once()
        self.repository.release.assert_called_once()

    def test_over_quota_does_not_write_blobs(self):
        self.repository.reserve_artifacts.side_effect = EngineError('storage_quota', 'พื้นที่เต็ม', 409)
        with self.assertRaises(EngineError):
            self.service.infer(JOB, ATTEMPT)
        self.store.put.assert_not_called()

    def test_parallel_call_in_same_instance_is_rejected(self):
        self.service.guard.acquire()
        try:
            with self.assertRaises(EngineError) as raised:
                self.service.infer(JOB, ATTEMPT)
            self.assertEqual(raised.exception.code, 'busy')
            self.repository.claim.assert_not_called()
        finally:
            self.service.guard.release()


class BlobTests(unittest.TestCase):
    def test_chunked_private_download_without_size_remains_bounded(self):
        class Stream:
            metadata = Mock(size=None)

            def __iter__(self):
                yield b'abc'
                yield b'def'

        @contextmanager
        def stream(*args, **kwargs):
            yield Stream()

        with patch('vercel.blob.sync.stream_blob', stream):
            self.assertEqual(PrivateBlobStore().read('private-test', 6), b'abcdef')
            with self.assertRaises(EngineError) as raised:
                PrivateBlobStore().read('private-test', 5)
            self.assertEqual(raised.exception.code, 'file_too_large')


class ImageTests(unittest.TestCase):
    def encode(self, image, fmt):
        buffer = io.BytesIO()
        image.save(buffer, format=fmt)
        return buffer.getvalue()

    def test_jpeg_bytes_are_preserved_and_png_alpha_is_composited_white(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'presentation_build') as directory:
            root = Path(directory)
            content = self.encode(Image.new('RGB', (40, 60), 'white'), 'JPEG')
            self.assertEqual(prepare_image(content, root / 'A').read_bytes(), content)
            path = prepare_image(self.encode(Image.new('RGBA', (40, 60), (0, 0, 0, 0)), 'PNG'), root / 'B')
            with Image.open(path) as decoded:
                self.assertEqual(decoded.getpixel((1, 1)), (255, 255, 255))

    def test_bad_file_oversize_and_decoded_pixel_limit(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'presentation_build') as directory:
            root = Path(directory)
            for content in [b'not an image', b'x' * (20 * 1024 * 1024 + 1)]:
                with self.assertRaises(EngineError):
                    prepare_image(content, root / 'A')
            content = self.encode(Image.new('1', (5000, 5000)), 'PNG')
            with self.assertRaises(EngineError) as raised:
                prepare_image(content, root / 'A')
            self.assertEqual(raised.exception.code, 'too_many_pixels')

    def test_heic_decodes_to_png_without_silent_resizing(self):
        from pillow_heif import register_heif_opener
        register_heif_opener()
        content = self.encode(Image.new('RGB', (80, 120), 'white'), 'HEIF')
        with tempfile.TemporaryDirectory(dir=ROOT / 'presentation_build') as directory:
            path = prepare_image(content, Path(directory) / 'A')
            self.assertEqual(path.suffix, '.png')
            with Image.open(path) as decoded:
                self.assertEqual(decoded.size, (80, 120))


if __name__ == '__main__':
    unittest.main()

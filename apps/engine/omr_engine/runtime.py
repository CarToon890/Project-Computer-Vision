import hashlib
import io
import json
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageOps, UnidentifiedImageError

from .security import EngineError, source_key

MAX_IMAGE = 20 * 1024 * 1024
MAX_PIXELS = 24_000_000
MODEL_VERSION = 'confirmed-finetune-v3-risk-first'
MODEL_HASH = 'a5ddc52247efc28dcb8a806e6ffe3225d2f65ebb8a4a13740b30dad6062069b1'


def prepare_image(content, target):
    if not content or len(content) > MAX_IMAGE:
        raise EngineError('file_too_large', 'ภาพต้องมีขนาดไม่เกิน 20 MiB', 422)
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
        with Image.open(io.BytesIO(content)) as image:
            if image.width * image.height > MAX_PIXELS:
                raise EngineError('too_many_pixels', 'ภาพต้องมีความละเอียดไม่เกิน 24 ล้านพิกเซล', 422)
            fmt = image.format
            if fmt not in {'JPEG', 'MPO', 'PNG', 'HEIF', 'HEIC'}:
                raise EngineError('unsupported_image', 'รองรับ JPEG, PNG และ HEIC', 422)
            image.load()
            if fmt in {'HEIF', 'HEIC'} or 'A' in image.getbands():
                image = ImageOps.exif_transpose(image)
                if 'A' in image.getbands():
                    rgba = image.convert('RGBA')
                    background = Image.new('RGBA', rgba.size, 'white')
                    background.alpha_composite(rgba)
                    image = background.convert('RGB')
                target = target.with_suffix('.png')
                image.convert('RGB').save(target)
            else:
                target = target.with_suffix('.jpg' if fmt in {'JPEG', 'MPO'} else '.png')
                target.write_bytes(content)
    except EngineError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise EngineError('invalid_image', 'เปิดภาพไม่ได้ กรุณาเลือกภาพใหม่', 422) from None
    return target


class ModelRuntime:
    def __init__(self, store, manifest_key, manifest_hash):
        self.store, self.manifest_key, self.manifest_hash = store, manifest_key, manifest_hash
        self.guard = threading.Lock()
        self.directory = None
        self.model = None

    def load(self):
        with self.guard:
            if self.model is not None:
                return
            if self.manifest_key != 'system/v3/manifest.json' or len(self.manifest_hash) != 64:
                raise EngineError('model_not_configured', 'ยังไม่ได้ตั้งค่าโมเดล', 503)
            raw = self.store.read(self.manifest_key, 64 * 1024)
            if hashlib.sha256(raw).hexdigest() != self.manifest_hash:
                raise EngineError('model_integrity', 'ข้อมูลโมเดลไม่ตรงกับรุ่นที่กำหนด', 503)
            manifest = json.loads(raw)
            expected = {'config': ('system/v3/model_config.json', 'models/model_config.json', 64 * 1024),
                        'weights': ('system/v3/row_cnn.pt', 'models/row_cnn.pt', 2 * 1024 * 1024),
                        'references': ('system/v3/form_references.npz', 'data/metadata/form_references.npz', 16 * 1024 * 1024)}
            if manifest.get('version') != 1 or set(manifest.get('files', {})) != set(expected):
                raise EngineError('model_integrity', 'โครงสร้างโมเดลไม่ถูกต้อง', 503)
            directory = TemporaryDirectory(prefix='omr-model-')
            try:
                root = Path(directory.name)
                for name, (key, relative, limit) in expected.items():
                    info = manifest['files'][name]
                    if info.get('key') != key:
                        raise EngineError('model_integrity', 'ตำแหน่งโมเดลไม่ถูกต้อง', 503)
                    content = self.store.read(key, limit)
                    if hashlib.sha256(content).hexdigest() != info.get('sha256'):
                        raise EngineError('model_integrity', 'ไฟล์โมเดลตรวจสอบไม่ผ่าน', 503)
                    target = root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                from omr_model import CLASSES, load_trained_model
                import torch
                config = json.loads((root / 'models/model_config.json').read_text(encoding='utf-8'))
                if config.get('model_version') != MODEL_VERSION or config.get('weights_sha256') != MODEL_HASH or config.get('classes') != CLASSES:
                    raise EngineError('model_integrity', 'โมเดลไม่ใช่ CNN v3 ที่กำหนด', 503)
                torch.set_num_threads(2)
                model, device = load_trained_model(root / 'models/row_cnn.pt', 'cpu', MODEL_HASH)
                self.directory, self.root, self.config = directory, root, config
                self.model, self.device = model, device
            except Exception:
                directory.cleanup()
                raise

    def read(self, job, attempt_id):
        load_started = time.perf_counter()
        cold = self.model is None
        self.load()
        load_seconds = time.perf_counter() - load_started
        from omr_inference import read_role
        from omr_runtime import build_methods
        started = time.perf_counter()
        with TemporaryDirectory(prefix='omr-read-') as directory:
            folder = Path(directory)
            readings, errors, transfers = {}, {}, {}
            for role in ('A', 'B'):
                key = job['sources'].get(role)
                if key is None:
                    continue
                stage = time.perf_counter()
                content = self.store.read(source_key(job['id'], key), MAX_IMAGE)
                transfers[role] = {'download_seconds': time.perf_counter() - stage}
                stage = time.perf_counter()
                source = prepare_image(content, folder / (role + '_source'))
                transfers[role]['prepare_seconds'] = time.perf_counter() - stage
                try:
                    readings[role] = read_role(self.model, self.device, source, self.root, {}, folder, None, role)
                except (ValueError, OSError, RuntimeError):
                    readings[role] = None
                    errors[role] = 'จัดแนวภาพไม่ได้ กรุณาถ่ายให้เห็นจุดอ้างอิงครบและหลีกเลี่ยงเงา'
            if not any(readings.values()):
                raise EngineError('registration_failed', 'จัดแนวภาพไม่ได้ กรุณาถ่ายภาพใหม่ให้เห็นกระดาษครบ', 422)
            methods, pair = build_methods(readings.get('A'), readings.get('B'), self.config, job['id'])
            assets, files = {}, {}
            for role, reading in readings.items():
                if not reading:
                    continue
                assets[role] = {}
                for label, filename in [('input', f'{role}_input.jpg'), ('registered', f'{role}_registered.jpg'), ('rows', f'{role}_rows.jpg')]:
                    key = f'jobs/{job["id"]}/attempts/{attempt_id}/{filename}'
                    files[key] = (folder / filename).read_bytes()
                    assets[role][label] = key
            result = {'id': job['id'], 'model_version': MODEL_VERSION, 'model_sha256': MODEL_HASH,
                      'methods': methods, 'pair_check': pair, 'assets': assets, 'errors': errors,
                      'registration': {r: v['registration'] for r, v in readings.items() if v},
                      'elapsed_seconds': time.perf_counter() - started,
                      'timings': {'cold_start': cold, 'model_load_seconds': load_seconds,
                                  'transfers': transfers,
                                  'roles': {r: v.get('stage_timings', {}) for r,v in readings.items() if v}},
                      'canonical_labels_written': False, 'exam_key_required': False,
                      'preprocessing_version': self.config.get('preprocessing_version')}
            return result, files

from .security import EngineError


class PrivateBlobStore:
    """Use SDK-authenticated private object paths, never arbitrary URLs."""
    def read(self, key, limit):
        from vercel.blob.sync import stream_blob
        chunks, size = [], 0
        with stream_blob(key, access='private') as response:
            # Private Blob responses may use chunked transfer without a size.
            # The streamed byte count below remains the authoritative limit.
            if response.metadata.size is not None and response.metadata.size > limit:
                raise EngineError('file_too_large', 'ไฟล์มีขนาดเกินที่รองรับ', 422)
            for chunk in response:
                size += len(chunk)
                if size > limit:
                    raise EngineError('file_too_large', 'ไฟล์มีขนาดเกินที่รองรับ', 422)
                chunks.append(chunk)
        return b''.join(chunks)

    def put(self, key, body):
        from vercel.blob.sync import put_blob
        put_blob(key, body, access='private', content_type='image/jpeg',
                 add_random_suffix=False, allow_overwrite=False)

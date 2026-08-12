from pathlib import Path

from app.utils.file_utils import resolved_generated_root, resolved_upload_root


class LocalFileService:
    def _resolve(self, key):
        if not key or not str(key).strip():
            raise ValueError("Missing storage key")
        key = str(key).replace("\\", "/").lstrip("/")
        if ".." in Path(key).parts or key.startswith("/"):
            raise ValueError("Invalid storage key")
        root = resolved_upload_root()
        target = (root / key).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("Path traversal refused") from exc
        return target

    def put(self, data, key):
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = data if isinstance(data, (bytes, bytearray)) else bytes(data)
        path.write_bytes(payload)
        return str(path)

    def get(self, key):
        path = self._resolve(key)
        if not path.is_file():
            return None
        return path.read_bytes()

    def delete(self, key):
        path = self._resolve(key)
        if path.is_file():
            path.unlink()
            return True
        return False


file_service = LocalFileService()


class GeneratedFileService(LocalFileService):
    def _resolve(self, key):
        if not key or not str(key).strip():
            raise ValueError("Missing storage key")
        key = str(key).replace("\\", "/").lstrip("/")
        if ".." in Path(key).parts or key.startswith("/"):
            raise ValueError("Invalid storage key")
        root = resolved_generated_root()
        target = (root / key).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("Path traversal refused") from exc
        return target


generated_files = GeneratedFileService()

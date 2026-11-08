"""Private original-file storage; client filenames never become filesystem paths."""
import os
from pathlib import Path, PurePosixPath
from uuid import UUID

from src.observability import get_logger

log = get_logger(__name__)


class LocalFileStorage:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()

    def _path(self, key):
        relative = PurePosixPath(key)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise ValueError("Invalid storage key")
        path = (self.root / Path(*relative.parts)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Storage key escapes the upload directory")
        return path

    def save(self, document_id, extension, content):
        identifier = UUID(document_id).hex
        if extension not in {"pdf", "docx", "txt", "md", "csv"}:
            raise ValueError("Unsupported stored extension")
        key = f"{identifier}/original.{extension}"
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
        except BaseException:
            # Only remove a file opened by this call, never an existing original.
            if 'fd' in locals():
                path.unlink(missing_ok=True)
            raise
        log.info("document.original_saved", stored_document_id=identifier, size_bytes=len(content))
        return key

    def remove(self, key):
        path = self._path(key)
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass
        log.info("document.original_removed")

    def read(self, key):
        path = self._path(key)
        if path.stat().st_size > 50 * 1024 * 1024:
            raise ValueError("Stored original exceeds the upload limit")
        return path.read_bytes()

    def path_for_download(self, key):
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError("Original file unavailable")
        return path

    def save_once(self, document_id, extension, content):
        """Publish a complete file atomically; concurrent duplicate uploads reuse it."""
        from uuid import uuid4
        identifier = UUID(document_id).hex
        if extension not in {"pdf", "docx", "txt", "md", "csv"}:
            raise ValueError("Unsupported stored extension")
        key = f"{identifier}/original.{extension}"
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = destination.with_name(uuid4().hex + '.tmp')
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if destination.read_bytes() != content:
                    raise ValueError("Stored original does not match this upload")
            log.info('document.original_available', stored_document_id=identifier, size_bytes=len(content))
            return key
        finally:
            temporary.unlink(missing_ok=True)

"""Stage and publish DOSBox Pure's save archive for a single player profile."""

import errno
import hashlib
import msvcrt
import os
from pathlib import Path
import shutil
import tempfile
import zipfile
import zlib


class SaveProfileError(RuntimeError):
    """The local save profile could not be opened or updated safely."""


def _archive_digest(path, archive_path):
    try:
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").digest()
            with zipfile.ZipFile(source) as archive:
                for member in archive.infolist():
                    with archive.open(member) as entry:
                        while entry.read(1024 * 1024):
                            pass  # Consume the whole entry to check its CRC.
    except (EOFError, OSError, RuntimeError, UnicodeError, ValueError, zipfile.BadZipFile, zlib.error) as error:
        raise SaveProfileError(f"Invalid DOS save archive {archive_path}: {error}") from error
    return digest


class SaveProfile:
    """Hold the Windows profile lock from staging through publication."""

    def __init__(self, directory, scratch, archive_name):
        directory = directory.resolve()
        if directory == scratch.resolve():
            raise SaveProfileError("The save directory must differ from the run scratch directory")
        self.saved = directory / archive_name
        self.staged = scratch / archive_name
        self._original_digest = None
        try:
            directory.mkdir(parents=True, exist_ok=True)
            lock = (directory / "profile.lock").open("a+b")
        except OSError as error:
            raise SaveProfileError(f"Could not open save directory {directory}: {error}") from error
        try:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            lock.close()
            if error.errno in (errno.EACCES, errno.EAGAIN):
                raise SaveProfileError(f"Save directory {directory} is already in use by another SimAnt session") from error
            raise SaveProfileError(f"Could not lock save directory {directory}: {error}") from error

        self._lock = lock
        try:
            try:
                source = self.saved.open("rb")
            except FileNotFoundError:
                return
            with source, self.staged.open("xb") as target:
                shutil.copyfileobj(source, target)
            self._original_digest = _archive_digest(self.staged, self.saved)
        except OSError as error:
            self.close()
            raise SaveProfileError(f"Could not stage {self.saved} at {self.staged}: {error}") from error
        except BaseException:
            self.close()
            raise

    def commit(self):
        if self._lock is None:
            raise SaveProfileError("The save directory is closed")
        pending = None
        try:
            try:
                source = self.staged.open("rb")
            except FileNotFoundError:
                return
            with source:
                if hashlib.file_digest(source, "sha256").digest() == self._original_digest:
                    return
                source.seek(0)
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=self.saved.parent, prefix="save-", suffix=".tmp", delete=False
                ) as target:
                    pending = Path(target.name)
                    shutil.copyfileobj(source, target)
                    target.flush()
                    os.fsync(target.fileno())
            digest = _archive_digest(pending, self.staged)
            os.replace(pending, self.saved)
            self._original_digest = digest
        except BaseException as error:
            failure = error
            if isinstance(error, OSError):
                failure = SaveProfileError(f"Could not update {self.saved} from {self.staged}: {error}")
            if pending is not None:
                try:
                    pending.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    failure.add_note(f"Could not remove temporary save {pending}: {cleanup_error}")
            if failure is error:
                raise
            raise failure from error

    def close(self):
        lock, self._lock = self._lock, None
        if lock is not None:
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                lock.close()

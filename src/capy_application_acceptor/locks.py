"""Process-owned, nonblocking identity locks. Lock files are never unlinked."""
import os
from pathlib import Path


class IdentityLock:
    def __init__(self, path: Path):
        self.path = path
        self.file = None

    def acquire(self):
        if self.path.is_symlink():
            raise OSError("unsafe lock")
        self.file = self.path.open("a+b")
        if self.file.seek(0, os.SEEK_END) == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, PermissionError, OSError):
            self.file.close()
            self.file = None
            return False
        return True

    def close(self):
        if self.file is not None:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()
            self.file = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

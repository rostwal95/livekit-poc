"""Cooperative local SQLite worker ownership shared by worker and cutover."""

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .execution_models import ExecutionError, StorageUnavailable, UnsupportedOperation

WORKER_LOCK_SUFFIX = ".worker.lock"


class WorkerBusy(ExecutionError):
    """Another cooperating worker owns this database's inquiry execution slot."""

    code = "capacity_exhausted"


class WorkerLockUnavailable(StorageUnavailable):
    """A safe private local worker lock could not be obtained."""


@contextmanager
def sqlite_worker_lock(path: Path) -> Iterator[None]:
    if os.name != "posix":
        raise UnsupportedOperation("The local inquiry worker requires POSIX file locking")
    import fcntl

    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as error:
        raise WorkerLockUnavailable("The worker lock is unavailable") from error
    try:
        try:
            information = os.fstat(descriptor)
            if (
                not stat.S_ISREG(information.st_mode)
                or information.st_mode & 0o077
                or information.st_uid != os.getuid()
                or information.st_nlink != 1
            ):
                raise WorkerLockUnavailable("The worker lock is not a private regular file")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise WorkerBusy("A cooperating inquiry worker is already active") from error
        except OSError as error:
            raise WorkerLockUnavailable("The worker lock is unavailable") from error
        yield
    finally:
        # Closing this owned descriptor releases flock, including after failure.
        os.close(descriptor)

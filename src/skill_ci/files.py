from __future__ import annotations

import contextlib
import os
import stat
import tempfile
from pathlib import Path

NOT_REGULAR = "not a regular file"


def read_regular_text(path: Path) -> str:
    # Opening a FIFO without O_NONBLOCK would wait for a writer.
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        # A socket, or a directory without read permission, cannot be opened at all.
        if not stat.S_ISREG(os.stat(path).st_mode):
            raise ValueError(NOT_REGULAR) from None
        raise
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError(NOT_REGULAR)
    with open(descriptor, encoding="utf-8") as file:
        return file.read()


def atomic_write(path: Path, data: bytes) -> None:
    target = Path(os.path.realpath(path))
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f"{target.name}.", delete_on_close=False) as partial:
        with contextlib.suppress(FileNotFoundError):
            os.fchmod(partial.fileno(), stat.S_IMODE(target.stat().st_mode))
        partial.write(data)
        partial.flush()
        os.fsync(partial.fileno())
        partial.close()
        os.replace(partial.name, target)

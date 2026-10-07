from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from types import FrameType

STOPPING = frozenset(
    getattr(signal, name)
    for name in (
        "SIGINT", "SIGTERM", "SIGHUP", "SIGQUIT", "SIGUSR1", "SIGUSR2", "SIGALRM", "SIGPIPE",
        "SIGABRT", "SIGVTALRM", "SIGPROF", "SIGXCPU", "SIGPOLL", "SIGPWR",
    )
    if hasattr(signal, name)
)
GRACE = 3.0
HAND_OFF_GRACE = GRACE + 2.0
TICK = 0.05


class Stopped(BaseException):
    def __init__(self, number: int) -> None:
        super().__init__(signal.Signals(number).name)
        self.status = 128 + number


def run(
    argv: Sequence[str],
    *,
    capture: bool = False,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    timeout: float | None = None,
    grace: float = GRACE,
) -> subprocess.CompletedProcess[bytes]:
    if not capture:
        sys.stdout.flush()
        sys.stderr.flush()
    piped = subprocess.PIPE if capture else None
    with stopping_signals() as received:
        child = subprocess.Popen(
            argv,
            env=env,
            cwd=cwd,
            stdin=subprocess.DEVNULL if capture else None,
            stdout=piped,
            stderr=piped,
            start_new_session=True,
        )
        try:
            output = wait(child, received, timeout=timeout, grace=grace)
        finally:
            for pipe in (child.stdout, child.stderr):
                if pipe is not None:
                    pipe.close()
        if output is None:
            raise subprocess.TimeoutExpired(argv, timeout)
    return subprocess.CompletedProcess(argv, child.returncode, *output)


@contextlib.contextmanager
def stopping_signals() -> Iterator[list[int]]:
    received: list[int] = []

    def record(number: int, frame: FrameType | None) -> None:
        # CPython can run a handler at the start of the handler it is already running, before that one records its
        # signal. The interrupted handler holds the first signal.
        if not received and (frame is None or frame.f_code is not record.__code__):
            received.append(number)

    # A signal ignored at startup, as under nohup or in a background job, stays ignored here and in the child. Python
    # ignores SIGPIPE itself at startup, so its SIG_IGN says nothing about how skill-ci was started.
    previous = {
        number: signal.signal(number, record)
        for number in STOPPING
        if number == signal.SIGPIPE or signal.getsignal(number) != signal.SIG_IGN
    }
    try:
        yield received
    finally:
        # Blocking runs every handler that has already fired.
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, STOPPING)
        for number, handler in previous.items():
            # Python resets its own handlers while it shuts down, but not SIG_IGN. signal.signal reports a handler
            # installed outside Python, such as faulthandler's, as None.
            signal.signal(number, signal.SIG_IGN if received else signal.SIG_DFL if handler is None else handler)
        signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        if received:
            raise Stopped(received[0])


def wait(
    child: subprocess.Popen[bytes], received: list[int], *, timeout: float | None, grace: float
) -> tuple[bytes | None, bytes | None] | None:
    started = time.monotonic()
    interrupted = None
    while True:
        now = time.monotonic()
        if interrupted is None and (received or (timeout is not None and now - started >= timeout)):
            # The harness stops the agents it started only on KeyboardInterrupt. uv 0.12.7 passes a SIGINT sent to its
            # pid on to the pinned skill-ci and waits for it, and several STOPPING signals make uv exit at once when they
            # reach its whole group. Python ignores SIGPIPE, so a SIGPIPE that uv passes on ends nothing.
            child.send_signal(signal.SIGINT)
            interrupted = now
        if interrupted is not None and now - interrupted >= grace:
            kill_group(child)
        try:
            if interrupted is None and child.stdout is not None:
                return child.communicate(timeout=TICK)
            child.wait(timeout=TICK)
        except subprocess.TimeoutExpired:
            continue
        if interrupted is None:
            return None, None
        # git dies of a signal at once and leaves its ssh transport running.
        kill_group(child)
        return None


def kill_group(child: subprocess.Popen[bytes]) -> None:
    # On macOS, killpg raises PermissionError on a group that holds only an unreaped zombie.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(child.pid, signal.SIGKILL)

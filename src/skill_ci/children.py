from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

# Every signal that stops skill-ci while a child runs. The child's leader gets SIGINT in its place, because the harness
# stops the agents it started only on KeyboardInterrupt, uv 0.12.7 passes a SIGINT sent to its pid on to the pinned
# skill-ci and waits for it, and Python and uv ignore SIGPIPE. Several of these make uv exit at once when they reach its
# whole group. SIGWINCH and SIGINFO keep their default action, which ends no process.
STOPPING = frozenset(
    getattr(signal, name)
    for name in (
        "SIGINT", "SIGTERM", "SIGHUP", "SIGQUIT", "SIGUSR1", "SIGUSR2", "SIGALRM", "SIGPIPE",
        "SIGABRT", "SIGVTALRM", "SIGPROF", "SIGXCPU", "SIGPOLL", "SIGPWR",
    )
    if hasattr(signal, name)
)
# Seconds a child gets to exit after its SIGINT before its process group is killed.
GRACE = 3.0
# A pinned skill-ci behind uv spends up to GRACE stopping its own child, so the hand-off waits longer.
HAND_OFF_GRACE = GRACE + 2.0
TICK = 0.05


class Stopped(BaseException):
    """A stopping signal ended the run. Neither an Exception nor a SystemExit, so no check turns it into its own status."""

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
    """Run argv in a session of its own, so that a stopping signal to skill-ci stops it and everything it started.

    capture=False shares skill-ci's stdin, stdout and stderr; capture=True gives the child /dev/null for stdin and
    returns its output. Raises Stopped once the child and its group are gone when a stopping signal arrived at any point
    in the call, even before the child existed, and subprocess.TimeoutExpired after `timeout` seconds.
    """
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

    def record(number: int, _frame: object) -> None:
        if not received:
            received.append(number)

    previous = {number: signal.signal(number, record) for number in STOPPING}
    try:
        yield received
    finally:
        # Blocking runs every handler that has already fired, so no signal lands between this check and the restore.
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, STOPPING)
        for number, handler in previous.items():
            # After a stop, the rest of a burst is ignored until skill-ci has exited. Python resets its own handlers
            # while it shuts down, but not SIG_IGN. signal.signal reports a handler installed outside Python, such as
            # faulthandler's, as None.
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
        # The leader is gone, but what it started in its group, such as git's ssh transport, may still run.
        kill_group(child)
        return None


def kill_group(child: subprocess.Popen[bytes]) -> None:
    # On macOS, killpg raises PermissionError on a group that holds only an unreaped zombie.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(child.pid, signal.SIGKILL)

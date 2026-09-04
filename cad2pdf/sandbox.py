"""
Run one drawing's work in a child process that can be stopped.

Converting a large drawing can want a gigabyte. On a 512 MB instance the
kernel resolves that by killing the gunicorn worker, and a killed worker
cannot apologise: the browser gets an empty body, `response.json()`
throws, and a convert request simply hangs until the user gives up. The
server has to be the one that notices first.

So the work happens in a forked child while the parent watches its
resident memory and the clock. If the child goes over either budget the
parent stops it and raises, and because the parent never did the
allocating it is still alive to send a real answer back.

RSS is watched rather than an RLIMIT_AS cap because numpy and matplotlib
reserve address space far beyond what they touch, so an address-space cap
either fires on drawings that would have been fine or has to be set so
loosely that it never fires at all. Resident memory is the number the
kernel actually kills on.
"""

from __future__ import annotations

import multiprocessing
import os
import time
import traceback
from typing import Any, Callable

from .hostlimits import current_rss_mb

# How long the parent waits on the child's pipe before looking at it again.
# Short enough that a fast allocation is caught before the kernel gets
# there, long enough not to spend the CPU the conversion needs - which on a
# 0.1 CPU instance is most of the reason the work is slow in the first
# place. Reading one small /proc file this often costs nothing measurable.
_POLL_SECONDS = 0.1


class WorkloadStopped(Exception):
    """
    The child was stopped rather than allowed to take the server down.

    `kind` is "memory" or "time"; `detail` carries the numbers so the
    caller can say what happened rather than just that it failed.
    """

    def __init__(self, message: str, *, kind: str, **detail: Any):
        super().__init__(message)
        self.kind = kind
        self.detail = detail


class ChildFailed(Exception):
    """The work raised inside the child. Carries the original text."""

    def __init__(self, message: str, *, exc_type: str = ""):
        super().__init__(message)
        self.exc_type = exc_type


def _child_main(conn, func, args, kwargs):
    try:
        conn.send(("ok", func(*args, **kwargs)))
    except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
        # Pickling an arbitrary exception across the pipe is not reliable
        # (some carry file handles or C state), so send its text instead.
        conn.send(("error", type(exc).__name__, str(exc) or traceback.format_exc()))
    finally:
        conn.close()


def run_guarded(
    func: Callable,
    args: tuple = (),
    kwargs: dict = None,
    *,
    memory_mb: float = None,
    timeout: float = None,
):
    """
    Run func in a child process, watching its memory and the clock.

    Returns whatever func returned. Raises WorkloadStopped if the child
    was stopped, or ChildFailed if the work itself raised. With no budgets
    given this is just a fork that reports errors.

    func and its result have to survive pickling, so the caller writes big
    output (a PDF) to a file and returns only what describes it.
    """
    ctx = multiprocessing.get_context("fork")
    receiver, sender = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_child_main, args=(sender, func, args, kwargs or {}), daemon=True
    )
    proc.start()
    # The parent holds no write end, so the pipe reports EOF when the child
    # exits without sending - which is how a kernel kill is noticed.
    sender.close()

    started = time.monotonic()
    peak_mb = 0.0
    payload = None
    stopped = None

    try:
        while True:
            # Budgets are checked before waiting on the pipe, not after. The
            # other way round, a child that finished inside one poll interval
            # handed back its result without ever having been measured - so
            # whether an oversized drawing was caught came down to how fast
            # the machine happened to be.
            rss = current_rss_mb(proc.pid)
            if rss is not None:
                peak_mb = max(peak_mb, rss)
                if memory_mb is not None and rss > memory_mb:
                    stopped = WorkloadStopped(
                        "ran out of memory", kind="memory",
                        peak_mb=round(rss), budget_mb=round(memory_mb),
                    )
                    break

            elapsed = time.monotonic() - started
            if timeout is not None and elapsed > timeout:
                stopped = WorkloadStopped(
                    "took too long", kind="time",
                    seconds=round(elapsed), budget_seconds=round(timeout),
                )
                break

            if receiver.poll(_POLL_SECONDS):
                try:
                    payload = receiver.recv()
                except EOFError:
                    payload = None
                break

            if not proc.is_alive() and not receiver.poll(0):
                break
    finally:
        if stopped is not None:
            _terminate(proc)
        proc.join(timeout=10)
        receiver.close()

    if stopped is not None:
        raise stopped

    if payload is None:
        # No result and no error: the child died without saying anything,
        # which on this app means the kernel got to it first.
        raise WorkloadStopped(
            "ran out of memory", kind="memory",
            peak_mb=round(peak_mb) or None, budget_mb=(
                round(memory_mb) if memory_mb is not None else None
            ),
            exitcode=proc.exitcode,
        )

    if payload[0] == "error":
        raise ChildFailed(payload[2], exc_type=payload[1])
    return payload[1]


def _terminate(proc) -> None:
    """Stop the child, without waiting on a process too busy to notice."""
    if not proc.is_alive():
        return
    proc.terminate()
    proc.join(timeout=3)
    if proc.is_alive():
        proc.kill()
        proc.join(timeout=3)


def available() -> bool:
    """
    Whether guarded running is usable here.

    Needs fork: a spawn-based child would re-import the app and re-pay the
    import cost on every request, which on a small instance is most of the
    request. Callers fall back to running in-process.
    """
    return "fork" in multiprocessing.get_all_start_methods() and hasattr(
        os, "fork"
    )

"""
How much memory this process is actually allowed to use.

The app's usual home is a 512 MB Render instance, and a big drawing can
want more than that all by itself. Without a budget the only thing that
notices is the kernel, which kills the worker mid-request: the browser
gets an empty response and the user gets a spinner that never stops. So
the budget has to be known up front, and it has to come from the
container rather than from the host, because a 512 MB container on a
64 GB machine still only gets 512 MB.

cgroup v2 and v1 report it in different files, and an unlimited cgroup
reports a number close to 2**63 rather than saying so.
"""

from __future__ import annotations

import os

# A cgroup with no limit reports something near 2**63. Anything above this
# is "unlimited" rather than a real allowance.
_NO_LIMIT_THRESHOLD_BYTES = 1 << 53

# Left for the interpreter, the web server and whatever else is resident
# while a drawing is being converted. Without it the budget would be spent
# right up to the ceiling and the kernel would still do the killing.
_HEADROOM_MB = 64

_CGROUP_V2 = "/sys/fs/cgroup/memory.max"
_CGROUP_V1 = "/sys/fs/cgroup/memory/memory.limit_in_bytes"


def _read_int(path: str):
    try:
        with open(path, "r", encoding="ascii") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def container_memory_mb():
    """
    Total memory this container may use, or None if nothing limits it.

    Checked before /proc/meminfo on purpose: inside a container meminfo
    describes the whole machine, which is exactly the wrong number.
    """
    for path in (_CGROUP_V2, _CGROUP_V1):
        value = _read_int(path)
        if value is not None and 0 < value < _NO_LIMIT_THRESHOLD_BYTES:
            return value / (1024 * 1024)
    return None


def total_memory_mb():
    """Machine memory, used only when no container limit applies."""
    try:
        with open("/proc/meminfo", "r", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def current_rss_mb(pid: int = None):
    """Resident memory of a process, or None if it cannot be read."""
    target = "self" if pid is None else str(pid)
    try:
        with open(f"/proc/{target}/status", "r", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def memory_budget_mb(default_mb: float = 1024.0):
    """
    How much a single conversion may use before it is stopped.

    What is left of the container's allowance once the resident process
    and a headroom margin are taken out. CAD2PDF_MEMORY_BUDGET_MB
    overrides the whole calculation, and 0 turns the limit off for anyone
    running somewhere the budget does more harm than good.
    """
    override = os.environ.get("CAD2PDF_MEMORY_BUDGET_MB")
    if override:
        try:
            value = float(override)
        except ValueError:
            pass
        else:
            return None if value <= 0 else value

    limit = container_memory_mb()
    if limit is None:
        limit = total_memory_mb()
        if limit is None:
            return default_mb
        # Nothing is containing us, so the machine's memory is shared with
        # everything else on it. Claim a share rather than all of it.
        limit = limit / 2

    resident = current_rss_mb() or 0.0
    budget = limit - resident - _HEADROOM_MB
    # A budget this small cannot convert anything at all; a caller that
    # enforced it would reject every drawing, which is worse than letting
    # the request run and fail honestly.
    return budget if budget >= 64 else None

"""
Where-did-this-come-from information for the /status dashboard.

When the app runs on Render, Render injects environment variables that
identify the exact GitHub commit it built from. That is the whole point of
the dashboard: you push to GitHub, Render redeploys, and /status tells you
whether the running app is actually the commit you just pushed - without
digging through the Render logs.

Everything here degrades gracefully: run it on a laptop, or on any other
host, and you get the same shape back with the unknown fields set to None.
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
from dataclasses import asdict, dataclass
from importlib import metadata
from typing import Optional

# Process start time, so the dashboard can show how long this instance has
# been up. On Render's free plan the instance sleeps when idle, so a small
# uptime usually means "it just woke up", not "it crashed".
_STARTED_AT = time.time()


@dataclass(frozen=True)
class BuildInfo:
    host: str                       # "Render", "Fly.io", "local", ...
    service_name: Optional[str]
    region: Optional[str]
    instance_id: Optional[str]
    repo_slug: Optional[str]        # "owner/repo"
    branch: Optional[str]
    commit: Optional[str]           # full SHA
    repo_url: Optional[str]
    branch_url: Optional[str]
    commit_url: Optional[str]

    @property
    def short_commit(self) -> Optional[str]:
        return self.commit[:7] if self.commit else None


def _env(name: str) -> Optional[str]:
    value = (os.environ.get(name) or "").strip()
    return value or None


def _local_git_commit() -> Optional[str]:
    """Best-effort commit for local runs. Never raises, never blocks long."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip()
    return sha or None


def _local_git_branch() -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    name = out.stdout.strip()
    return name if name and name != "HEAD" else None


def get_build_info() -> BuildInfo:
    if _env("RENDER"):
        host = "Render"
    elif _env("FLY_APP_NAME"):
        host = "Fly.io"
    else:
        host = "local"

    # CAD2PDF_* overrides let any other Docker host feed the dashboard the
    # same information (pass them as build args or env vars).
    repo_slug = _env("RENDER_GIT_REPO_SLUG") or _env("CAD2PDF_GIT_REPO")
    branch = _env("RENDER_GIT_BRANCH") or _env("CAD2PDF_GIT_BRANCH")
    commit = _env("RENDER_GIT_COMMIT") or _env("CAD2PDF_GIT_COMMIT")

    if host == "local":
        commit = commit or _local_git_commit()
        branch = branch or _local_git_branch()

    repo_url = f"https://github.com/{repo_slug}" if repo_slug else None
    branch_url = (
        f"{repo_url}/tree/{branch}" if repo_url and branch else None
    )
    commit_url = (
        f"{repo_url}/commit/{commit}" if repo_url and commit else None
    )

    return BuildInfo(
        host=host,
        service_name=_env("RENDER_SERVICE_NAME") or _env("FLY_APP_NAME"),
        region=_env("RENDER_REGION") or _env("FLY_REGION"),
        instance_id=_env("RENDER_INSTANCE_ID") or _env("FLY_ALLOC_ID"),
        repo_slug=repo_slug,
        branch=branch,
        commit=commit,
        repo_url=repo_url,
        branch_url=branch_url,
        commit_url=commit_url,
    )


def uptime_seconds() -> float:
    return time.time() - _STARTED_AT


def format_uptime(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def runtime_versions() -> dict:
    """
    Versions of the pieces that actually decide whether a DXF converts.

    Read from package metadata rather than each module's __version__ - Flask
    deprecated its attribute, and metadata works for every package anyway.
    """
    versions = {"python": platform.python_version()}
    for name in ("ezdxf", "matplotlib", "flask", "gunicorn"):
        try:
            versions[name] = metadata.version(name)
        except Exception:  # noqa: BLE001 - the dashboard must never 500
            versions[name] = "not installed"
    return versions


def as_dict(info: BuildInfo) -> dict:
    data = asdict(info)
    data["short_commit"] = info.short_commit
    return data

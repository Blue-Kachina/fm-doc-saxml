"""Self-version detection for fm-saxml.

When a user looks at generated documentation they should be able to tell which
version of this tool produced it — ideally specific enough to map back to a
single git commit.

Strategy (in order of preference):

1. **Local git HEAD.** If the package runs from its own checkout (editable
   installs from a clone, or tests run from a checkout), read the HEAD commit
   hash and commit timestamp via ``git`` and report those. A git repository
   that merely contains the install (a ``.venv`` inside some other project)
   doesn't count: its HEAD says nothing about this package.
2. **Build info.** A wheel built from a checkout carries ``_build_info.py``
   (written by ``hatch_build.py``) with the commit it was built from.
3. **Package version fallback.** Otherwise (e.g. a wheel built from an
   sdist), fall back to the ``__version__`` constant.

The detection is best-effort and never raises — if anything fails (no git
binary, timeout, permission error, detached repo, etc.) it returns a
``source="package"`` result so the renderer always has something to show.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TypedDict

from . import __version__


class VersionInfo(TypedDict):
    version: str
    commit_hash: Optional[str]
    commit_short: Optional[str]
    commit_date_iso: Optional[str]
    commit_date_display: Optional[str]
    source: str  # "git", "build" or "package"


REPO_URL = "https://dev.azure.com/directimpact/SWAT/_git/fm-saxml-converter"
REPO_LABEL = "fm-saxml-converter"
PACKAGE_NAME = "fm-saxml-converter"
_GIT_TIMEOUT_SECONDS = 2.0
_MAX_PARENT_WALK = 8


def get_self_version_info() -> VersionInfo:
    """Return identification info for the currently-running install."""
    info: VersionInfo = {
        "version": __version__,
        "commit_hash": None,
        "commit_short": None,
        "commit_date_iso": None,
        "commit_date_display": None,
        "source": "package",
    }

    commit_hash = commit_iso = None
    repo_root = _find_git_root(Path(__file__).resolve().parent)
    if repo_root is not None and _is_own_checkout(repo_root):
        commit_hash = _git(["rev-parse", "HEAD"], repo_root)
        if commit_hash:
            commit_iso = _git(["log", "-1", "--format=%cI"], repo_root)
            info["source"] = "git"
    if not commit_hash:
        commit_hash, commit_iso = _build_info()
        if not commit_hash:
            return info
        info["source"] = "build"

    info["commit_hash"] = commit_hash
    info["commit_short"] = commit_hash[:7]
    info["commit_date_iso"] = commit_iso
    info["commit_date_display"] = _format_iso_date(commit_iso)
    return info


def get_self_updated_at_display() -> str:
    """Return a single-line human-readable identifier for templates.

    Examples:
        - ``"2026-05-04 12:30 UTC (commit abc1234)"`` — git available
        - ``"commit abc1234"``                       — git but no commit date
        - ``"v0.1.0"``                                — fell back to package
    """
    info = get_self_version_info()
    if info["source"] in ("git", "build"):
        if info["commit_date_display"] and info["commit_short"]:
            return f"{info['commit_date_display']} (commit {info['commit_short']})"
        if info["commit_short"]:
            return f"commit {info['commit_short']}"
    return f"v{info['version']}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_git_root(start: Path) -> Optional[Path]:
    """Walk upward looking for a ``.git`` entry (file or directory)."""
    cur = start
    for _ in range(_MAX_PARENT_WALK):
        if (cur / ".git").exists():
            return cur
        parent = cur.parent
        if parent == cur:
            return None
        cur = parent
    return None


def _is_own_checkout(root: Path) -> bool:
    """True when ``root`` is a checkout of this package: its pyproject.toml names it."""
    try:
        text = (root / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return False
    return f'name = "{PACKAGE_NAME}"' in text


def _build_info() -> tuple[Optional[str], Optional[str]]:
    """The commit (and its date) a wheel was built from, if the build recorded it."""
    try:
        from . import _build_info  # type: ignore[attr-defined]
    except ImportError:
        return None, None
    return getattr(_build_info, "COMMIT", None) or None, getattr(_build_info, "COMMIT_DATE", None) or None


def _git(args: list[str], cwd: Path) -> Optional[str]:
    """Run ``git <args>`` quietly. Returns stripped stdout or None on any failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    out = (result.stdout or "").strip()
    return out or None


def _format_iso_date(iso: Optional[str]) -> Optional[str]:
    """Convert a git ISO-8601 timestamp to ``YYYY-MM-DD HH:MM UTC``."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")

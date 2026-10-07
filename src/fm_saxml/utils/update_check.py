"""Best-effort "a newer version is available" notice.

Design rules: never block, never fail, never nag.

* Runs in a background thread; the result is only shown if it arrives in time.
* Hits PyPI at most once every 24 hours (result is cached).
* Silent when output isn't a terminal, in CI, or when
  ``FM_SAXML_NO_UPDATE_CHECK`` is set.
* Every error (offline, proxy, corrupt cache, ...) is swallowed.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

PACKAGE_NAME = "fm-saxml-converter"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
NETWORK_TIMEOUT_SECONDS = 2.0


def is_disabled() -> bool:
    """True when no check should happen (opt-out, CI, or non-interactive output)."""
    if os.environ.get("FM_SAXML_NO_UPDATE_CHECK") or os.environ.get("CI"):
        return True
    try:
        return not sys.stderr.isatty()
    except (AttributeError, ValueError):
        return True


def parse_version(text: str) -> tuple[int, ...] | None:
    """Parse ``1.2.3`` into ``(1, 2, 3)``. Pre-releases (``1.2.3rc1``) return None."""
    try:
        return tuple(int(part) for part in text.strip().split("."))
    except ValueError:
        return None


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


def cache_file() -> Path:
    """Per-user cache location for each platform."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "fm-saxml" / "update-check.json"


def fetch_latest_version() -> str | None:
    import urllib.request

    request = urllib.request.Request(PYPI_URL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT_SECONDS) as resp:  # noqa: S310
        return json.load(resp)["info"]["version"]


def latest_version(
    *,
    fetch: Callable[[], str | None] = fetch_latest_version,
    cache: Path | None = None,
    now: Callable[[], float] = time.time,
) -> str | None:
    """Latest released version, using a 24h cache. Returns None on any failure."""
    cache = cache or cache_file()
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if now() - float(data["checked_at"]) < CHECK_INTERVAL_SECONDS:
            return data.get("latest")
    except (OSError, ValueError, KeyError, TypeError):
        pass

    try:
        latest = fetch()
    except Exception:  # noqa: BLE001 - offline, DNS, proxy, bad JSON, ...
        latest = None

    # Cache failures too, so an offline machine doesn't retry on every run.
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"checked_at": now(), "latest": latest}), encoding="utf-8")
    except OSError:
        pass
    return latest


def upgrade_hint(repo_url: str) -> str:
    """How to upgrade, based on how this copy was installed."""
    if getattr(sys, "frozen", False):
        return f"Download the new executable from {repo_url}/releases"
    prefix = sys.prefix.replace("\\", "/").lower()
    if "/pipx/" in prefix:
        return f"pipx upgrade {PACKAGE_NAME}"
    if "/uv/tools/" in prefix:
        return f"uv tool upgrade {PACKAGE_NAME}"
    return f"pip install -U {PACKAGE_NAME}"


class UpdateNotifier:
    """Runs the check in a daemon thread; ``message()`` never waits long."""

    def __init__(self, current: str, repo_url: str, **latest_kwargs) -> None:
        self._current = current
        self._repo_url = repo_url
        self._latest: str | None = None
        self._thread = threading.Thread(
            target=self._run, args=(latest_kwargs,), daemon=True, name="fm-saxml-update-check"
        )
        self._thread.start()

    def _run(self, latest_kwargs: dict) -> None:
        try:
            self._latest = latest_version(**latest_kwargs)
        except Exception:  # noqa: BLE001
            self._latest = None

    def message(self, timeout: float = 0.5) -> str | None:
        self._thread.join(timeout)
        if self._latest and is_newer(self._latest, self._current):
            return (
                f"A newer fm-saxml is available ({self._latest}; you have {self._current}). "
                f"{upgrade_hint(self._repo_url)}"
            )
        return None


def start(current: str, repo_url: str) -> UpdateNotifier | None:
    """Begin a background check, or return None if checks are disabled."""
    if is_disabled():
        return None
    return UpdateNotifier(current, repo_url)

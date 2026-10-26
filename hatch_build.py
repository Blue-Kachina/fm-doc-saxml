"""Hatch build hook: record the git commit a wheel is built from.

A wheel installed into site-packages has no git checkout to ask, so generated
docs could only say ``v<version>``, which several commits can share. When the
wheel is built from a checkout, this hook adds ``fm_saxml/_build_info.py`` with
the HEAD commit and its date; ``fm_saxml.version`` reads it. Built without git
(e.g. from an sdist), the wheel gets no build info and the docs show the version.
The file is written to a temporary folder, never into the source tree.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


def _git(args: list[str], cwd: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (r.stdout or "").strip()
    return out if r.returncode == 0 and out else None


class BuildInfoHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        self._tmp = None
        # An editable install runs from the checkout, where fm_saxml.version asks git directly
        if version == "editable" or not (Path(self.root) / ".git").exists():
            return
        commit = _git(["rev-parse", "HEAD"], self.root)
        if not commit:
            return
        date = _git(["log", "-1", "--format=%cI"], self.root)
        self._tmp = tempfile.mkdtemp(prefix="fm_saxml_build_")
        info = Path(self._tmp) / "_build_info.py"
        info.write_text('"""Written by hatch_build.py when this wheel was built."""\n\n'
                        f"COMMIT = {commit!r}\nCOMMIT_DATE = {date!r}\n", encoding="utf-8", newline="\n")
        build_data["force_include"][str(info)] = "fm_saxml/_build_info.py"

    def finalize(self, version: str, build_data: dict, artifact_path: str) -> None:
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)

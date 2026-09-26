"""Shared helpers for the Funes hexagon tools.

`.cli` is registered as hexagon's `custom_tools_dir`, so it sits on `sys.path`
and every tool package can `from _lib import ...`.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from hexagon.support.output.printer import log

# .cli/_lib.py -> .cli -> repo root
ROOT = Path(__file__).resolve().parent.parent


def step(title: str) -> None:
    """Announce a step, bold and spaced, the way the old shell scripts did."""
    log.info(f"[b]== {title}", gap_start=1)


def run(
    *cmd: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
    quiet: bool = False,
    sudo: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a command from the repo root, failing the tool on a non-zero exit."""
    argv = ["sudo", *cmd] if sudo and os.geteuid() != 0 else list(cmd)
    result = subprocess.run(
        argv,
        cwd=str(cwd or ROOT),
        env={**os.environ, **env} if env else None,
        capture_output=quiet,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        if quiet and result.stderr:
            sys.stderr.write(result.stderr)
        log.error(f"command failed ({result.returncode}): {' '.join(argv)}")
        raise SystemExit(result.returncode)
    return result


def require(*binaries: str, hint: str = "") -> None:
    """Abort with a readable message when a build/dev dependency is missing."""
    missing = [b for b in binaries if not shutil.which(b)]
    if not missing:
        return
    log.error(f"missing required command(s): {', '.join(missing)}")
    if hint:
        log.info(hint)
    raise SystemExit(1)


def project_version() -> str:
    """The version declared in meson.build."""
    for line in (ROOT / "meson.build").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("version:"):
            return stripped.split("'")[1]
    log.error("no version found in meson.build")
    raise SystemExit(1)

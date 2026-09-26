"""fns install-local - install the working tree over the system copy and restart Funes.

Mirrors the xapp-project dev loop (see clockenstein's test-clocks).
"""

import subprocess
from typing import Any

from hexagon.domain.env import Env
from hexagon.domain.tool import ActionTool
from hexagon.support.output.printer import log

from _lib import ROOT, project_version, require, run, step

APP_DIR = "/usr/share/funes/app"
PYLIB_DIR = "/usr/lib/python3/dist-packages/funes"


def main(
    _tool: ActionTool,
    _env: Env | None = None,
    _env_args: Any = None,
    _cli_args: Any = None,
) -> None:
    require("glib-compile-schemas")
    version = project_version()

    step(f"install {version} over the system copy")
    run("rm", "-rf", APP_DIR, sudo=True)
    run("mkdir", "-p", "/usr/share/funes", sudo=True)
    run("cp", "-R", str(ROOT / "app"), "/usr/share/funes/", sudo=True)

    run("rm", "-rf", PYLIB_DIR, sudo=True)
    run("cp", "-R", str(ROOT / "funes"), "/usr/lib/python3/dist-packages/", sudo=True)
    run(
        "sed",
        "-i",
        f"s/__PROJECT_VERSION__/{version}/g",
        f"{PYLIB_DIR}/__init__.py",
        sudo=True,
    )

    run(
        "glib-compile-schemas",
        "--targetdir",
        "/usr/share/glib-2.0/schemas",
        str(ROOT / "data"),
        sudo=True,
    )

    step("restart funes")
    run("killall", "funes", check=False, quiet=True)
    subprocess.Popen(
        ["funes"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    log.result(f"[b]funes {version} installed and restarted")

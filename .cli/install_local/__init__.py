"""fns install-local - install the working tree over the system copy and restart Funes.

Mirrors the xapp-project dev loop (see clockenstein's test-clocks).
"""

import subprocess
from pathlib import Path
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

    # Install into /usr/local, not /usr/share: /usr/share/glib-2.0/schemas is
    # dpkg's shared cache directory, and glib-compile-schemas --targetdir does
    # not merge into an existing cache, it replaces it with a compile of only
    # the sources given. Pointing it at /usr/share destroys every other
    # installed schema's cache entry.
    #
    # A copy of org.x.funes.gschema.xml in /usr/share can be either leftover
    # damage from that old bug, or a perfectly legitimate file owned by the
    # official .deb package (if Funes was `apt install`-ed before switching to
    # a local dev build). We can't safely tell those apart, and deleting a
    # dpkg-owned file out from under it is its own class of bug, so we only
    # warn and leave it for a human to resolve.
    share_schema = Path("/usr/share/glib-2.0/schemas/org.x.funes.gschema.xml")
    if share_schema.exists():
        log.error(
            f"{share_schema} exists. If it belongs to the official funes "
            "package, run `apt remove funes` to avoid two competing copies. "
            "If it's stale clobber damage from an old install-local, remove "
            "it and run `sudo glib-compile-schemas /usr/share/glib-2.0/schemas` "
            "to rebuild the cache from the remaining sources."
        )

    local_schemas = "/usr/local/share/glib-2.0/schemas"
    run("mkdir", "-p", local_schemas, sudo=True)
    run(
        "cp",
        str(ROOT / "data" / "org.x.funes.gschema.xml"),
        f"{local_schemas}/",
        sudo=True,
    )
    run("glib-compile-schemas", local_schemas, sudo=True)

    step("restart funes")
    run("killall", "funes", check=False, quiet=True)
    subprocess.Popen(
        ["funes"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    log.result(f"[b]funes {version} installed and restarted")

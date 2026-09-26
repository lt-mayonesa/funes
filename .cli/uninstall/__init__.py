"""fns uninstall - remove a locally installed (meson --prefix=/usr/local) Funes."""

from typing import Any

from hexagon.domain.env import Env
from hexagon.domain.tool import ActionTool
from hexagon.support.output.printer import log

from _lib import run

PATHS = (
    "/usr/local/bin/funes",
    "/usr/local/share/funes",
    "/usr/local/lib/python3/dist-packages/funes",
    "/usr/local/share/applications/org.x.funes.desktop",
    "/usr/local/share/glib-2.0/schemas/org.x.funes.gschema.xml",
)


def main(
    _tool: ActionTool,
    _env: Env | None = None,
    _env_args: Any = None,
    _cli_args: Any = None,
) -> None:
    run("rm", "-rf", *PATHS, sudo=True)

    # Best effort: the caches are shared, a stale entry is harmless.
    run(
        "glib-compile-schemas",
        "/usr/local/share/glib-2.0/schemas",
        sudo=True,
        check=False,
        quiet=True,
    )
    run(
        "update-desktop-database",
        "/usr/local/share/applications",
        sudo=True,
        check=False,
        quiet=True,
    )

    log.result("[b]local install removed")

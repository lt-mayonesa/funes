"""fns run - run Funes straight from the source tree, without installing anything."""

import os
from typing import Any

from hexagon.domain.env import Env
from hexagon.domain.tool import ActionTool
from hexagon.support.input.args import ToolArgs

from _lib import ROOT, require, run, step


class Args(ToolArgs):
    """No options of its own; everything after `fns run` goes to the app."""


def main(
    _tool: ActionTool,
    _env: Env | None = None,
    _env_args: Any = None,
    cli_args: Args = None,
) -> None:
    require("glib-compile-schemas", "python3")

    schemas = ROOT / "_build" / "data"
    schemas.mkdir(parents=True, exist_ok=True)

    step("compile schemas")
    run("glib-compile-schemas", "--targetdir", str(schemas), str(ROOT / "data"))

    # Let GTK and libxapp find the uninstalled icons (data/icons/hicolor/...).
    icons = ROOT / "_build" / "icon-data"
    icons.mkdir(parents=True, exist_ok=True)
    link = icons / "icons"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(ROOT / "data" / "icons")

    xdg_data_dirs = os.environ.get("XDG_DATA_DIRS", "")
    pythonpath = os.environ.get("PYTHONPATH", "")
    env = {
        "GSETTINGS_SCHEMA_DIR": str(schemas),
        "XDG_DATA_DIRS": ":".join(
            [
                str(icons),
                *([xdg_data_dirs] if xdg_data_dirs else []),
                "/usr/local/share",
                "/usr/share",
            ]
        ),
        "PYTHONPATH": ":".join([str(ROOT), *([pythonpath] if pythonpath else [])]),
    }

    step("funes")
    run(
        "/usr/bin/python3",
        str(ROOT / "app" / "funes_app.py"),
        *(cli_args.raw_extra_args or []),
        env=env,
    )

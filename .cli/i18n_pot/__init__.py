"""fns i18n-pot - regenerate funes.pot from the desktop entry and the python sources."""

from typing import Any

from hexagon.domain.env import Env
from hexagon.domain.tool import ActionTool
from hexagon.support.output.printer import log

from _lib import ROOT, require, run, step

POT = "funes.pot"


def main(
    _tool: ActionTool,
    _env: Env | None = None,
    _env_args: Any = None,
    _cli_args: Any = None,
) -> None:
    require("xgettext")

    step("desktop entry")
    run(
        "xgettext",
        "--language=Desktop",
        f"--output={POT}",
        "data/org.x.funes.desktop.in",
    )

    step("python sources")
    sources = sorted(
        str(p.relative_to(ROOT)) for p in [*ROOT.glob("app/*.py"), *ROOT.glob("funes/*.py")]
    )
    run(
        "xgettext",
        "--language=Python",
        "--join-existing",
        "--from-code=UTF-8",
        "--keyword=_",
        "--keyword=N_",
        f"--output={POT}",
        *sources,
    )

    log.result(f"[b]{POT} regenerated")

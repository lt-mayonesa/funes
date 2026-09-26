"""fns check - the exact check set CI runs: format, lint, bugcheck, tests, data."""

from typing import Any

from hexagon.domain.env import Env
from hexagon.domain.tool import ActionTool
from hexagon.support.input.args import Arg, OptionalArg, ToolArgs
from hexagon.support.output.printer import log

from _lib import require, run, step

UV_HINT = "install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"


class Args(ToolArgs):
    fix: OptionalArg[bool] = Arg(
        False,
        prompt_message="Apply ruff format / ruff check --fix instead of only reporting?",
    )


def main(
    _tool: ActionTool,
    _env: Env | None = None,
    _env_args: Any = None,
    cli_args: Args = None,
) -> None:
    require("uv", hint=UV_HINT)
    require("meson", "ninja", "desktop-file-validate", "glib-compile-schemas")

    run("uv", "sync", "--group", "dev", "--frozen", "--quiet")

    if cli_args.fix.value:
        step("ruff format")
        run("uv", "run", "ruff", "format", ".")
        step("ruff check --fix")
        run("uv", "run", "ruff", "check", "--fix", ".")
    else:
        step("ruff format --check")
        run("uv", "run", "ruff", "format", "--check", "--diff", ".")
        step("ruff check")
        run("uv", "run", "ruff", "check", ".")

    step("mypy --strict")
    run("uv", "run", "mypy")

    step("bandit")
    run("uv", "run", "bandit", "-c", "pyproject.toml", "-r", "app", "funes", "-ll", "--quiet")

    step("meson test")
    # The suite runs against the system python3, the interpreter the .deb targets.
    _setup_build()
    run("meson", "test", "-C", "_build", "--print-errorlogs")

    step("data validation")
    run("meson", "compile", "-C", "_build", quiet=True)
    run("desktop-file-validate", "_build/data/org.x.funes.desktop")
    run("glib-compile-schemas", "--strict", "--dry-run", "data/")

    log.result("[b]all checks passed")


def _setup_build() -> None:
    setup = ["meson", "setup", "_build", "--prefix=/usr"]
    if run(*setup, check=False, quiet=True).returncode != 0:
        run(*setup, "--wipe", quiet=True)

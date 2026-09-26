"""fns install-prerelease - download and install an alpha (PR) or beta (main) build.

alpha -> the `funes-alpha-deb-ubuntu24.04` artifact of a PR's latest CI run.
beta  -> the .deb attached to the rolling `beta` pre-release built from main.

Both live in GitHub, so the tool drives `gh`; see docs/RELEASING.md for how the
channels are produced.
"""

import json
import shutil
import subprocess
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any

from hexagon.domain.env import Env
from hexagon.domain.tool import ActionTool
from hexagon.support.input.args import Arg, OptionalArg, PositionalArg, ToolArgs
from hexagon.support.input.prompt import Prompt
from hexagon.support.output.printer import log

from _lib import require, run, step

REPO = "lt-mayonesa/funes"
ALPHA_ARTIFACT = "funes-alpha-deb-ubuntu24.04"
BETA_TAG = "beta"
CI_WORKFLOW = "ci.yml"
PR_LIMIT = 100
RUN_LIMIT = 20

# Dependency-upgrade PRs never carry a build worth trying by hand.
BOT_AUTHORS = {"dependabot", "dependabot[bot]", "renovate", "renovate[bot]", "app/dependabot"}
DEPENDENCY_LABELS = {"dependencies"}

GH_HINT = (
    "install it with: sudo apt install gh  (then: gh auth login)\n"
    "https://github.com/cli/cli#installation"
)


class Channel(str, Enum):
    alpha = "alpha"
    beta = "beta"


class Args(ToolArgs):
    channel: PositionalArg[Channel] = Arg(
        None,
        prompt_message="Which pre-release channel do you want to install?",
    )
    pr: OptionalArg[str] = Arg(
        None,
        prompt_message="Which PR's alpha build?",
        searchable=True,
    )
    assume_yes: OptionalArg[bool] = Arg(
        False,
        prompt_message="Install without asking for confirmation?",
    )


def main(
    _tool: ActionTool,
    _env: Env | None = None,
    _env_args: Any = None,
    cli_args: Args = None,
) -> None:
    require("gh", hint=GH_HINT)
    require("apt", "dpkg-deb", "dpkg-query")
    _require_gh_auth()

    if not cli_args.channel.value:
        cli_args.channel.prompt()
    channel = Channel(cli_args.channel.value)

    workdir = Path(tempfile.mkdtemp(prefix="funes-prerelease-"))
    keep = False
    try:
        if channel is Channel.alpha:
            deb = _download_alpha(cli_args, workdir)
        else:
            deb = _download_beta(workdir)

        _report_versions(deb)

        if not cli_args.assume_yes.value and not Prompt().confirm(
            message=f"Install {deb.name}?", default=True
        ):
            log.info("aborted, nothing was installed")
            return

        keep = not _install(deb)
        if keep:
            return

        _restart()
        log.result(f"[b]installed {_deb_version(deb)} and restarted funes")
    finally:
        if keep:
            log.info(f"the .deb was kept at {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


def _require_gh_auth() -> None:
    if run("gh", "auth", "status", check=False, quiet=True).returncode != 0:
        log.error("gh is not authenticated")
        log.info("run: gh auth login")
        raise SystemExit(1)


def _gh_json(*args: str) -> Any:
    return json.loads(run("gh", *args, quiet=True).stdout or "[]")


def _download_alpha(cli_args: Args, workdir: Path) -> Path:
    pull = _select_pr(cli_args)
    step(f"PR #{pull['number']} - {pull['title']}")

    run_id = _latest_run_with_artifact(pull["headRefName"])
    run(
        "gh",
        "run",
        "download",
        str(run_id),
        "--repo",
        REPO,
        "--name",
        ALPHA_ARTIFACT,
        "--dir",
        str(workdir),
    )
    return _single_deb(workdir, f"run {run_id}")


def _select_pr(cli_args: Args) -> dict[str, Any]:
    pulls = _open_pull_requests()
    if not pulls:
        log.error("no open PRs with alpha builds to install")
        raise SystemExit(1)

    by_number = {str(p["number"]): p for p in pulls}

    if cli_args.pr.value:
        number = str(cli_args.pr.value).lstrip("#")
        if number not in by_number:
            log.error(f"PR #{number} is not an open, non-dependency PR of {REPO}")
            raise SystemExit(1)
        return by_number[number]

    selected = cli_args.pr.prompt(
        searchable=True,
        choices=[{"name": _pr_label(p), "value": str(p["number"])} for p in pulls],
    )
    return by_number[str(selected)]


def _open_pull_requests() -> list[dict[str, Any]]:
    pulls = _gh_json(
        "pr",
        "list",
        "--repo",
        REPO,
        "--state",
        "open",
        "--limit",
        str(PR_LIMIT),
        "--json",
        "number,title,author,headRefName,updatedAt,labels,isDraft",
    )
    return [p for p in pulls if not _is_dependency_pr(p)]


def _is_dependency_pr(pull: dict[str, Any]) -> bool:
    author = (pull.get("author") or {}).get("login", "")
    labels = {label["name"].lower() for label in pull.get("labels") or []}
    return author.lower() in BOT_AUTHORS or bool(labels & DEPENDENCY_LABELS)


def _pr_label(pull: dict[str, Any]) -> str:
    author = (pull.get("author") or {}).get("login", "?")
    draft = " [draft]" if pull.get("isDraft") else ""
    updated = (pull.get("updatedAt") or "")[:10]
    return f"#{pull['number']}{draft} {pull['title']} - {author} - {updated}"


def _latest_run_with_artifact(branch: str) -> int:
    runs = _gh_json(
        "run",
        "list",
        "--repo",
        REPO,
        "--workflow",
        CI_WORKFLOW,
        "--branch",
        branch,
        "--limit",
        str(RUN_LIMIT),
        "--json",
        "databaseId,status,conclusion,createdAt",
    )
    completed = [r for r in runs if r.get("status") == "completed"]
    for candidate in sorted(completed, key=lambda r: r["createdAt"], reverse=True):
        if _has_alpha_artifact(candidate["databaseId"]):
            return int(candidate["databaseId"])

    log.error(f"no CI run of '{branch}' has a downloadable {ALPHA_ARTIFACT} artifact")
    log.info("artifacts expire after 14 days; push a commit to rebuild the PR")
    raise SystemExit(1)


def _has_alpha_artifact(run_id: int) -> bool:
    result = run(
        "gh",
        "api",
        f"repos/{REPO}/actions/runs/{run_id}/artifacts",
        "--jq",
        f'[.artifacts[] | select(.name == "{ALPHA_ARTIFACT}" and .expired == false)] | length',
        check=False,
        quiet=True,
    )
    return result.returncode == 0 and result.stdout.strip() not in ("", "0")


def _download_beta(workdir: Path) -> Path:
    step("rolling beta build of main")
    run(
        "gh",
        "release",
        "download",
        BETA_TAG,
        "--repo",
        REPO,
        "--pattern",
        "*.deb",
        "--dir",
        str(workdir),
    )
    return _single_deb(workdir, f"release '{BETA_TAG}'")


def _single_deb(workdir: Path, source: str) -> Path:
    debs = sorted(workdir.rglob("*.deb"))
    if not debs:
        log.error(f"no .deb found in {source}")
        raise SystemExit(1)
    return debs[0]


def _report_versions(deb: Path) -> None:
    step("versions")
    log.info(f"installed: {_installed_version() or '(not installed)'}")
    log.info(f"incoming : {_deb_version(deb)}")


def _installed_version() -> str:
    result = run("dpkg-query", "-W", "-f=${Version}", "funes", check=False, quiet=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def _deb_version(deb: Path) -> str:
    return run("dpkg-deb", "-f", str(deb), "Version", quiet=True).stdout.strip()


def _install(deb: Path) -> bool:
    step("apt install")
    result = run("apt", "install", "-y", str(deb), check=False)
    if result.returncode == 0:
        return True

    log.error(f"apt install failed ({result.returncode})")
    log.info(f"retry as root with:\n  sudo apt install -y {deb}")
    return False


def _restart() -> None:
    step("restart funes")
    run("killall", "funes", check=False, quiet=True)
    subprocess.Popen(
        ["funes"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

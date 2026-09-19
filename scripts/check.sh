#!/usr/bin/env bash
# Run the exact check set CI runs: format, lint, bugcheck, tests, data files.
#
# Usage: scripts/check.sh [--fix]
#   --fix   apply `ruff format` and `ruff check --fix` instead of only reporting
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

fix=0
[ "${1:-}" = "--fix" ] && fix=1

if ! command -v uv >/dev/null 2>&1; then
    cat >&2 <<'EOF'
error: uv is required to run the checkers.

  curl -LsSf https://astral.sh/uv/install.sh | sh

EOF
    exit 1
fi

step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

uv sync --group dev --frozen --quiet

if [ "$fix" = 1 ]; then
    step "ruff format"
    uv run ruff format .
    step "ruff check --fix"
    uv run ruff check --fix .
else
    step "ruff format --check"
    uv run ruff format --check --diff .
    step "ruff check"
    uv run ruff check .
fi

step "mypy --strict"
uv run mypy

step "bandit"
uv run bandit -c pyproject.toml -r app funes -ll --quiet

step "meson test"
# The suite runs against the system python3, the interpreter the .deb targets.
meson setup _build --prefix=/usr >/dev/null || meson setup _build --prefix=/usr --wipe >/dev/null
meson test -C _build --print-errorlogs

step "data validation"
meson compile -C _build >/dev/null
desktop-file-validate _build/data/org.x.funes.desktop
glib-compile-schemas --strict --dry-run data/

printf '\n\033[1;32mall checks passed\033[0m\n'

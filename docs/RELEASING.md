# SDLC: commits, pre-releases and releases

Three channels, one build recipe. Everything is driven by
[`.github/workflows/build-deb.yml`](../.github/workflows/build-deb.yml), a
reusable workflow that builds, tests, packages and lints the `.deb` on Ubuntu
24.04 and 22.04.

| Trigger | Workflow | Checks | Artifact | Version |
|---|---|---|---|---|
| push to `main` | `CI` → `beta` | all | assets on the rolling `beta` pre-release | `<ver>~beta.<run>.g<sha>~ubuntu<base>` |
| pull request | `CI` → `alpha` | all | workflow artifact + sticky PR comment | `<ver>~alpha.pr<N>.<run>.g<sha>~ubuntu<base>` |

Topic branches are only built through their pull request; `CI` no longer runs on
pushes to arbitrary branches, which used to start two identical runs per PR.
Use `workflow_dispatch` to build a branch that has no PR yet.
| push of a `v*` tag | `CI` | all | workflow artifact | `<ver>~ci.<run>.g<sha>~ubuntu<base>` |
| release published | `Release` | gate on CI + rebuild | assets on that release | `<ver>` |

"All checks" means, in this order and all blocking:

1. `ruff format --check` — formatting
2. `ruff check` — lint (E, F, W, I, N, UP, B, SIM, C4, RET, PTH, RUF)
3. `mypy --strict` and `bandit -ll` — bugcheck
4. `meson test` on Ubuntu 24.04 and 22.04 — unit tests
5. `desktop-file-validate` + `glib-compile-schemas --strict` — data files
6. `lintian --fail-on error` — packaging

Run the identical set locally with `fns check` ([`.cli/check`](../.cli/check/__init__.py));
`--fix` applies the auto-fixable ruff findings. The checkers are pinned in
`pyproject.toml` and installed with [uv](https://docs.astral.sh/uv/):

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
fns check
```

## Version ordering

Pre-release versions use `~`, which sorts *before* everything else in
`dpkg --compare-versions`. So `0.3.0~beta.41.gc0ffee` < `0.3.0`, and a machine
running a beta upgrades to the final release as soon as it lands. Never use
`+git<sha>`: that sorts *after* the release and pins people to the pre-release.

## Beta channel

Every green push to `main` force-moves the `beta` tag and replaces the assets of
the `beta` pre-release, which therefore always holds exactly one build: the tip
of `main`. Old assets are deleted first, so the release never accumulates.

```sh
gh release download beta --pattern '*.deb'
sudo apt install ./funes_*.deb
```

The `beta` tag is excluded from the CI triggers (only `v*` tags run CI), so
moving it cannot loop.

## Alpha channel

Pull requests build the same package with an `~alpha.pr<N>` version and upload
it as a 14-day workflow artifact. A sticky comment on the PR links the run and
prints the install snippet. Fork PRs get a read-only token, so the comment is
skipped there — the artifact is still reachable from the Checks tab.

## Releasing

1. Bump `version:` in `meson.build`, commit, push and let CI go green on `main`.
2. Create the release on GitHub (UI → *Releases* → *Draft a new release*, or
   `gh release create v0.3.0 --generate-notes`). The tag must be the
   `meson.build` version prefixed with `v`, on a commit that already has a
   successful CI run.
3. Publishing it runs `Release`, which:
   - checks tag ↔ `meson.build` version agreement;
   - **gates** on a successful `CI` run for that exact commit — an untested
     commit cannot be released;
   - rebuilds the package from the tag so the shipped version is clean
     (`0.3.0`, not `0.3.0~beta.…`);
   - re-runs tests and `lintian`;
   - attaches the `.deb` and `SHA256SUMS`.

Only one deb ships: it is `Architecture: all` and installs on both bases; the
22.04 job exists to prove the package still builds there. The workflow never
edits the notes or the pre-release flag.

Re-run packaging for an already published release with *Actions → Release → Run
workflow* and its tag.

`debian/changelog` is a stub; the packaged version is generated at build time by
[`scripts/set-deb-version.sh`](../scripts/set-deb-version.sh) (`fns
set-deb-version` locally), so it never needs hand editing.

## Roadmap: apt and other repositories

[`.github/workflows/publish-apt.yml`](../.github/workflows/publish-apt.yml) is a
manual-only stub. To finish it:

1. create a signing key; add the private key as the `APT_GPG_KEY` secret and its
   passphrase as `APT_GPG_PASSPHRASE`;
2. host the `pool/` + `dists/` tree on the `gh-pages` branch, managed with
   `reprepro` or `aptly`;
3. replace the stub's "Not implemented" step with the repository update and the
   Pages deploy;
4. document the `deb [signed-by=…] https://lt-mayonesa.github.io/funes …` source
   line in the README.

Other targets worth adding later: a PPA (`dput` to Launchpad), Flatpak, and an
AUR PKGBUILD.

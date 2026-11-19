# Contributing to meta-avocado

meta-avocado holds the Yocto layers and kas configurations that build Avocado OS.

## Where to start

Most Avocado OS users never build this repository. The avocado CLI installs
prebuilt packages from the Avocado package feeds; see the
[avocado-cli README](https://github.com/avocado-linux/avocado-cli#readme).
Work here when you need to change those packages, a board support layer or a
board's provisioning.

- Report bugs and request features in
  [GitHub issues](https://github.com/avocado-linux/meta-avocado/issues).
- Ask questions in the [Avocado Discord](https://www.peridio.com/join-our-discord).

## Pick a target branch

- `scarthgap` is the default branch. It builds on Yocto Scarthgap, the base of the 2024 feed.
- `wrynose` builds on Yocto Wrynose, the base of the 2026 feed.

Open your pull request against the branch whose feed needs the change. A change
that both branches need goes in as two pull requests, one per branch. Put the
branch name in brackets at the start of the title, as in
`[wrynose] stone: give sgdisk the full partition length`, so reviewers can pair
the two.

## Set up a build

Follow "Configuring a build" and "Building" in the [README](README.md).
[docs/feature-groups.md](docs/feature-groups.md) explains how to stack feature
fragments onto a machine.

## Run the checks locally

The pre-commit hooks run shfmt and shellcheck on shell scripts:

```bash
pre-commit install
pre-commit run --all-files
```

CI runs shellcheck on every tracked shell script, including scripts without a
`.sh` suffix. To silence a false positive, add a `# shellcheck disable=SCxxxx`
comment that states the reason.

CI runs the Python unit tests from the repository root with this command:

```bash
PYTHONPATH=meta-avocado/lib python3 -m unittest discover -s meta-avocado/tests -p 'test_*.py'
```

## Pull request checks

Each branch runs the workflows in its own `.github/workflows/`. On `scarthgap`,
every pull request runs shellcheck, a `bitbake -p` parse of the SDK container
for x86_64 and arm64 with the unit tests, host tests for stone, the QEMU runner
and the Tegra tools, and CodeQL. Other suites run when you touch the paths they
cover.

Full builds are opt in through labels:

1. Add a `build-<machine>` label for each machine to build. `<machine>` must
   match a file `kas/machine/<machine>.yml`.
2. Add the `build` label. The build reads the machine labels at that moment.

Each labeled machine builds `avocado-complete` twice, once minimal and once with
`kas/feature/complete.yml`. Adding labels needs triage or write access, so ask
in the pull request if you cannot add them.

## Commit and pull request titles

Pull requests are squash merged, so the title becomes the commit subject. Start
the title with the area it changes, such as `stone:`, `avocadoctl:` or
`meta-avocado-qemu:`, followed by a short summary. A paired pull request puts the
branch in brackets before the area.

## Add a machine or board

Follow [docs/adding-a-machine-target.md](docs/adding-a-machine-target.md).

## Report a security issue

Do not report vulnerabilities in public issues, pull requests or Discord. Follow
the [Avocado security policy](https://github.com/avocado-linux/avocado-cli/blob/main/SECURITY.md),
which covers this repository, and name meta-avocado as the affected repository.

## License

This repository is licensed under the [Apache License 2.0](LICENSE). Under
section 5 of that license, any contribution you intentionally submit for
inclusion is under the terms of the Apache License 2.0, unless you explicitly
state otherwise.

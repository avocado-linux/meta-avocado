# AvocadoOS bitbake-setup configurations

This directory is a [bitbake-setup](https://docs.yoctoproject.org/bitbake/2.18/bitbake-user-manual/bitbake-user-manual-environment-setup.html)
configuration registry. It provides an alternative to the [kas](../kas/)
workflow for setting up an AvocadoOS build, using the upstream Yocto tooling
(`bitbake-setup` + OE config fragments) instead.

Each `avocado-<machine>.conf.json` is a Configuration Template: it lists the
vendor layer/tool repositories (pinned to the same revisions as kas) and a
single build configuration that enables the right layers and an OE config
fragment carrying `MACHINE`, `DISTRO`, the environment defaults and the
local.conf settings for that machine.

The `meta-avocado` layers themselves are **not** cloned — they are used in
place from the live working tree this config ships in (via
`bb-layers-file-relative`, resolved relative to the `.conf.json`). That mirrors
kas, where `meta-avocado` is the local checkout rather than a pinned remote, and
means local edits (and unpushed commits) are picked up with no push round-trip.

## Source of truth

These files are **generated from the kas configuration** by
[`../scripts/kas2bitbake-setup.py`](../scripts/kas2bitbake-setup.py) — do not
edit them by hand. kas (under [`../kas/`](../kas/)) remains authoritative, so
the two workflows can never drift on repo pins. After changing anything under
`kas/`, regenerate:

```bash
./scripts/kas2bitbake-setup.py
```

The generator also (re)writes the per-machine fragments under
[`../meta-avocado/conf/fragments/avocado-build/`](../meta-avocado/conf/fragments/avocado-build/).
It is deterministic: re-running with no kas changes produces no diff.

## Bootstrap: get the `bitbake-setup` command

`bitbake-setup` ships *inside* the bitbake repo's `bin/` — it is not a
separately installed tool. You only need bitbake checked out once, to run the
script (the bitbake that actually builds is cloned by `bitbake-setup init`
into the setup's `layers/`, pinned by each config's `sources`).

Clone the same bitbake AvocadoOS pins, into the repo root (it is gitignored):

```bash
git clone --branch 2.18 https://github.com/avocado-linux/vendor-bitbake bitbake
```

Then drive it through [`../scripts/bitbake-setup`](../scripts/bitbake-setup), a
thin wrapper that runs the bootstrap bitbake-setup with the build "top
directory" pinned to `meta-avocado/bitbake-builds/` (gitignored), so build trees
stay inside the checkout instead of landing in your home directory — the same
convention as kas's `scripts/init-build`. (The bare `./bitbake/bin/bitbake-setup`
still works if you'd rather manage the top dir yourself.)

The wrapper keeps the heavy, reusable caches **outside** the repo so the
checkout doesn't balloon (and so a `rm -rf bitbake-builds` doesn't throw them
away). Defaults, all overridable via the environment:

| Variable             | Default                              | Controls           |
|----------------------|--------------------------------------|--------------------|
| `AVOCADO_BB_CACHE`   | `~/.cache/avocado-bitbake-setup`     | cache root         |
| `AVOCADO_DL_DIR`     | `$AVOCADO_BB_CACHE/downloads`        | `DL_DIR`           |
| `AVOCADO_SSTATE_DIR` | `$AVOCADO_BB_CACHE/sstate`           | `SSTATE_DIR`       |

`DL_DIR` is passed as a setting; `SSTATE_DIR` has no bitbake-setup setting
(site.conf hardcodes `<top_dir>/.sstate-cache`), so the wrapper symlinks that
path at the external cache.

> Note: kas does **not** use this checkout — kas clones its own bitbake into the
> build dir per [kas/vendor/oe.yml](../kas/vendor/oe.yml). This clone is only the
> bootstrap for the bitbake-setup workflow.

## Using it

Point it at a config **by local path** from within your checkout:

```bash
./scripts/bitbake-setup init ./bitbake-setup/avocado-qemux86-64.conf.json
```

`init` clones the pinned vendor layers into `bitbake-builds/<setup>/layers/`,
references the meta-avocado layers in place from this checkout, writes
`conf/bblayers.conf`, and enables the machine's fragment. It does **not** start a
build — finish with:

```bash
cd <setup-dir>/build
. ./init-build-env
bitbake avocado-distro
```

(`avocado-distro` is the build target for every machine; it is also recorded in
each config's description.)

Because the meta-avocado layers are used in place, your local edits to the
layers and fragments take effect immediately — no commit or push required.

> Local path only: `bb-layers-file-relative` resolves against the directory of
> the `.conf.json`, which bitbake-setup only knows when you init from a path on
> disk (the usage above). Initializing from a registry name or an `http(s)` URL
> is therefore not supported for these configs. The build always uses the
> meta-avocado checkout the config lives in; to build a different tree, run that
> tree's own `bitbake-setup/` configs.

## kas ↔ bitbake-setup mapping

| kas (flattened by `kas dump`)        | bitbake-setup                                   |
|--------------------------------------|-------------------------------------------------|
| vendor `repos.<r>.url` / `branch` / `commit` | `sources.<r>.git-remote` `uri` / `branch` / `rev` |
| vendor `repos.<r>.path`              | `sources.<r>.path`                              |
| vendor `repos.<r>.layers` (non-`disabled`) | configuration `bb-layers`                 |
| local `meta-avocado` layers          | `bb-layers-file-relative` (live working tree)   |
| `env.<V> = <default>`                | fragment `V ?= "<default>"` + `bb-env-passthrough-additions` name `V` |
| `machine` / `distro`                 | fragment `MACHINE = …` / `DISTRO = …`           |
| `local_conf_header.<k>`              | fragment body (in kas merge order)              |
| `target`                             | build note (`bitbake <target>`; run manually)   |

### Notes

- meta-avocado is consumed via `bb-layers-file-relative`, not cloned as a
  source — same as kas, where it is the local (url-less) repo.
- The `bitbake` repo is fetched as a source but is intentionally **not** a
  layer (kas marks it `.: disabled`); `oe-init-build-env` finds it next to
  openembedded-core.
- env defaults use `?=` so a value exported in your shell (and passed through
  via `bb-env-passthrough-additions`) still wins — matching kas semantics.
- The machine fragments live in the always-present `meta-avocado` base layer and
  are referenced as `meta-avocado/avocado-build/<machine>`.

# meta-avocado

AvocadoOS can be configured and built two ways. Both produce the same build —
they share the same pinned layer revisions, because the bitbake-setup configs
are generated from the kas configs (see below):

- **[kas](kas/)** — the established workflow.
- **[bitbake-setup](bitbake-setup/)** — the upstream Yocto tooling, for those
  who prefer it.

## Configuring a build (kas)

Source the `init-build` script and pass the path to a kas configuration to build. This will create a `build-{config file name}` directory in your `cwd`.

```bash
. scripts/init-build kas/machine/qemux86-64.yml
```

If you have direnv installed, there is a .envrc file added to the build dir to make it easier to reference the kas config. `$KAS_YML`

### Building

```bash
kas build $KAS_YML
```

## Configuring a build (bitbake-setup)

`bitbake-setup` ships inside the bitbake repo, so clone bitbake once into the
repo root to bootstrap it (gitignored; only used by this workflow — kas clones
its own bitbake):

```bash
git clone --branch 2.18 https://github.com/avocado-linux/vendor-bitbake bitbake
./scripts/bitbake-setup init ./bitbake-setup/avocado-qemux86-64.conf.json
cd bitbake-builds/<setup-dir>/build && . ./init-build-env
bitbake avocado-distro
```

`scripts/bitbake-setup` keeps build trees under `meta-avocado/bitbake-builds/`
(gitignored), the same way kas keeps `build-*` dirs in the checkout.

See [bitbake-setup/README.md](bitbake-setup/README.md) for the full guide,
the kas↔bitbake-setup mapping, and how to regenerate the configs. kas remains
the single source of truth; regenerate with `./scripts/kas2bitbake-setup.py`
after any change under `kas/`.

## Running in Qemu

Qemu can be run with a swtpm with the following command

```bash
meta-avocado/meta-avocado-qemu/scripts/run-qemux86-64-swtpm
```

This will open a tmux session.

## Local package feed

To serve a local package feed from your build outputs (sync packages, package
extensions, and start a browsable repo server in one command):

```bash
./scripts/dev-repo.sh 2026 qemux86-64
```

See [docs/local-package-feed.md](docs/local-package-feed.md) for the full guide.

## Testing

See [support/sdk-test/README.md](support/sdk-test/README.md) for testing instructions.

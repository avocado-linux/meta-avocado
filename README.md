# meta-avocado


## Configuring a build

Source the `init-build` script and pass the path to a kas configuration to build. This will create a `build-{config file name}` directory in your `cwd`.

```bash
. scripts/init-build kas/machine/qemux86-64.yml
```

If you have direnv installed, there is a .envrc file added to the build dir to make it easier to reference the kas config. `$KAS_YML`

## Building

```bash
kas build $KAS_YML
```

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

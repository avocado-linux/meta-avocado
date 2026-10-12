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

## Feature groups

Image content is opt-in: stack `kas/feature/<group>.yml` fragments onto a
machine to build anything from a bare-minimal image to the full feature set.
See [docs/feature-groups.md](docs/feature-groups.md) for the model and worked
`kas build` recipes.

## Running in Qemu

Qemu can be run with a swtpm with the following command

```bash
meta-avocado/meta-avocado-qemu/scripts/run-qemux86-64-swtpm
```

This will open a tmux session.

## Local package feed

Building `avocado-complete` also indexes `build/tmp/deploy/rpm` into a feed at
`build/tmp/deploy/avocado-feed` (symlinks plus repodata, nothing copied). Serve it
once and keep it running across rebuilds:

```bash
./scripts/feed-serve.sh build-qemux86-64
AVOCADO_REPO_URL=http://localhost:8080 avocado install
```

After rebuilding single packages, refresh the index with
`bitbake avocado-feed-index`. See
[docs/local-package-feed.md](docs/local-package-feed.md) for extensions and for
`dev-repo.sh`, which mirrors the production render pipeline.

## Testing

See [support/sdk-test/README.md](support/sdk-test/README.md) for testing instructions.

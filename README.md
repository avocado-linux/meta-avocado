# meta-avocado


## Configuring a build

Source the `init-build` script and pass the path to a kas configuration to build. This will create a `build-{config file name}` directory in your `cwd`.

```bash
. scripts/init-build kas/machine/qemux86-64-secureboot.yml
```

If you have direnv installed, there is a .envrc file added to the build dir to make it easier to reference the kas config. `$KAS_YML`

## Building

```bash
kas build $KAS_YML
```

## Running in Qemu

Qemu can be run with a swtpm with the following command

```bash
meta-avocado/meta-avocado-qemu/scripts/run-with-tpm
```

This will open a tmux session.

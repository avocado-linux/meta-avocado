# Boot settings: what a board delivers and how it says so

A project declares boot-level settings in `avocado.yaml`. Each board family
delivers the ones it can, and says which those are, so a project that asks for
something the board cannot do fails the build and names it instead of building
an image that quietly ignores it.

## The kinds

| Kind id | The project declares | Delivered by |
|---|---|---|
| `dt_overlay` | `extensions.<ext>.device_tree_overlays[]` with a `src` | the board's delivery hook |
| `dt_overlay_stock` | `device_tree_overlays[]` with no `src`, naming an overlay the BSP ships | the board's delivery hook |
| `boot_config` | `extensions.<ext>.boot_config[]`, single `key=value` lines | the board's delivery hook |
| `kernel_args` | `kernel.cmdline`, `kernel.cmdline_extra` | the board's own build or provisioning step (a platform build hook, the CLI's FIT rebuild, a provisioning script), from `AVOCADO_KERNEL_CMDLINE` and `AVOCADO_KERNEL_CMDLINE_EXTRA` |

The ids are the contract with avocado-cli. `boot_config` lines are written
verbatim, so what a line means is the board's decision; on a Raspberry Pi they
go into `avocado-overlays.txt`, which `config.txt` includes. The Raspberry Pi
hook refuses the keys that choose what the firmware boots (`kernel`,
`os_prefix`, `boot_partition`, `device_tree`, `start_file`, `fixup_file`),
since one of them bypasses the image's own boot setup; it names the offending
line and position.

## The capability file

A BSP that ships a delivery hook also ships

```text
/usr/libexec/avocado/boot-settings.json
```

in the same package (`avocado-dtc-overlay-deliver`), listing what the board
delivers:

```json
{
  "version": 1,
  "kinds": ["dt_overlay", "dt_overlay_stock", "boot_config"]
}
```

What the CLI does with it, before it compiles anything:

| Situation | Result |
|---|---|
| No file | Nothing changes: the hook runs and the claim check decides, as before the file existed |
| The project declares a hook kind the file does not list | The build fails, naming every such kind and the kinds the board supports. The hook does not run |
| The file is not JSON, has a `version` other than 1, or `kinds` is not a list of strings | The build fails and names the file |
| `kernel.cmdline` or `kernel.cmdline_extra` is set and the file does not list `kernel_args` | A warning, never a failure: boards that ignore these settings have always done so silently, and failing would break projects that build today |

`kernel_args` is not delivered by the hook. List it only if something on the
board really applies the variables: a platform build hook
(`avocado-build-<arch>`, as on Qualcomm), the CLI's own FIT rebuild, or a
provisioning script. Several boards do not apply them today (the Raspberry Pi 5
stone manifest has no command-line variable at all, and the Pi 4 one reads a
differently named `AVOCADO_CMDLINE_EXTRA`), and the warning is how a project
finds out.

## Limits to know about

- **The file travels with the hook package.** `avocado sdk install` puts
  `avocado-dtc-overlay-deliver` in the target sysroot only while some active
  extension declares overlays or `boot_config`, so the kernel-arguments warning
  can only appear for such projects (or where an earlier install left the
  package in the sysroot volume). A board with no hook has nowhere to publish a
  capability file yet. Giving the file its own always-installed package is the
  follow-up.
- **A lock can hold an older package.** A project whose `avocado.lock` pins an
  earlier build of the package keeps receiving it without the file, and the
  check stays off, until the lock is refreshed.
- **The file lists kinds, not every restriction.** A hook can still refuse one
  declaration after the early check: the Qualcomm hook rejects an overlay with
  `params`, because the overlay is merged into the tree inside the UKI.
- **The CLI refuses a `version` it does not know.** A file with another version
  fails any build that declares a hook kind, so bump it only together with a CLI
  release that reads it.

## Keeping the file true

The file is a promise, and the CLI trusts it. Each layer that ships one has a
host test, `tests/test-boot-settings.sh` beside its hook, that checks every
hook-delivered kind the file lists is claimed by the real hook, and, where the
hook cannot deliver a kind, that it does not. Add a kind to the file only
together with the hook change that makes it true, and run the test.

Claims themselves are unchanged: one per overlay, and one for the whole
`boot_config` list.

## Which boards say what today

| Board family | Hook | Capability file | Lists |
|---|---|---|---|
| Raspberry Pi | yes | yes | `dt_overlay`, `dt_overlay_stock`, `boot_config` |
| Qualcomm | yes | yes | `dt_overlay`, `kernel_args` |
| All others | no | no | not stated; unchanged behaviour |

A board without a hook fails a project that declares an overlay or
`boot_config` at `avocado install`, as it always has. Boards that honour
`kernel.cmdline_extra` without a hook (NVIDIA Jetson, the NXP FIT path) have no
capability file yet, so they give no warning either way.

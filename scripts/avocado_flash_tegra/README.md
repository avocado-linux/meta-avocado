# avocado_flash_tegra

Backend for `avocado-flash nvme`. It flashes a Jetson Orin Nano's NVMe over
USB while the board is in recovery mode. Standard library only.

## What it does

`avocado-flash nvme` is a thin wrapper around the stone tegraflash
provisioning script (profile `tegraflash-nvme`). It validates every input,
pins the one board in recovery mode, then runs the script as root with an
explicit environment. It synthesizes nothing itself: the partition layout,
UEFI boot priority and carrier overlays all live in the script.

Before the board is touched it refuses on any unmet precondition:

- a missing manifest template, provisioning script, image, or host tool
- no recovery-mode device, or more than one
- neither root nor `sudo` on the search path
- not enough free space for the work directory (total input size plus one tenth)

It also checks the kernel `Image` and the `avocado-tegra-bootimg` helper
(which pins the rootfs partition identifiers into the boot image), so the
board cannot boot a different disk and look like a successful flash.

Options:

| Option | Meaning |
|--------|---------|
| `-m`, `--machine` | machine name (default: the one built) |
| `-d`, `--deploy` | Yocto deploy directory |
| `-n`, `--dry-run` | validate and print the plan; write nothing |
| `-y`, `--assume-yes` | skip the typed confirmation |
| `--workdir` | work directory for the run (kept on failure) |
| `--rcm-id` | recovery-mode USB id `vvvv:pppp` for another board |

## Build the flash inputs

Build the `avocado-stone` target. A bring-up build lacks these inputs, and
the tool refuses and names the target that produces each one:

| Input | Build target |
|-------|--------------|
| manifest template (`stone-<machine>.json`) | `avocado-stone` |
| provisioning script | `avocado-stone` |
| var image | `avocado-image-var` |
| ESP image | `tegra-espimage` |
| TOS image | `tos-optee` |
| host tools (`tegraflash-tools` directory, with `initrd-flash`) | `tegraflash-tools-deploy` |

The other manifest entries map to `avocado-image-rootfs`,
`avocado-image-initramfs`, `tegra-initrd-flash-initramfs` and
`tegraflash-bsp` (also the carrier BSP). An entry with no mapping falls back
to `avocado-stone`.

The host also needs `jq`, `fdtget`, `fdtput`, `cpp` and `lsusb`, and a
`mkbootimg` either on the search path or executable inside the deployed
`tegraflash-tools` directory.

## Enter recovery mode

1. Fit the FC_REC jumper to GND on the J14 header.
2. Connect USB-C from the board to the host.
3. Power-cycle the board.

Check with `lsusb -d 0955:`. The bench Orin Nano shows `NVIDIA APX 7523`,
that is `0955:7523`. That value is recorded for that board only; pass
`--rcm-id vvvv:pppp` for another one.

## Run it

Dry run first. It prints the validated inputs, the pinned device and the plan
(command, working directory, environment) and writes nothing:

```
avocado-flash nvme --dry-run
```

Then the real run:

```
avocado-flash nvme
```

It prints:

- `inputs: all present`, then each input with its size and modification time
- `pinned: <path> <vid>:<pid>`, the recovery-mode device it will flash
- warnings that the NVMe is erased entirely and that QSPI firmware and UEFI
  variables are rewritten
- a typed confirmation prompt, unless `--assume-yes` is given
- the provisioning script's output, which is also streamed to `flash.log` in
  the work directory

The device pin is checked again after the confirmation, so a board attached
while the prompt waited is not flashed. The work directory is
`/var/tmp/avocado-flash-<machine>-<timestamp>` unless `--workdir` is given.
Use `--rcm-id` for another board's recovery-mode id.

## After the flash

On success the tool prints `Flash finished.` Remove the FC_REC jumper and
power-cycle the board.

QSPI firmware and UEFI variables were rewritten, and the old firmware version
cannot be read in recovery mode, so record it before entering recovery mode.

On success the tool removes the `tegraflash` directory the script left in the
work directory (through `sudo` when not root), and the work directory itself if
it created it.

## If it fails

Before any USB action the run compares the rootfs and ESP images with their
partitions in the deployed `tegraflash-bsp/external-flash.xml`, and refuses when
an image is larger than its partition, the partition is absent, or its size is
not a number (a missing or unreadable layout also refuses). For a rootfs that
does not fit, rebuild with a larger `ROOTFSPART_SIZE_DEFAULT`.

The work directory and `flash.log` are kept, and their paths are printed. The
board may be mid-write, so enter recovery mode again before retrying.

The script runs as root, so files in the work directory are root-owned. The
tool never passes `AVOCADO_AGENT_SOCK` to the script: it builds the
environment from scratch and tells `sudo` to unset the variable. The run needs
root, directly or through `sudo`.

Host tools: the run needs a host `cpp`. The provisioning script's own fallback
writes a `cpp` wrapper that executes `cpp` and so calls itself forever, so the
tool stages a `<machine>-avocadosdk-linux-cpp` symlink to your real `cpp` in
the work directory and the script uses that instead. The run is refused when
no `cpp` is on `PATH`.

Exit codes: 0 success, 1 a refusal or a failed flash, 2 a usage error, 130
interrupted.

## Branch note

The older release branch's provisioning script checks for root. This branch's
does not, so a non-root run would fail only after signing and the recovery
boot had succeeded. That is why the tool checks for root itself and does not
rely on the script.

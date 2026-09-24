# Boot device selection: layer notes

How `avocado-boot-device` is built and wired. For what the tool does and how to
use it, see the Boot device selection guide on the docs site - this page covers
only what someone changing this layer needs.

## Where the recipe lives, and why it is not in meta-avocado-nvidia

`meta-avocado/recipes-avocado/boot-device/avocado-boot-device_1.0.bb`.

It sits in the common layer because `BootOrder` is a UEFI concept rather than a
Tegra one. `meta-avocado-x86-64` already ships `efibootmgr` in its rootfs
packagegroup for A/B slot activation, so it can consume this unchanged rather
than growing a second copy.

`inherit allarch` - the payload is a POSIX shell script with no compiled
content, matching `avocado-dtc-overlay-deliver` in each BSP layer.

## The efibootmgr dependency

```bitbake
RDEPENDS:${PN} = "efibootmgr efivar"
```

Both come from oe-core (`meta/recipes-bsp/efibootmgr`, `meta/recipes-bsp/efivar`)
and declare `aarch64` in `COMPATIBLE_HOST`, so the dependency resolves on Tegra
as well as x86-64. oe-core is always enabled, so no layer needs adding.

`efibootmgr` is doing the part that is genuinely hard in shell: decoding an EFI
device path far enough to say which boot entry refers to an NVMe device.
`efivar` is what clears the immutable flag efivarfs sets on those variables -
without it, a direct write needs `chattr -i` by hand.

## Enabling it for another BSP

Only the Tegra feed is wired up today, because that is the hardware it was
designed against:

```bitbake
# meta-avocado-nvidia/recipes-avocado/packagegroups/packagegroup-avocado-tegra-extra.bb
RDEPENDS:${PN} = " \
  ...
  avocado-boot-device \
"
```

Adding it to another BSP means adding the same line to that layer's
`packagegroup-avocado-<bsp>-extra.bb`, which is what puts the package in that
target's feed. Nothing else is BSP-specific.

Before doing that, check the device-path node names the script matches on
(`NVMe(`, `SD(`, `eMMC(`, `USB(`) against what that board's firmware actually
emits - `efibootmgr -v` on the board is the answer. A class that does not match
makes the tool refuse rather than misbehave, but it also makes it useless on
that board.

## Fixing a board that keeps booting the wrong medium

Provisioning writing a new image to a disk and firmware then booting a
different, older one are not the same event - `BootOrder` is a firmware
setting, not something a flash or write operation touches. When that happens,
run this from the board's currently-booted OS:

```sh
avocado-set-boot-device nvme
```

Substitute the medium that should come first: `nvme`, `sd`, `emmc`, or `usb`.
This moves that device's UEFI boot entry to the front of the persistent
`BootOrder` and leaves every other entry in place as a fallback, so a later
failure of the selected disk does not strand the board. Confirm the change
took with:

```sh
avocado-set-boot-device --list
```

Use `avocado-set-boot-device --once nvme` instead when testing a boot rather
than committing to it - it writes `BootNext` for a single boot and self-heals
on the next power cycle even if you forget to revert it.

### Fallback: the currently-booted OS predates this change

The instructions above assume the running OS has `avocado-set-boot-device`
installed - it shipped in the Tegra feed on `avocado-linux/meta-avocado`
starting with the `avocado-boot-device` recipe. A board's OS that predates
this change has no such command and `command -v avocado-set-boot-device` will
return nothing. Two options, in order of preference:

**Install the package separately**, if the board's package feed still serves
it (it lives in the common layer, not a Tegra-only one, so any feed built
after this recipe merged carries it):

```sh
avocado install avocado-boot-device
```

If that succeeds, use the tool as described above rather than the manual
procedure below.

**Manual fallback**, when the package is unavailable: reorder `BootOrder`
directly with `efibootmgr`, using the board's own `BootXXXX` entries.

1. List the raw firmware boot-manager entries and find the four hex digits
   for the medium you want to boot:

   ```sh
   efibootmgr -v
   ```

   Look for the entry whose description or device path names your target -
   an NVMe entry's device path contains `NVMe(`, an SD card's contains `SD(`,
   eMMC's contains `eMMC(`, and USB mass storage's contains `USB(`. The four
   hex digits after `Boot` (e.g. `Boot0003`) are that entry's number.

2. Read the current `BootOrder` line from the same `efibootmgr -v` output,
   e.g. `BootOrder: 0000,0001,0003,0002`.

3. Rewrite it with the target entry moved to the front, keeping every other
   entry's relative order so there is still a fallback path:

   ```sh
   efibootmgr -o 0003,0000,0001,0002
   ```

4. Confirm the write took by re-running `efibootmgr` and checking the
   `BootOrder:` line reads back exactly as written - efivarfs can silently
   accept a write that the firmware later discards.

If `efibootmgr` itself is missing, no in-OS path exists; the board's OS needs
reflashing with an image that carries `efibootmgr` before boot order can be
managed from userspace at all.

## Related

- `meta-avocado/recipes-avocado/boot-device/files/avocado-set-boot-device` - the script
- `meta-avocado-nvidia/recipes-core/avocado-tegra-init/files/avocado-tegra-init` -
  the initrd side, which resolves the rootfs. Boot order chooses the kernel;
  that script chooses the rootfs, and the two have to agree.

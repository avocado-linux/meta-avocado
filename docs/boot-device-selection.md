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

## Related

- `meta-avocado/recipes-avocado/boot-device/files/avocado-set-boot-device` - the script
- `meta-avocado-nvidia/recipes-core/avocado-tegra-init/files/avocado-tegra-init` -
  the initrd side, which resolves the rootfs. Boot order chooses the kernel;
  that script chooses the rootfs, and the two have to agree.

# boot-device-tool-packaging: the runtime boot-device tool and its EFI-variable-tooling dependencies are present in both the rootfs feed and the initramfs for all five in-scope Jetson machines by default, with a documented manual invocation path (and a fallback for images predating this change).

**Delivered by:** jetson-boot-order-assertion
**Modules touched:** other

## Delivery Note

Invocation: `avocado provision -r dev --profile tegraflash-<medium>` (Phase 1: operator additionally runs `avocado-set-boot-device <medium>` from whichever OS currently boots, with a documented fallback for an OS old enough to lack the tool; Phase 2, when firmware actually boots the new image: no separate step)
Precondition: the runtime boot-device tool merged to `scarthgap` (or an equivalent landing) and composed into both the shared Tegra rootfs default-install package group and the shared Tegra initramfs default-install package group — two separate composition steps, both currently missing
Success signal: `efibootmgr` on the booted target shows the just-provisioned medium's `Boot` entry first in `BootOrder`, cross-checked against `avocado-set-boot-device --list`'s own device-class output rather than a bare `/proc/mounts` match
Silent failure: Phase 1 — operator skips the manual step, or the currently-booting OS predates Phase 1's packaging and lacks the tool entirely; `BootOrder` stays at whatever firmware already had. Phase 2 — firmware boots something other than the new image (documented limitation), efivarfs turns out not to be writable at the chosen stage, or the unit's own attempt fails and the marker survives for a retry on the next reboot. All are fail-safe: the board still boots from whatever device it already prefers.

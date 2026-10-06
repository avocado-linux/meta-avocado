# automatic-boot-order-assertion: after provisioning, when firmware boots the newly-flashed image on its first real boot, a marker-driven oneshot unit automatically asserts that medium as the front of `BootOrder`, with a defined marker lifecycle (write, retry-until-success, delete-only-on-success) and no automatic remediation for the documented stale-medium case (firmware boots something else instead).

**Delivered by:** jetson-boot-order-assertion
**Modules touched:** other

## Delivery Note

Invocation: `avocado provision -r dev --profile tegraflash-<medium>` (Phase 1: operator additionally runs `avocado-set-boot-device <medium>` from whichever OS currently boots, with a documented fallback for an OS old enough to lack the tool; Phase 2, when firmware actually boots the new image: no separate step)
Precondition: the runtime boot-device tool merged to `scarthgap` (or an equivalent landing) and composed into both the shared Tegra rootfs default-install package group and the shared Tegra initramfs default-install package group — two separate composition steps, both currently missing
Success signal: `efibootmgr` on the booted target shows the just-provisioned medium's `Boot` entry first in `BootOrder`, cross-checked against `avocado-set-boot-device --list`'s own device-class output rather than a bare `/proc/mounts` match
Silent failure: Phase 1 — operator skips the manual step, or the currently-booting OS predates Phase 1's packaging and lacks the tool entirely; `BootOrder` stays at whatever firmware already had. Phase 2 — firmware boots something other than the new image (documented limitation), efivarfs turns out not to be writable at the chosen stage, or the unit's own attempt fails and the marker survives for a retry on the next reboot. All are fail-safe: the board still boots from whatever device it already prefers.

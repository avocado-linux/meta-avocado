# Security capabilities: built by the feed, chosen by the runtime

Avocado OS splits every security feature into two decisions made by two
different parties:

| Decision | Who makes it | Where |
|---|---|---|
| **Can this machine deliver the feature?** | The layer maintainer | `AVOCADO_SECURITY_CAPABILITIES` in the machine conf |
| **Does this product use it?** | The user | `avocado.yaml` (`var.encrypt`, `image.verity`, ...) via `avocado-cli` |

Yocto's job is the first half only: **a declared capability is built into the
feed** — kernel options, initramfs tooling, rootfs helpers, partition layout —
so that the second half can be made later, per runtime, without rebuilding the
distro. A feed built with `kas/feature/complete.yml` therefore ships everything
its machine can do, and a runtime that does not opt in behaves exactly as if the
capability did not exist.

The one exception is `verified-boot`, which is a build-time mode by nature:
it embeds a signing key into the bootloader. See below.

## 1. The declaration

```bitbake
# conf/machine/avocado-<machine>.conf
AVOCADO_SECURITY_CAPABILITIES = "encrypted-var verified-boot"
```

Three states, and they are distinguishable on purpose
(`meta-avocado/classes/avocado-security-capabilities.bbclass`):

| Value | Meaning |
|---|---|
| unset | machine not yet migrated onto the declaration — nothing security-related is built or checked |
| `""` | machine declares it can deliver nothing |
| `"encrypted-var ..."` | the listed capabilities are built into the feed |

The declaration is also shipped to the device as
`/etc/avocado-security-capabilities` (package `avocado-security-capabilities`,
pulled by both the rootfs and initramfs packagegroups), so on-device tooling can
refuse to do something the image was never built for.

Recipes gate on the declaration with one idiom:

```bitbake
${@bb.utils.contains('AVOCADO_SECURITY_CAPABILITIES', 'encrypted-var', ' file://dm-crypt.cfg', '', d)}
```

Do not gate delivery on `DISTRO_FEATURES`. That was the old model, and it made
the feed decide for the user.

## 2. Capabilities

### `encrypted-var` — LUKS2 `/var`

**Declaring builds:**

| Piece | Where | Gate |
|---|---|---|
| dm-crypt + LUKS ciphers | kernel (`dm-crypt.cfg`; NXP kernels via `avocado-security-kernel.inc`, Jetson via `ftpm.cfg`) | capability |
| `cryptsetup`, `cryptsetup-var` (unlock / first-boot encrypt) | initramfs (`packagegroup-avocado-initramfs`) | capability |
| `cryptsetup-var-udev`, `cryptsetup-var-posture`, `cryptsetup` | rootfs (`packagegroup-avocado-rootfs`) | capability |
| a key backend (`var-key.sh`) | `recipes-core/cryptsetup-var/` bbappend in the vendor layer | machine override |

**The runtime decides.** `avocado-cli` writes `/etc/avocado/var-encrypt` into a
runtime's initramfs when its `avocado.yaml` says:

```yaml
runtimes:
  prod:
    var:
      encrypt: true
```

`cryptsetup-var.service` has `ConditionPathExists=/etc/avocado/var-encrypt`. No
marker, no encryption — the feed's own initramfs never carries the marker, so a
distro image always boots a plaintext `/var`. With the marker, the first boot
encrypts the flashed `/var` in place (seeded content survives) and later boots
open it as `/dev/mapper/var`.

**How `/var` follows the choice.** `fstab` mounts `/var` from
`/dev/disk/by-avocado/var`, never from a device the build picked:

- `base-files` generates `61-avocado-var.rules` from `AVOCADO_VAR_PART_DEV`
  (present in the initramfs and the rootfs): the plaintext partition claims the
  name unless it carries a LUKS header (`ID_FS_TYPE=crypto_LUKS`), and the open
  `var` dm mapping claims it with `link_priority=100`. So an open LUKS container
  is the only owner of the name whenever the initrd created one.
- `99-zz-cryptsetup-var.rules` (in `cryptsetup-var-udev`, rootfs) re-asserts the
  mapping after switch-root, where the udev database has been cleared.

Turning `var.encrypt` back off on a device that already encrypted is not a
supported downgrade: the partition stays LUKS, nothing opens it, `/var` does not
mount. Reprovision instead.

`AVOCADO_VAR_PART_DEV` is therefore always the **plaintext** partition:
`/dev/disk/by-partlabel/<name>`, `/dev/disk/by-partuuid/<uuid>` /
`PARTUUID=<uuid>`, or a bare `/dev/<node>` (other `by-*` forms are rejected at
build time). The generated rule matches that partition on **any** attached disk;
scoping it to the boot disk is not expressible in a static rule and is a known
follow-up.

**Jetson variant.** Same declaration, same gate (`packagegroup-avocado-tegra-extra`
publishes the fTPM userspace on the `ftpm` capability the same way), same marker.
Only the mount path differs: `avocado-tegra-init` finds the var partition by
PARTNAME on whatever disk the rootfs booted from (NVMe, eMMC, SD) — a fixed
`by-avocado/var` rule cannot express "the var partition on the boot disk" when
several disks carry one — so `AVOCADO_VAR_PART_DEV` is `"none"`, no fstab line or
rule is generated, and `avocado-tegra-init` masks `cryptsetup-var.service` and
checks `/etc/avocado/var-encrypt` itself before calling `cryptsetup-var.sh`.

**Key backends today:**

| Platform | `var-key.sh` | Later boots |
|---|---|---|
| i.MX 8M / 9 | SoC-UID-derived Argon2id | same key |
| Jetson | Argon2id recovery key + TPM2 keyslot sealed to the OP-TEE fTPM (PCR 7) | TPM2 token, Argon2id fallback |
| qemu / x86 | Argon2id (+ swtpm / TPM2 where present) | as Jetson |

**Prerequisites a machine must meet before declaring it:** a dm-crypt kernel
fragment reachable from its kernel recipe, and a GPT `var` partlabel
(`cryptsetup-var.service` keys on it). Raspberry Pi has neither today
(`linux-raspberrypi` carries no fragment; the layout is MBR), so it declares
`""` rather than shipping a unit that waits on a device it never produces.

### `verified-boot` — signed FIT, enforced by U-Boot

This is the exception: **a build-time mode**, requested with
`kas/feature/verified-boot.yml` and refused unless declared.

- Without it, U-Boot boots any FIT, signed or not. A project can still sign its
  FIT (`AVOCADO_FIT_KEY_DIR`) and re-key a prebuilt `imx-boot` from the SDK
  (`fdt_add_pubkey`, `mkimage_imx8`), which is how a product enforces its own key.
- With it, the distro's `sb-keys` public key is embedded in U-Boot and
  `CONFIG_FIT_SIGNATURE` enforces it — a project's own FIT will not boot without
  replacing the bootloader. That is why `complete.yml` never turns it on.

Declaring it (i.MX: `avocado-imx-fit.inc` machines) builds FIT support into
U-Boot and the kernel's FIT artifacts regardless, so the unsigned and
project-signed paths are always available.

### Bootloader updates (i.MX8M eMMC)

The bootloader is the thing that enforces the FIT key, so it has to ship with
the OS update that changes the key. On eMMC the i.MX BootROM loads `imx-boot`
from a hardware boot partition selected by `PARTITION_CONFIG`; there are two
(`boot0`, `boot1`), and the manifest couples them to the OS slots so a slot
always boots with the bootloader that verifies its FIT:

```json
"os_artifacts": {
  "imx_boot": { "image_key": "imx_boot", "slot_partitions": ["emmc-boot:0", "emmc-boot:1"] }
},
"activate": [
  { "type": "uboot-env", "set": { "avocado_boot_slot": "{inactive_slot}" } },
  { "type": "command",   "command": ["avocado-imx-bootpart", "{inactive_slot}"] }
],
"rollback": [ ...same with "{previous_slot}" ]
```

- `emmc-boot:<n>` is an avocadoctl slot target: the n-th boot partition of the
  disk that holds `var`, written with `force_ro` lifted and verified by
  read-back. A disk without boot partitions (SD card) is refused.
- `avocado-imx-bootpart <slot>` (from `meta-avocado-nxp`, in every i.MX
  rootfs) flips `PARTITION_CONFIG` with `mmc bootpart enable`, and refuses a
  boot partition that does not hold an i.MX boot image, so a rollback can never
  point the ROM at an empty partition.
- `avocado build` puts the re-keyed `imx-boot` in the runtime under the feed's
  own file names, so this artifact is the project-keyed bootloader whenever
  `signing.fit_key` is set.

**Medium rule.** A manifest describes every medium the machine can be
provisioned on (`sd`, `img`, `uuu-emmc`), and an OS update must work on all of
them. Targets that name hardware the running medium does not have — an eMMC
boot partition while booted from SD — are **skipped with a message** by
avocadoctl, and `avocado-imx-bootpart` exits 0 the same way, so only what exists
on the running medium is written. On SD the bootloader therefore stays what
provisioning flashed; the eMMC path is the one that carries bootloader updates.
Apply the same rule to any future medium-specific target.

Not covered: a bootloader that does not boot at all. The BootROM has no
fallback across boot partitions here, so a bad `imx-boot` needs USB recovery
(`uuu`); validate bootloader changes on a bench device before fleet rollout.

### rootfs and extension dm-verity

Not a capability token: every i.MX kernel carries `dm-verity.cfg`, every i.MX
stone manifest carries per-slot hash partitions, and the U-Boot environment
reads `avocado,roothash` out of the FIT when present. A FIT without a root hash
boots a plain rootfs. The choice is entirely `avocado.yaml`:

```yaml
rootfs:
  image:
    verity: true
extensions:
  security:
    image:
      verity: true
```

### `ahab`, `ftpm`, `tpm2`

Build-time requests (`kas/feature/*.yml`), checked against the declaration the
same way as `verified-boot`. `ahab` signs the i.MX 9 boot container (see
`meta-avocado-nxp/docs/imx93-srk-pki.md`); `ftpm`/`tpm2` select the OP-TEE fTPM
or a hardware/virtual TPM as the sealing device for `encrypted-var`.

## 3. Per-platform summary

| Machine | `encrypted-var` | `verified-boot` | verity | var device | notes |
|---|---|---|---|---|---|
| imx8mp-evk | built | declared | built | `by-partlabel/var` | CAAM in kernel; FIT boot |
| imx93-frdm | built | declared | built | `by-partlabel/var` | FIT boot, env permit list under verified-boot; AHAB optional |
| imx93-evk, imx91/95-frdm, var-dart, ucm | — (undeclared) | — | built | `by-partlabel/var` | `booti`; declare to enable |
| jetson-* | built | — | — | `none` (tegra-init) | fTPM-sealed key |
| qemuarm64 / qemux86-64 | built | — | — | `by-partlabel/var` | fTPM / swtpm |
| intel-x86-64-v* | — (`tpm2` only) | — | — | `by-partlabel/var` | |
| raspberrypi* | — (declares `""`) | — | — | `/dev/mmcblk0p3` | MBR, no dm-crypt fragment yet |

## 4. What a `complete` build means

`kas/feature/complete.yml` adds no security tokens. Everything a machine
declares is built whether or not `complete.yml` is used; `complete.yml` only
widens the *package* set (feature groups). The old `kas/feature/encrypted-var.yml`
is gone; a leftover `encrypted-var` in `DISTRO_FEATURES` is warned about and
ignored.

## 5. Transitions

An OS update is applied by the avocadoctl **already on the device**, so a fix
in the apply path never helps the update that carries it. Order fleet changes
accordingly:

| Transition | Works? | Notes |
|---|---|---|
| Extension-only update | yes | unchanged path |
| OS bundle update on a GPT machine | avocadoctl with `locate_target` (#24) or newer | older builds wrote by layout offset to the manifest's devpath, which is kernel-dependent |
| OS update onto a device provisioned with the previous partition layout | **no** | an update cannot add partitions and the saved U-Boot env maps the old slots; reprovision |
| Enabling extension verity (`root_hash` in the manifest) | after avocadoctl #22 is on the device | older builds mount the extension unverified without complaint; ship the new avocadoctl in a plain OS update first |
| Bootloader (FIT key) change via OS update | i.MX8M eMMC with `emmc-boot:<n>` artifacts | slot a ↔ boot0, slot b ↔ boot1; rollback flips back; an unbootable bootloader still needs `uuu` |
| Enabling `var.encrypt` via OS update | yes | first boot of the new slot encrypts the flashed `/var` in place, shrinking a grown filesystem to the data in use first |
| Disabling `var.encrypt` after it encrypted | **no** | the partition stays LUKS; reprovision |
| `/var` mounted through `by-avocado/var` (this change) | per slot | the old slot keeps its fstab; the two coexist |

Rule of thumb: **ship the new avocadoctl in a plain OS update before turning on
any manifest-level security feature.**

## 6. Adding a capability to a new machine

1. Wire the delivery side: kernel fragment, key backend bbappend, partition
   layout (`var` partlabel), any bootloader pieces.
2. Gate every one of them on `AVOCADO_SECURITY_CAPABILITIES`, not on
   `DISTRO_FEATURES`.
3. Set `AVOCADO_VAR_PART_DEV` to the plaintext partition.
4. Declare: `AVOCADO_SECURITY_CAPABILITIES = "..."`.
5. Prove both halves on hardware: a runtime **without** the opt-in boots
   plaintext; a runtime **with** it encrypts on first boot and reopens on the
   next. Only the second proves the capability; only the first proves the
   declaration did not take the choice away.

See also `docs/adding-a-machine-target.md` §4.

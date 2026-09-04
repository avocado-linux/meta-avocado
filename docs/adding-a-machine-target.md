# Adding a New Machine Target to Avocado OS

This guide walks through every file and configuration needed to add a new
hardware target to Avocado OS.  Use it as a checklist and reference when
bringing up a new board or SoC.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Required Components Checklist](#2-required-components-checklist)
3. [Layer Configuration](#3-layer-configuration)
4. [Machine Configuration](#4-machine-configuration)
5. [KAS Configuration](#5-kas-configuration)
6. [Stone Manifest](#6-stone-manifest)
7. [Stone Provisioning Scripts](#7-stone-provisioning-scripts)
8. [SDK Target Scripts](#8-sdk-target-scripts)
9. [Package Extension Mechanism](#9-package-extension-mechanism)
10. [Kernel Configuration](#10-kernel-configuration)
11. [BSP Extension](#11-bsp-extension)
12. [Complete Walkthrough](#12-complete-walkthrough)
13. [Reference: Existing Targets](#13-reference-existing-targets)

---

## 1. Architecture Overview

```
kas/machine/<machine>.yml          KAS build entry point
        |
        +-- kas/base.yml           Core repos (OE-Core, meta-openembedded, meta-avocado)
        +-- kas/vendor/<v>.yml     Vendor BSP layer + package extension variables
        +-- kas/feature/<f>.yml    Optional features (TPM, virtualization)
        +-- kas/target/distro.yml  Distro target (meta-avocado-distro, meta-avocado-sdk)
        |
        +-- meta-avocado-<target>/
              |
              +-- conf/layer.conf                        Layer registration
              +-- conf/machine/avocado-<machine>.conf    Machine definition
              +-- conf/machine/include/<family>.inc       Family-shared machine settings (optional)
              +-- recipes-avocado/distro/                 avocado-stone.bbappend (profile wiring)
              +-- recipes-avocado/sdk/                    SDK target append + lifecycle scripts
              +-- recipes-avocado/packagegroups/          Target-specific packagegroups
              +-- recipes-bsp/                            U-Boot / extlinux / TF-A appends
              +-- recipes-kernel/linux/                   Kernel appends + config fragments
              +-- stone/stone-<machine>.json              Stone manifest
              +-- stone/<machine>/                        Per-profile provisioning scripts + helpers
        |
        +-- bsp/<machine-short-name>/
              +-- avocado.yaml                           BSP extension definition
```

---

## 2. Required Components Checklist

| # | Component | Path pattern | Required? |
|---|-----------|-------------|-----------|
| 1 | Meta-layer `conf/layer.conf` | `meta-avocado-<target>/conf/layer.conf` | Yes |
| 2 | Machine configuration | `meta-avocado-<target>/conf/machine/avocado-<machine>.conf` | Yes |
| 3 | Family include (multi-board layer) | `meta-avocado-<target>/conf/machine/include/<family>.inc` | Recommended for multi-board layers |
| 4 | KAS machine YAML | `kas/machine/<machine>.yml` | Yes |
| 5 | Stone manifest JSON | `meta-avocado-<target>/stone/stone-<machine>.json` | Yes |
| 6 | Provisioning scripts | `meta-avocado-<target>/stone/<machine>/stone-provision-*.sh` | Yes (for non-base profiles) |
| 7 | Distro `avocado-stone.bbappend` | `meta-avocado-<target>/recipes-avocado/distro/avocado-stone.bbappend` | If declaring stone profiles outside the base recipe set (e.g. `serial`, `emmc`) |
| 8 | SDK target bbappend | `meta-avocado-<target>/recipes-avocado/sdk/avocado-sdk-target.bbappend` | Yes |
| 9 | SDK lifecycle scripts | `meta-avocado-<target>/recipes-avocado/sdk/avocado-sdk-target/avocado-{build,provision}-<machine>` | Yes |
| 10 | Extra packagegroup | `meta-avocado-<target>/recipes-avocado/packagegroups/packagegroup-avocado-<target>-extra.bb` | Recommended |
| 11 | Kernel config fragments | `meta-avocado-<target>/recipes-kernel/linux/files/*.cfg` | If custom kernel |
| 12 | Kernel bbappend with avocado boilerplate | `meta-avocado-<target>/recipes-kernel/linux/<kernel>_%.bbappend` | Yes — see [Section 10](#10-kernel-configuration) |
| 13 | BSP extension | `bsp/<machine-short-name>/avocado.yaml` | Recommended |
| 14 | Security capability declaration | `AVOCADO_SECURITY_CAPABILITIES` in the machine conf | Yes — `""` if the machine delivers none; see [Security capabilities](#security-capabilities) |

---

## 3. Layer Configuration

Create a new meta-layer directory with a standard `conf/layer.conf`:

```bitbake
# meta-avocado-<target>/conf/layer.conf
BBPATH .= ":${LAYERDIR}"

BBFILES += "${LAYERDIR}/recipes-*/*/*.bb \
            ${LAYERDIR}/recipes-*/*/*.bbappend"

BBFILE_COLLECTIONS += "meta-avocado-<target>"
BBFILE_PATTERN_meta-avocado-<target> = "^${LAYERDIR}/"
BBFILE_PRIORITY_meta-avocado-<target> = "9"

LAYERDEPENDS_meta-avocado-<target> = "core"
LAYERSERIES_COMPAT_meta-avocado-<target> = "scarthgap"
```

---

## 4. Machine Configuration

The machine `.conf` file defines hardware-specific settings:

```bitbake
#@TYPE: Machine
#@NAME: <Human-readable machine name>
#@DESCRIPTION: <One-line description>

# Provisioning methods this machine supports
STONE_PROVISIONING ?= "img usb"

# Machine overrides for conditional logic
MACHINEOVERRIDES =. "<machine-short>:"

# Include base Avocado machine settings
require conf/machine/include/avocado.inc

# CPU tuning
DEFAULTTUNE ?= "<tune>"
require conf/machine/include/<arch>/tune-<tune>.inc

# Kernel provider
PREFERRED_PROVIDER_virtual/kernel = "linux-yocto"

# Machine features
MACHINE_FEATURES += "<features>"
```

### Key variables

| Variable | Purpose |
|----------|---------|
| `STONE_PROVISIONING` | Space-separated list of provisioning profiles (`img`, `pxe`, `usb`) |
| `MACHINEOVERRIDES` | Enables conditional recipe sections (e.g., `:append:<override>`) |
| `DEFAULTTUNE` | CPU instruction set target |
| `PREFERRED_PROVIDER_virtual/kernel` | Which kernel recipe to use |
| `EFI_PROVIDER` | Set to `"systemd-boot"` for UEFI targets, `""` for U-Boot targets |
| `AVOCADO_BOOTLOADER` | Boot method: `"uboot"` (U-Boot + TF-A, fwup disk assembly) or `"uefi"` (systemd-boot + GPT). Defaults to `uboot` in `conf/machine/include/avocado.inc`; x86 targets set `uefi`. Boot-artifact deps in the stone / img-bootfiles / SDK bbappends gate on it with `bb.utils.contains('AVOCADO_BOOTLOADER', ...)` rather than the machine name. |
| `KERNEL_IMAGETYPE` | `"bzImage"` for x86, `"Image"` for ARM64 |
| `AVOCADO_SECURITY_CAPABILITIES` | What this machine can deliver on the security side (`encrypted-var`, `verified-boot`, `ahab`, `ftpm`, `tpm2`). Declaring builds the tooling into the feed; the user's `avocado.yaml` decides per runtime whether to use it. Set it to `""` rather than leaving it unset once the machine has been assessed. See [Security capabilities](#security-capabilities). |
| `AVOCADO_VAR_PART_DEV` | The **plaintext** var partition — `/dev/disk/by-partlabel/var` (GPT layouts), `/dev/disk/by-partuuid/<uuid>` or `PARTUUID=<uuid>`, or a bare `/dev/<node>`; any other `/dev/disk/by-*` form fails the build. `/var` is mounted through `/dev/disk/by-avocado/var`, which follows an opened LUKS mapping automatically, so this never changes with encryption. `"none"` only when init mounts `/var` itself (Jetson). |

### Security capabilities

Every security feature is split in two: the machine **declares** what it can
deliver, and the user's `avocado.yaml` **chooses** whether a runtime uses it.
Yocto builds the declared capabilities into the feed unconditionally — kernel
options, initramfs tooling, rootfs helpers — and never turns them on by itself.
`docs/security-capabilities.md` is the full model; what a new machine needs:

1. **Declare.** `AVOCADO_SECURITY_CAPABILITIES = "encrypted-var"` (or `""`).
   `avocado-security-capabilities.bbclass` refuses a build that requests a
   build-time mode (`verified-boot`, `ahab`, `ftpm`, `tpm2`) the machine has not
   declared, and ships the declaration to the device as
   `/etc/avocado-security-capabilities`.
2. **Gate delivery on the declaration**, not on `DISTRO_FEATURES`:
   ```bitbake
   SRC_URI += "${@bb.utils.contains('AVOCADO_SECURITY_CAPABILITIES', 'encrypted-var', ' file://dm-crypt.cfg', '', d)}"
   ```
   The shared packagegroups already pull `cryptsetup-var` (initramfs) and
   `cryptsetup-var-udev` / `-posture` (rootfs) this way; a vendor layer adds its
   kernel fragment and a `cryptsetup-var.bbappend` with the machine's
   `var-key.sh` backend (see `meta-avocado-nxp/recipes-core/cryptsetup-var/`).

   That `var-key.sh` has a contract the build enforces, in two tiers, so a
   provider that does not carry it fails the build rather than shipping a
   machine that cannot unlock `/var`:

   ```sh
   # avocado-var-key-provider: usable
   # avocado-var-key-identity: /sys/devices/soc0/serial_number
   ROOT="${1:-}"
   SOC_UID_FILE="$ROOT/sys/devices/soc0/serial_number"
   ```

   One `avocado-var-key-identity:` line per file the provider reads its
   hardware identity from, and every one of those reads prefixed with the
   script's optional first argument. At `do_install` the recipe runs the
   installed provider against two synthetic identities and requires two
   *different* 64-byte keys, which is what catches a provider that emits a
   constant or that reads past the fixture into the build host. It then runs
   it against an empty fixture and requires it to REFUSE, which is what
   catches a provider that substitutes a constant when it finds no identity.
   On a device the provider is invoked with no arguments, so the prefix is
   empty.

   Your provider must refuse rather than fall back to a constant. A machine
   that cannot do that - a virtual target with no unique board identifier -
   declares `test-only` instead of `usable`, which skips the refusal check and
   warns when the check runs. It is not self-service: the waiver is honoured
   only for machines meta-avocado lists in
   `AVOCADO_VAR_KEY_TEST_ONLY_MACHINES`, so declaring it in a vendor layer does
   not grant it. Do not reach for it on real hardware: it means every
   board in the fleet derives the same `/var` key.

   Full statement in
   `meta-avocado/recipes-core/cryptsetup-var/README-deliverability.md`,
   "The var-key provider contract". Copy the nearest vendor provider, not the
   shared one under `meta-avocado/` - that one is deliberately marked
   `unusable`.
3. **Label the var partition `var`** in the stone manifest (GPT). Both
   `cryptsetup-var.service` and the `by-avocado/var` rule key on it; an MBR
   layout builds the tooling but cannot yet encrypt.
4. **Set `AVOCADO_VAR_PART_DEV`** to the plaintext partition (above).
5. **Prove both halves on hardware**: a runtime without `var.encrypt` boots a
   plaintext `/var`; one with it encrypts in place on first boot and reopens on
   the next.

`kas/feature/complete.yml` adds no security tokens — a declared capability is
built with or without it.

---

## 5. KAS Configuration

Create `kas/machine/<machine>.yml`:

```yaml
header:
  version: 16
  includes:
    - repo: meta-avocado
      file: kas/base.yml
    - repo: meta-avocado
      file: kas/vendor/<vendor>.yml    # if applicable
    - repo: meta-avocado
      file: kas/feature/tpm.yml        # optional features
    - repo: meta-avocado
      file: kas/target/distro.yml

repos:
  meta-avocado:
    path: meta-avocado
    layers:
      meta-avocado-<target>:

machine: avocado-<machine>
```

### Vendor KAS files

If the machine requires a vendor BSP layer (e.g., `meta-intel`, `meta-tegra`),
create or reference a `kas/vendor/<vendor>.yml` that pulls in the vendor repo
and sets any needed variables:

```yaml
header:
  version: 16
  includes:
    # meta-virtualization is REQUIRED -- packagegroup-avocado-extra in the
    # base meta-avocado layer RDEPENDs on docker, which lives in
    # meta-virtualization. Omitting this triggers a parse error:
    #   ERROR: Nothing RPROVIDES 'docker' (... packagegroup-avocado-extra
    #   RDEPENDS on or otherwise requires it)
    - repo: meta-avocado
      file: kas/feature/virtualization.yml
    # arm.yml pulls meta-arm + meta-arm-toolchain; only needed if the vendor
    # BSP requires meta-arm (most ARM64 BSPs do).
    - repo: meta-avocado
      file: kas/vendor/arm.yml

repos:
  <vendor-layer>:
    url: <repo-url>
    branch: scarthgap
    layers:
      .:

local_conf_header:
  vendor-<vendor>: |
    PKG_EXTRA_INSTALL:append = " packagegroup-avocado-<target>-extra"
    # virtualization + seccomp are REQUIRED for the avocado-extra packagegroup
    # to resolve (the meta-virtualization layer above is necessary but not
    # sufficient -- the DISTRO_FEATURES flag activates docker's PACKAGECONFIG).
    # opengl + wayland are conventional defaults; drop on headless targets.
    DISTRO_FEATURES_EXTRA:append = " opengl wayland seccomp virtualization"
```

### Hard requirements that bite first builds

Every avocado-distro target needs:

| Requirement | What it provides | Symptom if missing |
|---|---|---|
| `kas/feature/virtualization.yml` in vendor.yml `header.includes` | meta-virtualization layer (docker recipe) | `Nothing RPROVIDES 'docker'` from `packagegroup-avocado-extra` |
| `virtualization seccomp` in `DISTRO_FEATURES_EXTRA` | docker PACKAGECONFIG enablement | docker builds but fails QA, or runtime fails to launch containers |
| `kas/vendor/arm.yml` for ARM64 BSPs that need meta-arm | meta-arm + meta-arm-toolchain | LAYERDEPENDS unsatisfied during parse |
| Per-machine `avocado-build-${MACHINE_SHORT_NAME}` and `avocado-provision-${MACHINE_SHORT_NAME}` SDK lifecycle scripts under `meta-avocado-<target>/recipes-avocado/sdk/avocado-sdk-target/` | SDK-side `stone validate`/`create`/`provision` invocations | `Unable to get checksum for avocado-sdk-target SRC_URI entry avocado-build-<machine>` at do_fetch |

The SDK lifecycle scripts are machine-agnostic boilerplate -- copy any
existing one (e.g. `meta-avocado-raspberrypi/recipes-avocado/sdk/avocado-sdk-target/avocado-build-rpi`)
and rename to your machine. No edits to script body needed unless your
family does something exotic.

---

## 6. Stone Manifest

The stone manifest (`stone-<machine>.json`) defines:

- **Runtime metadata** — platform name, architecture, default provisioning profile, update strategy
- **Provisioning envs** — env-var bundles surfaced to the provisioning scripts (device identity, kernel cmdline overrides)
- **Provisioning profiles** — script mappings, declared envs, and host-side requirements
- **Storage device layout** — partition table, image filenames, optional FAT-image build args

### Modern (rolling/edge) layout — GPT A/B with FAT boot partition

This is the pattern current bring-ups (`rzv2n-sr-som`, `imx93-frdm`, `stm32mp25-dk`)
use. The kernel + DTB + initramfs + extlinux config live in a FAT boot
partition the bootloader probes; the rootfs is delivered as an A/B pair so
OTA updates can flip slots without touching the bootloader.

```json
{
  "runtime": {
    "platform": "avocado-<machine>",
    "architecture": "<arch>",
    "provision_default": "sd",
    "update_strategy": "gpt-ab"
  },
  "provision": {
    "envs": {
      "device_info": {
        "AVOCADO_DEVICE_CERT": "${AVOCADO_DEVICE_CERT}",
        "AVOCADO_DEVICE_KEY":  "${AVOCADO_DEVICE_KEY}",
        "AVOCADO_DEVICE_ID":   "${AVOCADO_DEVICE_ID}"
      },
      "cmdline": {
        "AVOCADO_CMDLINE_EXTRA": "${AVOCADO_CMDLINE_EXTRA}"
      }
    },
    "profiles": {
      "sd":     { "script": "stone-provision-sd.sh",     "envs": ["device_info", "cmdline"], "requires": ["usb"] },
      "emmc":   { "script": "stone-provision-emmc.sh",   "envs": ["device_info", "cmdline"], "requires": ["usb"] },
      "serial": { "script": "stone-provision-serial.sh", "envs": ["device_info"],            "requires": ["usb"] }
    }
  },
  "storage_devices": {
    "rootdisk": {
      "out": "avocado-<machine>-rootdisk.img",
      "devpath": "/dev/mmcblk0",
      "block_size": 512,
      "images": {
        "boot": {
          "out": "boot.img",
          "size": 256,
          "size_unit": "mebibytes",
          "build_args": {
            "type": "fat",
            "variant": "FAT32",
            "label": "BOOT",
            "files": [
              { "in": "Image", "out": "Image" },
              { "in": "<dtb>", "out": "<dtb>" },
              { "in": "avocado-image-initramfs-<machine>.cpio.zst", "out": "avocado-image-initramfs-<machine>.cpio.zst" },
              { "in": "extlinux.conf", "out": "extlinux/extlinux.conf" }
            ]
          }
        },
        "rootfs": "avocado-image-rootfs-<machine>.erofs-lz4",
        "var":    "avocado-image-var-<machine>.btrfs",
        "initramfs": "avocado-image-initramfs-<machine>.cpio.zst",
        "kernel": "Image"
      },
      "partitions": [
        { "name": "boot-a",   "image": "boot",   "partition_type": "EF00", "partition_uuid": "<uuid>", "offset": 1, "offset_unit": "mebibytes", "size": 256, "size_unit": "mebibytes" },
        { "name": "boot-b",                      "partition_type": "EF00", "partition_uuid": "<uuid>", "size": 256,  "size_unit": "mebibytes" },
        { "name": "rootfs-a", "image": "rootfs", "partition_type": "8305", "partition_uuid": "<uuid>", "size": 512,  "size_unit": "mebibytes" },
        { "name": "rootfs-b",                    "partition_type": "8305", "partition_uuid": "<uuid>", "size": 512,  "size_unit": "mebibytes" },
        { "name": "var",      "image": "var",    "partition_type": "8300", "partition_uuid": "4d21b016-b534-45c2-a9fb-5c16e091fd2d", "size": 1024, "size_unit": "mebibytes", "expand": "true" }
      ]
    }
  }
}
```

### Bootloader as an OS artifact (eMMC boot partitions)

A machine that boots `imx-boot` from an eMMC hardware boot partition can ship
the bootloader with each OS update by adding an `os_artifacts` entry whose slot
targets are `emmc-boot:0` / `emmc-boot:1` and an `activate`/`rollback` step
that runs `avocado-imx-bootpart {inactive_slot}` / `{previous_slot}` (see
`docs/security-capabilities.md`, "Bootloader updates"). Boot partitions are
coupled to OS slots (a → boot0, b → boot1). Provisioning must leave a valid
image in **both** boot partitions, or the first update to slot b is the first
thing to populate boot1 — `uuu`'s `flash bootloader` does write both.

Medium rule: the same manifest serves the machine's SD, image and eMMC
profiles. A target the running medium does not have is skipped with a message
(avocadoctl) and the activation helper exits 0, so OS updates keep working
from SD — only the bootloader is left as provisioned there. Any new
medium-specific target must follow the same rule.

### `expand: true` and how the device grows `/var`

`expand: "true"` on the last partition means "fill the disk". fwup can only do
that when it writes the real device (`sd` profile); an image written to a file
(`uuu`, `img`) is provisioned at the image size. So provisioning also records the
intent **on the disk**: stone sets GPT attribute bit 56 on that partition
(`AVOCADO_PARTITION_<NAME>_FLAGS` → `flags = ${VAR_PART_FLAGS}` in the fwup
template), and the initramfs unit `avocado-var-grow` extends any partition that
carries the bit to the end of its disk before `cryptsetup-var` opens it or
`var.mount` mounts it. The LUKS mapping and btrfs then grow to the new size in
the same boot. No manifest → no bit → nothing grows; a partition already at the
disk end is a no-op. A new GPT template must carry `flags = ${VAR_PART_FLAGS}`
on its var partition to take part; MBR layouts do not.

### Notes on partition layout

- The `var` partition UUID is canonical (`4d21b016-b534-45c2-a9fb-5c16e091fd2d`)
  across all Avocado machines — it's baked into the rootfs `/etc/fstab`. Do not
  generate a new one.
- Boot partitions use type `EF00` (EFI System) so the bootloader's distroboot
  scan finds them by GUID; rootfs slots use `8305` (Linux ARM root). For SoCs
  with a fixed first-stage offset (stm32mp2 FSBL, jetson tegra-bct, etc.) add
  the FSBL/FIP partitions before the GPT-AB block with explicit `offset` keys
  — `build-disk-image.sh` honours per-partition offsets.
- `rootfs-b` does NOT carry an `image` key; it's allocated empty and populated
  by the OTA agent on first slot flip.

### Legacy / EFI flat layout (x86-64, qemu)

Older targets without GPT-AB use a single rootfs partition and reference the
bootloader directly (no FAT staging):

```json
"images": {
  "rootfs": "avocado-image-rootfs-<machine>.squashfs",
  "kernel": "bzImage",
  "bootloader": "systemd-bootx64.efi"
}
```

---

## 7. Stone Provisioning Scripts

Each provisioning profile maps to a shell script. The base
`avocado-stone.bb` recipe ships SRC_URI overrides for `img`, `sd`, `usb`.
Profiles outside that set (e.g. `serial`, `emmc`) need to be wired up in
`avocado-stone.bbappend` — see Section 8a.

| Profile | Script | Purpose |
|---------|--------|---------|
| `img` | `stone-provision-img.sh` | Creates a raw disk image |
| `sd` | `stone-provision-sd.sh` | Builds GPT image + writes to host-attached SD |
| `usb` | `stone-provision-usb.sh` | Creates image + writes to USB device |
| `emmc` | `stone-provision-emmc.sh` | Flashes onboard eMMC via U-Boot fastboot |
| `serial` | `stone-provision-serial.sh` | Bootloader bootstrap via UART/USB-DFU |

For multi-stage targets (stm32mp2, rzv2n) the typical bring-up sequence is:
`serial` (bootstrap bootloader) → `emmc`/`sd` (install OS image).

### Environment variables available to scripts

| Variable | Description |
|----------|-------------|
| `AVOCADO_STONE_MANIFEST` | Path to the stone manifest JSON |
| `AVOCADO_STONE_BUILD_DIR` | Directory the script may write assembled images into |
| `AVOCADO_STONE_DATA_DIR` | Directory containing pre-built images (deploy dir) |
| `AVOCADO_PROVISION_OUT` | Output directory for deferred-write flows (Docker Desktop) |
| `AVOCADO_USB_PASSTHROUGH` | `1` if `/dev/ttyUSB*`/`/dev/sd*` are passthrough'd into the SDK; `0` for image-only output |
| `AVOCADO_DEVICE_CERT` / `AVOCADO_DEVICE_KEY` / `AVOCADO_DEVICE_ID` | Surfaced when the profile lists `device_info` in `envs` |
| `AVOCADO_CMDLINE_EXTRA` | Surfaced when the profile lists `cmdline` in `envs` |

### Sharing image-build logic across profiles

When sd / emmc / serial all need the same GPT image, factor the partition-
table walk into a `build-disk-image.sh` helper alongside the per-profile
scripts and ship it via `avocado-stone.bbappend` (see Section 8a).
[meta-avocado-renesas/stone/rzv2n-sr-som/build-disk-image.sh](../meta-avocado-renesas/stone/rzv2n-sr-som/build-disk-image.sh)
and
[meta-avocado-stm/stone/stm32mp25-dk/build-disk-image.sh](../meta-avocado-stm/stone/stm32mp25-dk/build-disk-image.sh)
are the reference implementations.

---

## 8. SDK Target Scripts

The SDK target bbappend wires up two things:
- `do_compile[depends]` on whichever recipes' `do_deploy` artifacts the
  provisioning scripts need to find at flash time (TF-A, OP-TEE, U-Boot,
  extlinux config).
- `RDEPENDS` on the nativesdk packages those scripts shell out to (jq,
  mtools/dosfstools, gptfdisk, dfu-util, fastboot).

```bitbake
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

# Stone bundle artifacts the provisioning scripts ship to the host.
do_compile[depends] += "u-boot-<vendor>:do_deploy"
do_compile[depends] += "trusted-firmware-a-<vendor>:do_deploy"
do_compile[depends] += "extlinux-<machine>:do_deploy"

RDEPENDS:${PN}:append = " \
  nativesdk-mtools \
  nativesdk-dosfstools \
  nativesdk-gptfdisk \
  nativesdk-util-linux-lsblk \
  nativesdk-util-linux-blockdev \
  nativesdk-dfu-util \
"
```

The two SDK lifecycle scripts (`avocado-build-<machine>` and
`avocado-provision-<machine>`) live under `${PN}/` and are target-agnostic in
content — they shell out to the stone CLI which dispatches to the
profile-specific provisioning script. Copy them verbatim from a reference
target and only rename the file (the avocado-cli tooling looks them up by
`MACHINE_SHORT_NAME` suffix).

### 8a. Distro `avocado-stone.bbappend`

Targets that declare profiles outside the base recipe set (`img`, `sd`,
`usb`) must wire those profiles' scripts into the build via an
`avocado-stone.bbappend`:

```bitbake
# In-tree deps the provisioning scripts pull from DEPLOYDIR.
do_compile[depends] += "u-boot-<vendor>:do_deploy"
do_compile[depends] += "trusted-firmware-a-<vendor>:do_deploy"
do_compile[depends] += "extlinux-<machine>:do_deploy"

DEPENDS += " jq-native"

# Shared image-builder helper used by every profile script.
SRC_URI += " file://build-disk-image.sh"

# Per-profile script overrides for profiles not in the base recipe.
SRC_URI:append:stone-emmc   = " file://stone-provision-emmc.sh"
SRC_URI:append:stone-serial = " file://stone-provision-serial.sh"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/build-disk-image.sh ${DEPLOYDIR}/build-disk-image.sh
}

do_deploy:append:stone-emmc() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/stone-provision-emmc.sh ${DEPLOYDIR}/stone-provision-emmc.sh
}

do_deploy:append:stone-serial() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/stone-provision-serial.sh ${DEPLOYDIR}/stone-provision-serial.sh
}
```

`stone-<profile>` is a `MACHINEOVERRIDES` element synthesized by `avocado.inc`
from the machine's `STONE_PROVISIONING` value, so the `:append:stone-<profile>`
overrides only fire when the corresponding profile is enabled.

---

## 9. Package Extension Mechanism

Avocado separates the **minimal rootfs** from **extended packages** available
in the package feed.  Extra packages are defined in a packagegroup and
referenced via `PKG_EXTRA_INSTALL` (typically set in the vendor KAS file).

```bitbake
# packagegroup-avocado-<target>-extra.bb
DESCRIPTION = "Extra packages for <target>"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup

RDEPENDS:${PN} = " \
  linux-firmware-<wifi> \
  kernel-modules \
  <additional-packages> \
"
```

The `kernel-modules` package is critical: it ensures that **all** kernel
modules built by the kernel recipe appear as individual packages in the
feed.  Without it, users won't be able to install individual
`kernel-module-<name>` packages.

Packagegroup `sdk-extras` (`packagegroup-avocado-sdk-extras`) can also be
extended to include additional nativesdk packages in the SDK.

---

## 10. Kernel Configuration

### Appending to the kernel recipe

Create a `linux-yocto_%.bbappend` (or appropriate kernel recipe append).
**Every avocado kernel bbappend must `inherit avocado-kernel-feed`** and pull
in the per-kernel module packagegroup `.inc`. Together they wire the kernel
into the avocado-cli kernel resolver, the auto-appended per-kernel module
packagegroups, and the fully-qualified `kernel-{devsrc,devicetree,modules}`
packaging that lets multiple kernel versions coexist in a rolling feed.

```bitbake
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

COMPATIBLE_MACHINE:<machine> = "<machine>"
KBUILD_DEFCONFIG:<machine> = "<defconfig>"

SRC_URI:append:<machine> = " \
    file://avocado-core.cfg \
    file://avocado-extra.cfg \
    file://<machine-specific>.cfg \
"

# Renames kernel-{devsrc,devicetree,modules} to include KERNEL_VERSION,
# republishes the unqualified Provide for back-compat callers, and emits the
# avocado-cli kernel-resolver virtual (`avocado-kernel-${KERNEL_VERSION}`).
# All four boilerplate blocks live in the bbclass; see
# meta-avocado/classes/avocado-kernel-feed.bbclass.
inherit avocado-kernel-feed

# Emit per-kernel rootfs/initramfs module packagegroups (renamed at packaging
# time to include KERNEL_VERSION). avocado-cli auto-appends the matching
# variant at install time so transitive module pulls resolve to this kernel's
# modules rather than dnf's NVR tie-break across the feed.
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
```

### Per-kernel boilerplate — what each piece does

| Block | Purpose | Required? |
|-------|---------|-----------|
| `SRC_URI` with `avocado-core.cfg` / `avocado-extra.cfg` | Avocado-required kernel config (CONFIG_RD_ZSTD, CONFIG_OVERLAY_FS, etc. — see "Required Kernel Options" below) | Yes |
| `inherit avocado-kernel-feed` | Provides: fully-qualified `kernel-{devsrc,devicetree,modules}-${KERNEL_VERSION}` PKG renames, unqualified+versioned `RPROVIDES` for back-compat, and `RPROVIDES:${KERNEL_PACKAGE_NAME}-base += "avocado-kernel-${KERNEL_VERSION}"` so avocado-cli's resolver can enumerate this kernel in the feed | Yes |
| `require .../avocado-kernel-modules-packagegroup.inc` | Emits `packagegroup-avocado-{rootfs,initramfs}-modules-${KERNEL_VERSION}` so avocado-cli can auto-append the correct kernel's modules at install time | Yes |

The boilerplate is additive and harmless in single-kernel feeds — it only
becomes load-bearing when the family adds an alt-kernel multiconfig (see
[multi-kernel.md](multi-kernel.md)). Adding it from day one means the
groundwork is in place if the family ever gains a second kernel.

If the family ships kernel-version-critical modules in the rootfs or
initramfs (block drivers, network for early boot, etc.), append them to
the auto-emitted packagegroup with versioned NAMEs — see
[multi-kernel.md](multi-kernel.md) for the pattern.

### Required Kernel Options for Avocado

Every Avocado target **must** include the following kernel config options in
`avocado-core.cfg` for the system to boot and function correctly:

```
# Initramfs decompression -- must match the initramfs compression format.
# Avocado uses .cpio.zst by default (see AVOCADO_IMAGE_INITRAMFS_TYPE).
# Without this, the kernel will silently hang after the bootloader hands off.
CONFIG_RD_ZSTD=y
CONFIG_RD_GZIP=y

# Root filesystem
CONFIG_OVERLAY_FS=y
CONFIG_SQUASHFS=y
CONFIG_SQUASHFS_ZSTD=y

# Block device support
CONFIG_BLK_DEV_LOOP=y
CONFIG_EFI_PARTITION=y
```

### EFI / UEFI targets (x86-64)

For EFI-booted targets (x86-64 with systemd-boot), the following are critical:

```
# ACPI must be explicitly enabled -- linux-yocto BSP metadata may disable it
# for certain KMACHINE values. Without ACPI, EFI and all dependent features fail.
CONFIG_ACPI=y

# EFI stub support
CONFIG_EFI=y
CONFIG_EFI_STUB=y

# Early console (allows earlycon=efifb on the kernel command line)
CONFIG_SERIAL_EARLYCON=y
CONFIG_EFI_EARLYCON=y

# Framebuffer console (required for display output)
CONFIG_FB=y
CONFIG_FB_EFI=y
CONFIG_FRAMEBUFFER_CONSOLE=y
CONFIG_VT=y
CONFIG_VT_CONSOLE=y
```

### Build Drivers as Modules

Avocado's design separates the minimal rootfs from installable extensions.
Mark hardware-specific drivers as modules (`=m`), not built-in (`=y`), so
they appear as individual `kernel-module-<name>` packages in the feed.

**Important:** The `linux-yocto` recipe includes a `yocto-kernel-cache` that
applies BSP-specific configuration metadata on top of your `.cfg` fragments.
This metadata can force certain options to built-in or disabled, overriding
your fragment values.  If a driver you marked as `=m` ends up built-in or
missing, check the kernel-cache `.scc` and `.cfg` files for your KMACHINE
value.  You can override specific kernel-cache settings by placing your
`.cfg` fragment **after** the cache is applied (kernel fragments listed in
`SRC_URI` are applied in order, last wins).

---

## 11. BSP Extension

The BSP extension (`bsp/<machine-short-name>/avocado.yaml`) defines the
runtime packages installed via the Avocado CLI when a user sets up a device.
This includes kernel modules, firmware, and userspace tools specific to the
hardware.

```yaml
default_target: <machine-short-name>
supported_targets:
  - <machine-short-name>

distro:
  release: 2024
  channel: edge

extensions:
  avocado-bsp-<machine-short-name>:
    version: 2024.1.0
    release: r0
    summary: Board support for <description>
    description: Board support for <description>
    license: Apache-2.0
    url: https://github.com/avocadolinux/avocado-os
    vendor: Avocado Linux <info@avocadolinux.org>

    types:
      - sysext
      - confext

    on_merge:
      - udevadm control --reload
      - udevadm trigger --type=subsystems --action=add --settle
      - udevadm trigger --type=devices --action=add --settle

    packages:
      # Bring-up: ship every kernel module via the kernel-modules meta-package.
      # Trim down to the lsmod set once the board boots cleanly.
      kernel-modules: '*'
      linux-firmware-<chip>: '*'

sdk:
  image: docker.io/avocadolinux/sdk:{{ avocado.distro.release }}-{{ avocado.distro.channel }}
```

### Important notes on BSP extension packages

- Only list packages that actually exist in the package feed.  Packages
  for kernel modules built as `=y` (built-in) do NOT appear in the feed
  and will cause "No match" errors during extension installation.
- Use `kernel-modules` in the packagegroup-extra recipe to ensure all
  modules are published to the feed.
- Test the extension with `avocado ext install` before releasing.

---

## 12. Complete Walkthrough

To add a new machine called `acme-widget`:

1. **Create the meta-layer**: `meta-avocado-acme/conf/layer.conf`
2. **Create the machine config**: `meta-avocado-acme/conf/machine/avocado-acme-widget.conf` (set `STONE_PROVISIONING ?= "..."`, `MACHINEOVERRIDES`, then `require conf/machine/include/avocado.inc`; declare `AVOCADO_SECURITY_CAPABILITIES` and set `AVOCADO_VAR_PART_DEV` to the plaintext var partition — see [Security capabilities](#security-capabilities))
3. **Create the KAS config**: `kas/machine/acme-widget.yml`
4. **Create the stone manifest**: `meta-avocado-acme/stone/stone-acme-widget.json`
5. **Create provisioning scripts**: `meta-avocado-acme/stone/acme-widget/stone-provision-*.sh` and (if shared) `build-disk-image.sh`
6. **Create distro `avocado-stone.bbappend`** (only if you declared profiles outside the base set): `meta-avocado-acme/recipes-avocado/distro/avocado-stone.bbappend`
7. **Create SDK target append**: `meta-avocado-acme/recipes-avocado/sdk/avocado-sdk-target.bbappend` plus the two SDK lifecycle scripts (`avocado-build-acme-widget`, `avocado-provision-acme-widget`) under `${PN}/`
8. **Create extra packagegroup**: `meta-avocado-acme/recipes-avocado/packagegroups/packagegroup-avocado-acme-extra.bb`
9. **Wire `PKG_EXTRA_INSTALL`**: edit `kas/vendor/<vendor>.yml` to append `packagegroup-avocado-acme-extra`
10. **Create kernel config fragments**: `meta-avocado-acme/recipes-kernel/linux/files/avocado-core.cfg` etc.
11. **Create kernel bbappend**: `meta-avocado-acme/recipes-kernel/linux/<kernel>_%.bbappend` with `inherit avocado-kernel-feed` and `require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc`
12. **Create BSP extension**: `bsp/acme-widget/avocado.yaml`
13. **Build**: `kas build distro/kas/machine/acme-widget.yml`
14. **Test**: Provision a device and verify boot, then test BSP extension installation with `avocado ext install bsp-acme-widget`.
15. **Test the security opt-in** (if `encrypted-var` is declared): build one runtime with `var.encrypt: true` and one without; the first must encrypt `/var` on first boot, the second must stay plaintext.

---

## 13. Reference: Existing Targets

| Machine | Layer | Bootloader | Provisioning | Notes |
|---------|-------|-----------|-------------|-------|
| `raspberrypi5` | `meta-avocado-raspberrypi` | U-Boot | img, sd, usb | Reference ARM target |
| `jetson-orin-nano` | `meta-avocado-nvidia` | U-Boot (CBoot) | tegraflash | NVIDIA Jetson, uses swupdate |
| `intel-x86-64-v2` | `meta-avocado-x86-64` | systemd-boot | img, usb | x86-64-v2 EFI target (SSE4.2, Atom-class) |
| `intel-x86-64-v3` | `meta-avocado-x86-64` | systemd-boot | img, usb | x86-64-v3 EFI target (AVX2, Core-class) |
| `intel-x86-64-v4` | `meta-avocado-x86-64` | systemd-boot | img, usb | x86-64-v4 EFI target (AVX-512) |
| `qemux86-64` | `meta-avocado-qemu` | U-Boot | img | QEMU testing |
| `imx93-evk` | `meta-avocado-nxp` | U-Boot | img, sd | NXP i.MX93 |
| `imx93-frdm` | `meta-avocado-nxp` | U-Boot | img, sd, uuu-emmc | NXP FRDM-IMX93, FAT boot + GPT-AB |
| `rzv2n-sr-som` | `meta-avocado-renesas` | U-Boot (TF-A FIP) | sd, emmc, serial | SolidRun RZ/V2N SoM, FAT boot + GPT-AB, USB-OTG fastboot |
| `stm32mp25-dk` | `meta-avocado-stm` | U-Boot (TF-A FIP + OP-TEE) | sd, emmc, serial | ST STM32MP257F-DK, FAT boot + GPT-AB, USB-DFU bootstrap |

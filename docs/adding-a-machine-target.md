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
| `KERNEL_IMAGETYPE` | `"bzImage"` for x86, `"Image"` for ARM64 |

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

### Carrying a device tree the vendor BSP does not ship

Nearly every target's device tree arrives inside a vendor BSP layer, and that is
the shape to prefer. When a board's dts exists only downstream, or has to be
forward-ported onto a newer kernel than the vendor targeted, two shapes work and
they fail differently:

| Shape | Use when | Failure mode |
|---|---|---|
| One patch carrying both the dts and its `Makefile` entry | The dts is close to final, or is a straight backport | `do_patch` fails loudly on any drift in either half |
| A loose `.dts` in `SRC_URI` installed at `do_configure`, plus a patch for the `Makefile` entry only | The dts is a first cut under active revision, and reviewers need to diff it against the vendor source | Silent: the install overwrites whatever is at that path |

The second shape keeps the dts reviewable as a file rather than as patch context,
which is worth having while a board is being brought up. It also has a trap that
the first does not: `install` will happily clobber a dts the kernel starts
shipping later, hiding the divergence, and the `Makefile` patch then fails on a
duplicate entry pointing nowhere near the cause. Guard it:

```bitbake
do_configure:prepend:<machine>() {
    if [ -e ${S}/arch/arm64/boot/dts/<vendor>/<board>.dts ]; then
        bbfatal "linux-<vendor> now ships <board>.dts. Drop the dts and Makefile patch from this bbappend and use the vendor copy."
    fi
    install -m 0644 ${WORKDIR}/<board>.dts \
        ${S}/arch/arm64/boot/dts/<vendor>/<board>.dts
}
```

`meta-avocado-renesas/recipes-kernel/linux/linux-renesas_%.bbappend` is the
worked example. Fold the dts into the patch once the board stops moving.

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
2. **Create the machine config**: `meta-avocado-acme/conf/machine/avocado-acme-widget.conf` (set `STONE_PROVISIONING ?= "..."`, `MACHINEOVERRIDES`, then `require conf/machine/include/avocado.inc`)
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

---

## 13. Reference: Existing Targets

| Machine | Layer | Bootloader | Provisioning | Notes |
|---------|-------|-----------|-------------|-------|
| `raspberrypi5` | `meta-avocado-raspberrypi` | U-Boot | img, sd, usb | Reference ARM target |
| `jetson-orin-nano-devkit` | `meta-avocado-nvidia` | U-Boot (CBoot) | tegraflash | NVIDIA Jetson, uses swupdate |
| `intel-x86-64-v2` | `meta-avocado-x86-64` | systemd-boot | img, usb | x86-64-v2 EFI target (SSE4.2, Atom-class) |
| `intel-x86-64-v3` | `meta-avocado-x86-64` | systemd-boot | img, usb | x86-64-v3 EFI target (AVX2, Core-class) |
| `intel-x86-64-v4` | `meta-avocado-x86-64` | systemd-boot | img, usb | x86-64-v4 EFI target (AVX-512) |
| `qemux86-64` | `meta-avocado-qemu` | U-Boot | img | QEMU testing |
| `imx93-evk` | `meta-avocado-nxp` | U-Boot | img, sd | NXP i.MX93 |
| `imx93-frdm` | `meta-avocado-nxp` | U-Boot | img, sd, uuu-emmc | NXP FRDM-IMX93, FAT boot + GPT-AB |
| `rzv2n-sr-som` | `meta-avocado-renesas` | U-Boot (TF-A FIP) | sd, emmc, serial | SolidRun RZ/V2N SoM, FAT boot + GPT-AB, USB-OTG fastboot |
| `stm32mp25-dk` | `meta-avocado-stm` | U-Boot (TF-A FIP + OP-TEE) | sd, emmc, serial | ST STM32MP257F-DK, FAT boot + GPT-AB, USB-DFU bootstrap |

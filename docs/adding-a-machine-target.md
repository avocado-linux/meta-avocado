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
              +-- conf/machine/include/<target>.inc       Shared machine settings (optional)
              +-- recipes-avocado/distro/                 Stone recipe append
              +-- recipes-avocado/sdk/                    SDK target scripts + append
              +-- recipes-avocado/packagegroups/          Target-specific packagegroups
              +-- recipes-kernel/linux/                   Kernel appends + config fragments
              +-- stone/                                  Stone manifest + provisioning scripts
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
| 3 | KAS machine YAML | `kas/machine/<machine>.yml` | Yes |
| 4 | Stone manifest JSON | `meta-avocado-<target>/stone/stone-<machine>.json` | Yes |
| 5 | Provisioning scripts | `meta-avocado-<target>/stone/<machine>/stone-provision-*.sh` | Yes |
| 6 | SDK target bbappend | `meta-avocado-<target>/recipes-avocado/sdk/avocado-sdk-target.bbappend` | Yes |
| 7 | Extra packagegroup | `meta-avocado-<target>/recipes-avocado/packagegroups/packagegroup-avocado-<target>-extra.bb` | Recommended |
| 8 | Kernel config fragments | `meta-avocado-<target>/recipes-kernel/linux/files/*.cfg` | If custom kernel |
| 9 | Kernel bbappend with avocado boilerplate | `meta-avocado-<target>/recipes-kernel/linux/<kernel>_%.bbappend` | Yes — see [Section 10](#10-kernel-configuration) |
| 10 | BSP extension | `bsp/<machine-short-name>/avocado.yaml` | Recommended |

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
STONE_PROVISIONING ?= "img peridio"

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
| `STONE_PROVISIONING` | Space-separated list of provisioning profiles (`img`, `pxe`, `usb`, `peridio`) |
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

repos:
  <vendor-layer>:
    url: <repo-url>
    branch: scarthgap
    layers:
      .:

local_conf_header:
  vendor-<vendor>: |
    PKG_EXTRA_INSTALL:append = " packagegroup-avocado-<target>-extra"
```

---

## 6. Stone Manifest

The stone manifest (`stone-<machine>.json`) defines:

- **Runtime metadata** (platform name, architecture, default provisioning profile)
- **Provisioning profiles** (script mappings)
- **Storage device layout** (image names, partitions)

```json
{
  "runtime": {
    "platform": "avocado-<machine>",
    "architecture": "<arch>",
    "provision_default": "img"
  },
  "provision": {
    "profiles": {
      "img": { "script": "stone-provision-img.sh" },
      "peridio": { "script": "stone-provision-peridio.sh" }
    }
  },
  "storage_devices": {
    "rootdisk": {
      "out": "avocado-image-<machine>",
      "devpath": "/dev/mmcblk0",
      "block_size": 512,
      "images": {
        "rootfs": "avocado-image-rootfs-<machine>.squashfs",
        "var": "avocado-image-var-<machine>.btrfs",
        "initramfs": "avocado-image-initramfs-<machine>.cpio.zst",
        "kernel": "bzImage",
        "bootloader": "systemd-bootx64.efi"
      }
    }
  }
}
```

---

## 7. Stone Provisioning Scripts

Each provisioning profile maps to a shell script. Common profiles:

| Profile | Script | Purpose |
|---------|--------|---------|
| `img` | `stone-provision-img.sh` | Creates a raw disk image |
| `usb` | `stone-provision-usb.sh` | Creates image + writes to USB device |
| `pxe` | `stone-provision-pxe.sh` | Prepares PXE/iPXE boot artifacts |
| `peridio` | `stone-provision-peridio.sh` | Creates swupdate .swu for OTA |

### Environment variables available to scripts

| Variable | Description |
|----------|-------------|
| `AVOCADO_STONE_MANIFEST` | Path to the stone manifest JSON |
| `AVOCADO_STONE_BUILD_DIR` | Build output directory |
| `AVOCADO_STONE_DATA_DIR` | Directory containing built images |
| `AVOCADO_PROVISION_OUT` | Optional output directory |

---

## 8. SDK Target Scripts

The SDK target bbappend adds nativesdk dependencies needed by the
provisioning scripts:

```bitbake
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

RDEPENDS:${PN}:append = " \
  nativesdk-mtools \
  nativesdk-gptfdisk \
"
```

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
**Every avocado kernel bbappend must include the boilerplate shown below**;
it wires the kernel into the avocado-cli kernel resolver, the auto-appended
per-kernel module packagegroups, and the fully-qualified kernel-devsrc
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

# Rename kernel-devsrc to include KERNEL_VERSION so multiple kernel versions
# can coexist in a rolling feed without colliding on the unversioned package
# name. Publish both the unqualified and the versioned virtual Provides so
# existing callers (e.g. `packagegroup-avocado-sdk-extra.bb` listing
# `kernel-devsrc`) keep working, and explicit pinners can target
# `kernel-devsrc-{{ avocado.kernel.version }}` via interpolation.
PKG:${KERNEL_PACKAGE_NAME}-devsrc = "${KERNEL_PACKAGE_NAME}-devsrc-${KERNEL_VERSION}"
RPROVIDES:${KERNEL_PACKAGE_NAME}-devsrc += "kernel-devsrc kernel-devsrc-${KERNEL_VERSION}"

# Same multi-kernel feed-collision rationale as kernel-devsrc above. The
# kernel-devicetree package emitted by kernel-devicetree.bbclass is not auto-
# renamed by kernel.bbclass, so two kernels' RPMs would land on the same NAME
# and dnf would NVR-tiebreak. Fully-qualify it so avocado-cli's `-${KERNEL_VERSION}`
# auto-suffix resolves to the resolver-pinned kernel.
PKG:${KERNEL_PACKAGE_NAME}-devicetree = "${KERNEL_PACKAGE_NAME}-devicetree-${KERNEL_VERSION}"
RPROVIDES:${KERNEL_PACKAGE_NAME}-devicetree += "kernel-devicetree kernel-devicetree-${KERNEL_VERSION}"

# Publish a well-known virtual that avocado-cli's kernel resolver queries
# with `dnf repoquery --whatprovides 'avocado-kernel-*' --provides`. Encodes
# KERNEL_VERSION in the Provide name so the resolver can enumerate every
# kernel available in the feed without fishing through package NAMEs or
# relying on kernel.bbclass's (nonexistent) unqualified `kernel` Provide.
RPROVIDES:${KERNEL_PACKAGE_NAME}-base += "avocado-kernel-${KERNEL_VERSION}"

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
| `PKG:${KERNEL_PACKAGE_NAME}-devsrc` rename | Fully-qualified `kernel-devsrc-${KERNEL_VERSION}` package name so multiple kernel versions can ship in the same feed without dnf NVR collision | Yes |
| `RPROVIDES:${KERNEL_PACKAGE_NAME}-devsrc` unqualified+versioned | Backward-compat for callers listing the unqualified `kernel-devsrc` (e.g. `packagegroup-avocado-sdk-extra.bb`) | Yes |
| `PKG:${KERNEL_PACKAGE_NAME}-devicetree` rename + `RPROVIDES` | Same as kernel-devsrc but for the device tree package emitted by `kernel-devicetree.bbclass`; harmless on x86 where the package is empty | Yes |
| `RPROVIDES:${KERNEL_PACKAGE_NAME}-base += "avocado-kernel-${KERNEL_VERSION}"` | avocado-cli kernel resolver contract — without this, the resolver can't enumerate this kernel in the feed | Yes |
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
  version: 0.1.0
  channel: apollo-edge

extensions:
  avocado-bsp-<machine-short-name>:
    version: '{{ avocado.distro.version }}'
    release: r0
    summary: Board support for <description>
    description: >
      <Longer description of what this BSP provides.>
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
      # List kernel-module-<name> packages, firmware, and tools
      kernel-module-<driver>: '*'
      linux-firmware-<chip>: '*'
      <userspace-tool>: '*'

sdk:
  image: docker.io/avocadolinux/sdk:{{ avocado.distro.channel }}
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
2. **Create the machine config**: `meta-avocado-acme/conf/machine/avocado-acme-widget.conf`
3. **Create the KAS config**: `kas/machine/acme-widget.yml`
4. **Create the stone manifest**: `meta-avocado-acme/stone/stone-acme-widget.json`
5. **Create provisioning scripts**: `meta-avocado-acme/stone/acme-widget/stone-provision-img.sh` (etc.)
6. **Create SDK target append**: `meta-avocado-acme/recipes-avocado/sdk/avocado-sdk-target.bbappend`
7. **Create extra packagegroup**: `meta-avocado-acme/recipes-avocado/packagegroups/packagegroup-avocado-acme-extra.bb`
8. **Create kernel config fragments**: `meta-avocado-acme/recipes-kernel/linux/files/avocado-core.cfg` etc.
9. **Create kernel bbappend**: `meta-avocado-acme/recipes-kernel/linux/linux-yocto_%.bbappend`
10. **Create BSP extension**: `bsp/acme-widget/avocado.yaml`
11. **Build**: `kas build kas/machine/acme-widget.yml`
12. **Test**: Provision a device and verify boot, then test BSP extension installation.

---

## 13. Reference: Existing Targets

| Machine | Layer | Bootloader | Provisioning | Notes |
|---------|-------|-----------|-------------|-------|
| `raspberrypi5` | `meta-avocado-raspberrypi` | U-Boot | img, peridio | Reference ARM target |
| `jetson-orin-nano-devkit` | `meta-avocado-nvidia` | U-Boot (CBoot) | img, peridio | NVIDIA Jetson, uses swupdate |
| `intel-x86-64-v2` | `meta-avocado-x86-64` | systemd-boot | img, pxe, usb, peridio | x86-64-v2 EFI target (SSE4.2, Atom-class) |
| `intel-x86-64-v3` | `meta-avocado-x86-64` | systemd-boot | img, pxe, usb, peridio | x86-64-v3 EFI target (AVX2, Core-class) |
| `intel-x86-64-v4` | `meta-avocado-x86-64` | systemd-boot | img, pxe, usb, peridio | x86-64-v4 EFI target (AVX-512) |
| `qemux86-64` | `meta-avocado-qemu` | U-Boot | img, peridio | QEMU testing |
| `imx93-evk` | `meta-avocado-nxp` | U-Boot | img, peridio | NXP i.MX93 |

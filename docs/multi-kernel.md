# Multi-Kernel Support for a Target Family

This guide covers adding a second (or third) kernel to an existing target
family — e.g., shipping linux-yocto 6.6 alongside linux-jammy-nvidia-tegra
5.15 on Jetson, or linux-raspberrypi 6.6 alongside 6.12 on RPi. The end
state is a unified package feed where every kernel is published with
fully-qualified NAMEs, and avocado-cli's kernel resolver can pin against
any of them via `kernel.version` in the lockfile.

For the basics of adding a single-kernel target, see
[adding-a-machine-target.md](adding-a-machine-target.md). The boilerplate
required on every avocado kernel bbappend (kernel-devsrc rename,
`avocado-kernel-${KERNEL_VERSION}` virtual, packagegroup require) is
documented there in Section 10 — that boilerplate is a prerequisite for
multi-kernel and harmless in single-kernel feeds, so it's required on
every kernel bbappend regardless of whether the family currently ships
one or many.

---

## Table of Contents

1. [When Multi-Kernel Is Needed](#1-when-multi-kernel-is-needed)
2. [Architecture Overview](#2-architecture-overview)
3. [Two Variants: Different Recipes vs Same Recipe Different Versions](#3-two-variants-different-recipes-vs-same-recipe-different-versions)
4. [Required Components Checklist](#4-required-components-checklist)
5. [Multiconfig Conf](#5-multiconfig-conf)
6. [Feature YML](#6-feature-yml)
7. [Machine YML Composition](#7-machine-yml-composition)
8. [The avocado-multikernel.bbclass](#8-the-avocado-multikernelbbclass)
9. [Kernel-Critical Modules in rootfs/initramfs](#9-kernel-critical-modules-in-rootfsinitramfs)
10. [Build, Verify, Inspect](#10-build-verify-inspect)
11. [Reference: Existing Multi-Kernel Families](#11-reference-existing-multi-kernel-families)

---

## 1. When Multi-Kernel Is Needed

Add multi-kernel support to a family when:

- Customers need a choice between a vendor BSP kernel (with proprietary
  drivers, e.g. NVIDIA L4T) and a mainline-track kernel (linux-yocto,
  linux-fslc) on the same hardware.
- The family is migrating from one kernel generation to another and you
  want both available in the feed during the transition (e.g. RPi 6.6 →
  6.12) so customers can pin via `kernel.version` and migrate on their
  own schedule.
- A specific kernel version is required for a feature (DKMS shim, BSP
  driver only built against one kernel) but you don't want to drop the
  default kernel for everyone.

If the family ships only one kernel and has no near-term plan to ship
two, multi-kernel is **not** needed. Just ensure the per-kernel boilerplate
in [adding-a-machine-target.md Section 10](adding-a-machine-target.md#10-kernel-configuration)
is in place — that's enough to publish a single kernel into a feed that
could later become multi-kernel.

---

## 2. Architecture Overview

```
kas/machine/<target>.yml
        |
        +-- kas/feature/multi-kernel-<family>.yml         <-- included automatically;
        |       |                                            no caller-side composition
        |       +-- BBMULTICONFIG += "<alt-mc-name>"
        |       +-- INHERIT += "avocado-multikernel"
        |       +-- AVOCADO_MULTIKERNEL_MC_RECIPES += "<mc>:<recipe> ..."
        |
        +-- kas/target/distro.yml
                |
                +-- target: avocado-distro

meta-avocado-<family>/conf/multiconfig/<alt-mc-name>.conf
        |
        +-- per-mc TMPDIR (always required)
        +-- per-mc BUILDHISTORY_DIR (required for same-recipe-different-version only)
        +-- PREFERRED_PROVIDER_virtual/kernel:forcevariable (different-recipe variant)
            OR
            PREFERRED_VERSION_<recipe>:forcevariable (same-recipe variant)

meta-avocado/classes/avocado-multikernel.bbclass
        |
        +-- on avocado-distro recipe only:
        |     +-- do_multikernel_merge[mcdepends] += "mc::<mc>:<recipe>:do_build" (per pair)
        |     +-- do_multikernel_merge() rsyncs ${TOPDIR}/tmp-${mc}/deploy/ -> ${DEPLOY_DIR}
        +-- runs after do_configure, before do_compile (avocado-repo-map)
```

After `kas build kas/machine/<target>.yml` completes, the default mc's
`tmp/deploy/` tree contains:

- All default-mc RPMs and the default kernel's RPMs
- All alt-mc kernel RPMs (kernel + kernel-modules + kernel-devsrc + per-kernel
  packagegroups, all KERNEL_VERSION-qualified)
- Both mcs' Pulp upload manifests merged into `tmp/deploy/pulp-uploads/`
- Each alt-mc recipe's own SPDX documents under
  `tmp/deploy/spdx/<version>/<mc>/`, and its cve-check results under
  `${CVE_CHECK_DIR}/<mc>/` - in a subdirectory rather than merged in place,
  because both mcs write the same recipe's document and result under one
  filename
- A unified `tmp/deploy/rpm/avocado-repo.map` covering every arch present

CI's Tekton task definition needs **zero changes** for multi-kernel — every
machine, multi-kernel-aware or not from the caller's POV, invokes the
same `kas build kas/machine/$M.yml:ci/...yml --target avocado-distro`
shape.

---

## 3. Two Variants: Different Recipes vs Same Recipe Different Versions

The two multi-kernel families today take different shapes, and the
distinction drives the multiconfig conf:

### Variant A — Different recipes (Jetson)

Default kernel is `linux-yocto` 6.6; alt is `linux-jammy-nvidia-tegra`
5.15. The two recipes have different `${PN}` values, so:

- `BUILDHISTORY_DIR_PACKAGE = ${BUILDHISTORY_DIR}/packages/${MULTIMACH_TARGET_SYS}/${PN}`
  has different paths for each — no per-mc BUILDHISTORY_DIR override needed.
- The multiconfig conf uses
  `PREFERRED_PROVIDER_virtual/kernel:forcevariable = "linux-jammy-nvidia-tegra"`
  to switch the kernel provider in the alt mc.

### Variant B — Same recipe, different versions (Raspberry Pi)

Both kernels are `linux-raspberrypi` at different `PV`s (6.6.x and 6.12.x).
Same `${PN}` means:

- Both mcs would write to identical `BUILDHISTORY_DIR_PACKAGE` paths,
  trigging `version-going-backwards` QA when 6.6 < 6.12. **Per-mc
  BUILDHISTORY_DIR is required** — anchor it under `${TMPDIR}` so it
  follows TMPDIR isolation automatically.
- The multiconfig conf uses
  `PREFERRED_VERSION_<recipe>:forcevariable = "6.6.%"` to pin the version
  in the alt mc; the provider stays the same.

### Picking your variant

| Question | Variant A | Variant B |
|----------|-----------|-----------|
| Are the two kernels different recipe names? | Yes | No (same recipe at different PVs) |
| Multiconfig override knob | `PREFERRED_PROVIDER_virtual/kernel:forcevariable` | `PREFERRED_VERSION_<recipe>:forcevariable` |
| Per-mc `BUILDHISTORY_DIR` required? | No | **Yes** |
| Per-mc `TMPDIR` required? | Yes | Yes |

Both variants share the rest of the infrastructure (feature yml, bbclass,
machine-yml composition).

---

## 4. Required Components Checklist

| # | Component | Path | Required? |
|---|-----------|------|-----------|
| 1 | Multiconfig conf | `meta-avocado-<family>/conf/multiconfig/<alt-mc-name>.conf` | Yes |
| 2 | Feature YML | `kas/feature/multi-kernel-<family>.yml` | Yes |
| 3 | Machine YML inclusion | `header.includes` in every `kas/machine/<target>.yml` of the family | Yes |
| 4 | Per-kernel bbappend boilerplate | Already on every avocado kernel bbappend (see [adding-a-machine-target.md §10](adding-a-machine-target.md#10-kernel-configuration)) | Prereq |
| 5 | `avocado-multikernel.bbclass` | `meta-avocado/classes/avocado-multikernel.bbclass` | Already exists; no per-family work |

---

## 5. Multiconfig Conf

Path: `meta-avocado-<family>/conf/multiconfig/<alt-mc-name>.conf`

The mc name should be readable and unambiguous. Conventions:

- Variant A (different recipe): name after the kernel flavor — e.g. `jetson-l4t`, `imx-mainline`.
- Variant B (different version): name after `<family>-<version-tag>` with underscores — e.g. `raspberrypi-6_6`. Avoid dots in mc names; avoid double-hyphen sequences (`6-6`) that read as ranges.

### Variant A example (`meta-avocado-nvidia/conf/multiconfig/jetson-l4t.conf`)

```bitbake
# meta-avocado-<family>/conf/machine/include/avocado-jetson.inc:5 hard-assigns
# PREFERRED_PROVIDER_virtual/kernel = "linux-yocto" and is loaded by every Jetson
# machine conf after this multiconfig conf. A plain `=` here gets clobbered;
# `:forcevariable` is the highest-precedence override and wins regardless of
# load order.
PREFERRED_PROVIDER_virtual/kernel:forcevariable = "linux-jammy-nvidia-tegra"

# Same MACHINE in two multiconfigs collides on bitbake's per-recipe WORKDIR
# (keyed on MACHINE_ARCH, NOT on multiconfig name). Per-mc TMPDIR is the only
# clean isolation; DEPLOY_DIR_RPM and other sub-trees inherit ${TMPDIR}, so
# they're per-mc too — required to avoid bitbake's "shared-area collision"
# detection on same-NEVRA sysroot recipes (glibc, libgcc, ...).
TMPDIR = "${TOPDIR}/tmp-jetson-l4t"
```

### Variant B example (`meta-avocado-raspberrypi/conf/multiconfig/raspberrypi-6_6.conf`)

```bitbake
# Both kernels are the same recipe (linux-raspberrypi) — only the version
# differs — so we override PREFERRED_VERSION rather than PREFERRED_PROVIDER.
# `:forcevariable` is robust against future `=` assigns in any machine.conf.
PREFERRED_VERSION_linux-raspberrypi:forcevariable = "6.6.%"

# Per-mc TMPDIR (same reason as Variant A).
TMPDIR = "${TOPDIR}/tmp-raspberrypi-6_6"

# BUILDHISTORY_DIR defaults to ${TOPDIR}/buildhistory, NOT under TMPDIR — so
# the per-mc TMPDIR isolation above does not carry buildhistory along.
# BUILDHISTORY_DIR_PACKAGE keys on ${MULTIMACH_TARGET_SYS}/${PN}; same MACHINE
# + same recipe means both mcs would write to identical paths and trip
# `version-going-backwards` when one PV is lower than the other. Anchoring
# BUILDHISTORY_DIR under TMPDIR ties this to the same per-mc isolation.
#
# Required ONLY for same-recipe-different-version (Variant B); Variant A
# (different recipes) sidesteps this because ${PN} differs.
BUILDHISTORY_DIR = "${TMPDIR}/buildhistory"
```

`MACHINE` is intentionally **not** set in either conf — it's inherited
from the default mc, so a single multiconfig conf works for every machine
in the family.

---

## 6. Feature YML

Path: `kas/feature/multi-kernel-<family>.yml`

Every multi-kernel family's feature yml is the same shape:

```yaml
header:
  version: 16

local_conf_header:
  feature/multi-kernel-<family>: |
    BBMULTICONFIG += "<alt-mc-name>"
    INHERIT += "avocado-multikernel"
    AVOCADO_MULTIKERNEL_MC_RECIPES += "<alt-mc-name>:<recipe1> <alt-mc-name>:<recipe2> ..."
```

`AVOCADO_MULTIKERNEL_MC_RECIPES` lists every alt-mc recipe whose RPMs
should land in the unified feed. For a kernel-only alt mc, list just the
kernel recipe. For Jetson, both the kernel and the OOT shim are listed
because nvidia-kernel-oot's RPMs need to ship alongside the kernel's
modules:

```yaml
AVOCADO_MULTIKERNEL_MC_RECIPES += "jetson-l4t:linux-jammy-nvidia-tegra jetson-l4t:nvidia-kernel-oot"
```

The feature yml has **no `target:` list** — the alt-mc recipe enters the
build graph via `mcdepends` synthesized in
[avocado-multikernel.bbclass](#8-the-avocado-multikernelbbclass), not via
bitbake target flags.

---

## 7. Machine YML Composition

Every machine yml in the family must include the family's
multi-kernel feature yml in `header.includes`. Place it **after** the
vendor yml (BBLAYERS must be set first so the multiconfig conf is
discoverable) and **before** the target yml:

```yaml
# kas/machine/<target>.yml
header:
  version: 16
  includes:
    - repo: meta-avocado
      file: kas/base.yml
    - repo: meta-avocado
      file: kas/vendor/<vendor>.yml
    - repo: meta-avocado
      file: kas/feature/multi-kernel-<family>.yml   # multi-kernel
    - repo: meta-avocado
      file: kas/feature/<other-features>.yml         # other features (virtualization, tpm)
    - repo: meta-avocado
      file: kas/target/distro.yml
```

Multi-kernel becomes the **standard build** for every machine in the
family. Callers do not compose multi-kernel onto the kas command line.

---

## 8. The `avocado-multikernel.bbclass`

Already exists at
`meta-avocado/classes/avocado-multikernel.bbclass`. No per-family
work needed — it's INHERIT'd globally from the feature yml's
`local_conf_header` and PN-guarded so it only takes effect on the
`avocado-distro` recipe.

What it does on `avocado-distro`:

1. **Synthesizes mcdepends** from `AVOCADO_MULTIKERNEL_MC_RECIPES`. Each
   `<mc>:<recipe>` pair becomes
   `do_multikernel_merge[mcdepends] += "mc::<mc>:<recipe>:do_build"`.
   This makes `bitbake avocado-distro` transitively build every alt-mc
   recipe — no caller-side `--target mc:...` flags needed.

2. **Adds `do_multikernel_merge`** between `do_configure` and `do_compile`
   on `avocado-distro`. The task rsyncs each
   `${TOPDIR}/tmp-${mc}/deploy/` tree into `${DEPLOY_DIR}`. Because it
   runs before `do_compile` (which calls
   `avocado-repo-map`'s `do_create_repo_map`), the regenerated
   `avocado-repo.map` sees the unified arch tree.

When `AVOCADO_MULTIKERNEL_MC_RECIPES` is empty (the bbclass is
INHERIT'd but the variable not set), the python anonymous block
early-returns and the task stays `noexec=1` — no work, no overhead, no
behavioral change vs. single-kernel builds.

---

## 9. Kernel-Critical Modules in rootfs/initramfs

The `avocado-kernel-modules-packagegroup.inc` required from every kernel
bbappend (see
[adding-a-machine-target.md §10](adding-a-machine-target.md#10-kernel-configuration))
emits two empty packagegroups per kernel:

- `packagegroup-avocado-rootfs-modules-${KERNEL_VERSION}`
- `packagegroup-avocado-initramfs-modules-${KERNEL_VERSION}`

avocado-cli auto-appends the matching variant at install time keyed on
the lockfile's pinned kernel.version. To pull kernel-version-critical
modules into rootfs/initramfs, append to the packagegroup with **versioned
NAMEs** in the kernel bbappend:

```bitbake
# Modules that must be in the initramfs to bring the rootfs storage online.
# Versioned with ${KERNEL_VERSION} so dnf resolves to this kernel's module
# RPMs rather than NVR-tie-breaking across a multi-kernel feed.
RDEPENDS:packagegroup-avocado-initramfs-modules:append = " \
    kernel-module-nvme-${KERNEL_VERSION} \
    kernel-module-pcie-tegra194-${KERNEL_VERSION} \
"
```

The `-${KERNEL_VERSION}` suffix is critical. An unqualified
`kernel-module-nvme` reference would NVR-tiebreak in dnf and could pull
the wrong kernel's module package, breaking initramfs assembly.

If a module is needed in **both** the rootfs and initramfs (e.g.,
`kernel-module-zram` when DISTRO_FEATURES contains `zram`), append to
both packagegroups. The shared inc file already does this for `zram`.

---

## 10. Build, Verify, Inspect

### Build

```bash
cd build-<machine>
kas build meta-avocado/kas/machine/<machine>.yml
```

The build runs both the default mc (full distro, image, the lot) and the
alt mc (just the kernel + OOT recipes listed in
`AVOCADO_MULTIKERNEL_MC_RECIPES` plus their transitive deps), then
merges. No post-build rsync command needed.

### Verify the unified feed

```bash
# Both kernels' base packages exist:
ls build/tmp/deploy/rpm/<arch>/ | grep -E 'kernel-(base|image)'

# kernel-devsrc is fully qualified per kernel:
ls build/tmp/deploy/rpm/<arch>/ | grep kernel-devsrc-

# avocado-cli resolver discovers both kernels:
dnf repoquery --whatprovides 'avocado-kernel-*' --provides --repo=local

# avocado-repo.map covers both mcs' arches:
cat build/tmp/deploy/rpm/avocado-repo.map
```

### Verify alt-mc artifacts merged

```bash
# Pulp manifests from both mcs (when INLINE_PULP_UPLOAD=true):
ls build/tmp/deploy/pulp-uploads/*.jsonl | wc -l

# The alt kernel recipe's own SPDX documents and cve-check results, each
# in its own subdirectory:
ls build/tmp/deploy/spdx/3.0.1/<alt-mc-name>/ | head
ls build/tmp/deploy/cve/$MACHINE/<alt-mc-name>/

# tmp-<mc>/deploy/ tree exists from the alt mc but its contents are
# already mirrored into the default mc's tmp/deploy/:
ls build/tmp-<alt-mc-name>/deploy/rpm/
```

### Verify avocado-cli kernel pinning

Pin `kernel.version = "<version>.*"` in `avocado.yaml`, run
`avocado pkg sync`, and confirm the rootfs/initramfs auto-append picked
up the matching `packagegroup-avocado-{rootfs,initramfs}-modules-<version>`
package.

---

## 11. Reference: Existing Multi-Kernel Families

| Family | Default kernel | Alt kernel(s) | mc name | Variant | Multiconfig conf |
|--------|----------------|---------------|---------|---------|------------------|
| Jetson | linux-yocto 6.6 | linux-jammy-nvidia-tegra 5.15 + nvidia-kernel-oot | `jetson-l4t` | A (different recipes) | `meta-avocado-nvidia/conf/multiconfig/jetson-l4t.conf` |
| Raspberry Pi | linux-raspberrypi 6.12 | linux-raspberrypi 6.6 | `raspberrypi-6_6` | B (same recipe, different versions) | `meta-avocado-raspberrypi/conf/multiconfig/raspberrypi-6_6.conf` |

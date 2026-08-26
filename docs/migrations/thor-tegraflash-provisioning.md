# Thor (Jetson AGX Thor) Tegraflash Provisioning

How we got `avocado provision dev --profile tegraflash-nvme` working for
the Jetson AGX Thor devkit (T264) running NVIDIA's *unified-flash* Python
toolchain inside the avocado SDK container.

This is companion material to [scarthgap-to-wrynose.md](scarthgap-to-wrynose.md).
The Thor work happened during the same migration window but is its own
story — Thor is the first board in the fleet that requires NVIDIA's new
`unified_flash/` Python tools (the legacy `tegra234-flash-helper.sh`
shell flow doesn't cover T264), and that toolchain makes a number of
host-environment assumptions that don't hold inside our container.

---

## What's actually different about Thor

| Concern | Orin (T23x) | Thor (T264) |
|---|---|---|
| Flash flow | `tegra234-flash-helper.sh` (shell) | `unified_flash/tools/flashtools/bootburn/flash_bsp_images.py` (Python) |
| Reboot at end of flash | Implicit via USB `authorized` deauthorize | None — flow exits with device still in flashing initramfs |
| UEFI cmdline on cold boot | Includes `boot.slot_suffix=`, `root=`, etc. | Only `bl_prof_dataptr=...` `bl_prof_ro_ptr=...` |
| PCIe controller driver (NVMe path) | `pcie-tegra194` (in-tree, kernel feed) | `pcie-tegra264` (OOT, ships in `nvidia-kernel-oot/updates/`) |
| TOS image | `tos-optee_t234.img` | `tos-optee_t264.img` |
| Hafnium SPMC | not used | `hafnium_t264.fip` |
| BL31 / standalone-mm | tegra234 | tegra264 (`standalonemm_jetson.pkg`) |
| UEFI binaries | `uefi_t23x_*` | `uefi_t26x_*` |
| Flash layout file | `flash.xml.in` | `rcmboot-flash.xml.in` (generated from PARTITION_LAYOUT_RCMBOOT) |
| ADB use | optional, partition writer fallback | **required** — Python flow drives writes through adbd in the device-side flashing initramfs |

The container also makes life harder than NVIDIA's reference SDK Manager
flow: no `udevadm`, no system `/sys/bus/usb` write access on every host,
and the host's block devices are exposed to the container by default —
we don't want NVIDIA's tools touching `/dev/nvme0n1` thinking it's a
flashing target when it's actually the developer's laptop SSD.

---

## Recipe-side fixes

### `tegraflash-bsp`

[meta-avocado-nvidia/recipes-bsp/tegraflash/tegraflash-bsp.bb](../../meta-avocado-nvidia/recipes-bsp/tegraflash/tegraflash-bsp.bb)
collects the L4T BSP artifacts that the on-host flash flow consumes. Thor
required these adjustments:

- **`virtual/bootloader` + prebuilt providers.** The recipe used to
  `DEPENDS` directly on `edk2-firmware-tegra`; Thor flips to UEFI
  prebuilts (`tegra-uefi-prebuilt`, `edk2-nvidia-standalone-mm-prebuilt`,
  `edk2-firmware-tegra-rcmboot-prebuilt` — wired up via
  `kas/vendor/nvidia.yml`). Switched the dep to `virtual/bootloader` so
  either source works.
- **`L4T_BSP_DIR` path.** wrynose changed where the L4T sources land
  (`sources/` is now an explicit subdirectory) — the recipe's `cp -a`
  steps were silently no-oping for `.bin` / `.img` / `.fw` / `eks` /
  generic copies. Fixed the path.
- **`FLASH_HELPER_SCRIPT:tegra264 = "tegra-flash-helper.sh"`.** Thor uses
  meta-tegra's unified helper unmodified (our former `tegra264-flash-helper.sh`
  was a stale upstream snapshot with no avocado logic and was dropped). Only
  tegra234 keeps a local `tegra234-flash-helper.sh`, for the ODMDATA
  env-precedence fix upstream lacks. Before: hardcoded to t234.
- **`TOSIMGFILENAME:tegra234 / :tegra264`.** Per-SoC TOS filename — the
  unified-flash Python expects `tos-optee_t264.img` for Thor and breaks
  out `unsigned customer data` if it can't find it.
- **Hafnium + standalone-mm.** Tegra264-only `do_deploy:depends` and
  copy steps for `hafnium_t264.fip` and `standalonemm_jetson.pkg`. These
  are required inputs to the rcmboot blob on Thor.
- **UEFI bin glob extended to `t26x`.** The deploy step was matching
  `uefi_t23x_*` only; Thor needs `uefi_t26x_general.bin` and friends.
- **`rcmboot-flash.xml.in` generation.** Thor's RCM-boot flow expects a
  separate XML; recipe now generates it from `PARTITION_LAYOUT_RCMBOOT`.
- **`IST_RTID` strip.** Added to the `process_flash_xml` strip list —
  upstream layout includes an IST partition Avocado doesn't ship.

### `tegraflash-tools-deploy`

[meta-avocado-nvidia/recipes-bsp/tegraflash/tegraflash-tools-deploy.bb](../../meta-avocado-nvidia/recipes-bsp/tegraflash/tegraflash-tools-deploy.bb)
deploys NVIDIA's host-side Python flash toolchain. Three edits were
needed for SDK use:

- **Shebang rewrite.** NVIDIA's `unified_flash/tools/flashtools/**/*.py`
  files ship with `#!/usr/bin/python3` (absolute path). In the SDK
  container that resolves to the host's `/usr/bin/python3`, which lacks
  `PyYAML` and the rest of the nativesdk Python deps. We rewrite to
  `#!/usr/bin/env python3` so PATH lookup picks the nativesdk python at
  `${AVOCADO_SDK_PREFIX}/usr/bin/python3` (which has `PyYAML` from
  `nativesdk-python3-pyyaml`). Without this Step 5 of the T264 flow
  dies with `ModuleNotFoundError: No module named 'yaml'` inside
  `create_bsp_images.py`.
- **`wr_sh.sh` shebang + perms fix.** NVIDIA ships
  `unified_flash/tools/flashtools/flash/wr_sh.sh` with a typo'd shebang
  (`#/bin/sh` — missing the `!`) and mode `0644`. When pushed to the
  device with `adb push` and exec'd, exec(2) returns ENOEXEC because of
  the bad shebang, and the +x bit is missing so the shell fallback
  doesn't fire either. Net: every flash dies with `Permission denied`
  (rc 126). Fix both at deploy time.
- **`strip-udevadm.py`** runs at `do_deploy` time to apply ~20 source
  patches to the deployed Python. See next section.

### `strip-udevadm.py` — surgical patches to NVIDIA's Python

NVIDIA's unified-flash Python makes a number of host-environment
assumptions that don't hold inside the container.
[meta-avocado-nvidia/recipes-bsp/tegraflash/files/strip-udevadm.py](../../meta-avocado-nvidia/recipes-bsp/tegraflash/files/strip-udevadm.py)
applies them at deploy time. Despite the name, it now does much more
than just strip udevadm — kept the original name to avoid sstate churn.

The patch categories, with the file each batch targets:

#### `bootburn_lib.py` — flashing entry point

- **udevadm → sysfs.** NVIDIA's `bootburn_t264_py/bootburn_lib.py` calls
  `udevadm` to resolve `/dev/bus/usb/<bus>/<dev>` paths to canonical
  `/sys/devices/...` paths for `tegrarcm` USB instance arguments.
  `udevadm` is unavailable in the SDK container (no
  `nativesdk-systemd`; `nativesdk-eudev` would be the heavy dep that
  gets us a stub binary). Replaced with sysfs-only equivalents using
  the per-USB-device symlink at `/sys/dev/char/<major>:<minor>`. Mirrors
  the analogous container-aware sysfs replacements already in
  `initrd-flash.sh`.
- **`f_NvDDTool` resolution.** `select_socgrp`'s `sys.path` mutation
  causes `flash_utilities` to load as two distinct module objects;
  `target_config` mutates one, `bootburn_lib` reads the other.
  Side-stepped by computing the `nvdd` path from `__file__` /
  `shutil.which()` rather than relying on the class default.
- **`CopyTegraSign` tolerance.** Several `Copy(file, dest)` loops
  iterated over a hard-coded list of artefacts (`xmss-sign`, `oemkey`,
  dev-keys, `flash_lz4`, …) that aren't present in our build. Wrapped
  the loops to skip missing files instead of aborting.
- **`UpdatePVITFullFlashing` / `UpdatePVITPartialFlashing`.** Tolerant
  of missing optional inputs.
- **`resizeFilesystem` `losetup` lookup.** Used a hardcoded path to
  `losetup`; switched to PATH-based `shutil.which()` and tolerate the
  binary being absent (skip resize step instead of aborting).

#### `bootburn_adb.py` — ADB push/pull/shell wrappers

- **udevadm → sysfs**, same pattern as above.
- **PATH-based binary lookup** for the same set of host helpers.
- **`getBlockDeviceSize` (host-side fallback).** NVIDIA's helper called
  `losetup` to size loopback files; replaced with `os.stat` so the
  losetup dep goes away.

#### `flash_utilities.py`

- **Class default paths computed from `__file__`.** Same dual-module
  hazard as `bootburn_lib.py` — class-level defaults are evaluated at
  import time, before `select_socgrp` decides which module wins.
  Resolving from `__file__` makes the defaults stable regardless of
  load order.

#### `bootburn_parser.py`

- **`flash_lz4` / dev-keys tolerance.** Same pattern as `CopyTegraSign`
  — accept absent optional artefacts.

The script is **idempotent and self-healing** — re-deploying picks up
already-patched files and skips them, and it can detect prior broken
patches and restore them to upstream-pristine before re-applying. This
matters because we iterate on these patches while debugging.

---

## Provision-script fixes

### `stone-provision-tegraflash.sh`

[meta-avocado-nvidia/stone/tegra/stone-provision-tegraflash.sh](../../meta-avocado-nvidia/stone/tegra/stone-provision-tegraflash.sh)
is the per-board provisioning script invoked by `avocado provision`.

- **`PYTHONWARNINGS=ignore::SyntaxWarning`.** NVIDIA's
  `tegraflash_impl_t264.py` uses `break` inside `finally` blocks
  (PEP 765, SyntaxWarning in 3.14, SyntaxError in 3.16). Suppress the
  noise until upstream fixes it.
- **Defensive `adb start-server` pre-warm.** NVIDIA's
  `flash_bsp_images.py` runs `adb start-server` once and treats failure
  as fatal. On a fresh container, the *first* `start-server` call
  triggers `~/.android/adbkey` RSA keygen which races the daemon ACK
  timeout — so the first call returns "failed to start daemon" even
  though the daemon eventually comes up. We call `adb start-server`
  twice in a subshell with relaxed shell flags + outer `|| true` so the
  second call sees the warm daemon and the actual flash call later
  doesn't fight the keygen race.
- **SoC-aware TOS copy.** Reads `TOSIMGFILENAME` from `.env.initrd-flash`
  (set by `tegraflash-bsp` recipe) and copies the TOS to the
  SoC-correct destination filename. Falls back to the t234 name for
  older BSPs that don't emit the env var.

### `initrd-flash.sh` — Thor flow

[meta-avocado-nvidia/recipes-bsp/tegra-binaries/tegra-helper-scripts/initrd-flash.sh](../../meta-avocado-nvidia/recipes-bsp/tegra-binaries/tegra-helper-scripts/initrd-flash.sh)
is the NVIDIA-derived host-side flash driver. Two Thor-specific changes
in the `CHIPID = 0x26` branch:

- **`adb shell reboot -f` after successful flash.** NVIDIA's
  `bootburn_t264_py/bootburn_lib.py:FlashImages` ends with
  `# self.AdbCleanup` (commented out) and `os.chdir(cwd)` — no reboot.
  The legacy T23x flow rebooted implicitly via the USB `authorized`
  deauthorize hook that the device-side initramfs honored; the T264
  flashing initramfs has no such hook. Without an explicit reboot the
  device sits forever in the flashing initramfs running adbd. We
  capture `PIPESTATUS[0]` from `doflash.sh` and, if zero, locate the
  bundled `unified_flash/tools/flashtools/flash/adb` (or fall back to
  PATH) and call `adb shell reboot -f`. Plain `adb reboot` does not work:
  the device-side `adbd64` implements it via the Android `sys.powerctl`
  property, which nothing serves in the flashing initramfs (adbd logs
  `reboot (reboot,adb) failed`). The call returns non-zero because the
  device disconnects mid-call — that's expected, the reboot has been
  issued. T264 then keeps the RCM boot mode across that warm reset and
  re-enumerates as the boot-ROM APX device (`0955:7026`) instead of
  cold-booting, so the script waits up to 60 s for it with
  `find-jetson-usb --wait` and sends `tegrarcm_v2 --chip 0x26 0 --reboot
  coldboot`. If the device never reappears it booted on its own.
- **Device-side `reboot` restored.** meta-tegra's `tegra-target-flash-scripts`
  sed drops NVIDIA's `/sbin/reboot` wrapper (`busybox reboot -f`) along with
  the mount block; with bash as PID 1, bare busybox `reboot` is a no-op.
  `recipes-bsp/tegra-binaries/tegra-target-flash-scripts_%.bbappend`
  reinstates it as an update-alternative (priority 100 > busybox 50).
- **End-of-script disconnect verification.** The chip-independent
  final-disconnect block previously logged
  `WARN: Cannot write to /sys/bus/usb/devices/<inst>/authorized` even
  on the success path, because by the time we reach it the device is
  already gone (post `adb shell reboot -f` — exactly what we want). Updated to
  poll up to 5s for the device to disappear, and to log
  `Device already detached — flash completed cleanly` instead of WARN
  when the path doesn't exist. WARN now fires only when a *known-
  attached* device fails to deauthorize.

---

## Container hygiene

### Host disk exposure

The default container args mounted `-v /dev:/dev` so adb / lsblk could
see the Jetson when it landed as a USB mass-storage device. The
side effect: NVIDIA's flash tools see the host's `/dev/nvme0n1` (the
developer's laptop SSD) and could write to it. Caught this when a flash
log printed `Write failed on (/dev/nvme0n1)` — the Jetson's NVMe is
`nvme0n1` *on the device*, but the tool was happily talking to the
host disk.

Recommended remediation (Option A): swap the blanket `-v /dev:/dev` for
USB-only mounts (`/dev/bus/usb`) plus a passthrough rule for the Jetson
device node when in adb mode. Tracked separately — not yet landed at
time of writing.

---

## Boot-time fixes (post-flash)

These showed up after a flash succeeded but the freshly-booted Thor
couldn't find its rootfs.

### `avocado-tegra-init` — robust slot detection

[meta-avocado-nvidia/recipes-core/avocado-tegra-init/files/avocado-tegra-init](../../meta-avocado-nvidia/recipes-core/avocado-tegra-init/files/avocado-tegra-init)
is the initramfs-time helper that locates `APP` / `APP_b` and mounts
`/sysroot`. Worked on Orin, failed on Thor — `[FAILED] Failed to start
Detect and mount APP_<slot> partition`.

Root cause was twofold and we fixed both:

1. **Thor's UEFI passes essentially no userland-relevant cmdline.**
   `/proc/cmdline` is just `bl_prof_dataptr=... bl_prof_ro_ptr=...` —
   no `boot.slot_suffix=`, no `root=`. The original script bailed when
   neither was present.
2. **The `BootChainOsCurrent` EFI variable attribute byte differs.**
   Upstream's check expects `6` (BS+RT). NVIDIA's OTA scripts write
   `7` (NV+BS+RT), and the firmware on Thor appears to set `7`.

Reworked the script to use four detection paths in priority order
(mostly ported from upstream
`meta-tegra/recipes-core/initrdscripts/tegra-minimal-init/platform-preboot.sh`,
with extensions):

1. `boot.slot_suffix=` from cmdline (unchanged — works on Orin).
2. `BootChainOsCurrent` EFI variable, accepting attribute byte **6 or
   7**, with `set -e`-safe `hexdump || true`.
3. `root=` from cmdline (`UUID=`, `PARTUUID=`, `PARTLABEL=`, `LABEL=`,
   `/dev/...`).
4. Last-ditch: scan every disk for `PARTLABEL=APP` or `APP_b`.

On final failure, dumps `/proc/cmdline`, `blkid`, and `lsblk -o
NAME,PARTLABEL,SIZE` to the journal so the next failure is
self-diagnosing. (That diagnostic is what told us Path 4 had nothing
to find — only `zram0` — which led to the next problem.)

### `nvidia-kernel-oot` — Thor PCIe driver in initramfs

The Path-4 diagnostic showed only `zram0` in `lsblk` — meaning the
NVMe never enumerated. Comparing the Thor *flashing* initramfs (which
*does* see the NVMe) against our *boot* initramfs:

```
# Flashing initramfs (works)
insmod .../updates/drivers/pci/controller/pcie-tegra264.ko   ← OOT, missing in our boot initramfs
insmod .../kernel/drivers/phy/tegra/phy-tegra194-p2u.ko
insmod .../kernel/drivers/pci/controller/dwc/pcie-tegra194.ko
insmod .../kernel/drivers/nvme/host/nvme-core.ko
insmod .../kernel/drivers/nvme/host/nvme.ko
```

`pcie-tegra264.ko` is **out-of-tree** — it ships in
`nvidia-kernel-oot/updates/drivers/pci/controller/`, not in any
`kernel-module-pcie-*` package in the kernel feed. The in-tree
`pcie-tegra194` driver doesn't bind to Thor's `compatible =
"nvidia,tegra264-pcie"` nodes; the only thing that binds is `pcie-host-
generic`, which only catches the GPU's internal root complex (10de:22e6),
not the three `a8084x0000.pcie` controllers that carry the NVMe and
other endpoints.

Fix:
[nvidia-kernel-oot_%.bbappend](../../meta-avocado-nvidia/recipes-kernel/nvidia-kernel-oot/nvidia-kernel-oot_%.bbappend)
now appends `kernel-module-pcie-tegra264-${KERNEL_VERSION}` to
`packagegroup-avocado-initramfs-modules-oot` under the `:tegra264`
MACHINEOVERRIDE (auto-derived from `SOC_FAMILY="tegra264"` via
`openembedded-core/meta/conf/machine/include/soc-family.inc`). Orin
builds (`SOC_FAMILY="tegra234"`) are unaffected.

The OOT package name pattern is `nv-kernel-module-pcie-tegra264-...`
but `oot_update_rprovides` (also in that bbappend) emits the
unqualified `kernel-module-pcie-tegra264-${KERNEL_VERSION}` Provides,
so the dependency string follows the same convention as the kernel-feed
modules listed in `linux-noble-nvidia-tegra_%.bbappend`.

---

## Open items

- **`/dev:/dev` exposure.** Container args still expose the host
  filesystem. Move to USB-only mounts.
- **Multi-kernel.** Disabled in
  [kas/machine/jetson-{orin-nano,agx-thor}-devkit.yml](../../kas/machine/)
  during the migration because of OOT virt-storage modpost gaps. Reinstate
  once `tegra_vblk` resolves `NV_OOT_TEGRA_HV_SKIP_BUILD`.
- **chromium.** Disabled in
  [packagegroup-avocado-extra.bb](../../meta-avocado/recipes-avocado/packagegroups/packagegroup-avocado-extra.bb)
  via empty `BROWSER_PACKAGES` because `libclang_rt` paths now include
  `TARGET_VENDOR=-avocado` and the upstream chromium recipe doesn't
  account for it. Re-enable once that resolves.
- **`*.py SyntaxWarning`.** Suppressed via `PYTHONWARNINGS`. Drop the
  workaround when NVIDIA fixes the `break`-in-`finally` upstream or we
  carry a localised patch in `tegraflash-tools-deploy`.

---

## Verification checklist

A full Thor flash should produce:

```
[Flashing finished Successfully!! 232 seconds]
Issuing 'adb reboot' to leave flashing initramfs...
Device already detached — flash completed cleanly
```

…and the freshly-booted device should show:

```
tegra264-pcie a808400000.pcie: PCIe Controller-1 Link is UP
tegra264-pcie a808480000.pcie: PCIe Controller-5 Link is UP
nvme nvme0: pci function 0005:01:00.0
nvme0n1: p1 p2 p3 p4 p5 p6 p7 p8 p9 p10 p11 p12 p13 p14 p15 p16
```

…followed by `avocado-tegra-init` mounting `/sysroot` from the APP
partition without the `[FAIL]` fallback paths firing.

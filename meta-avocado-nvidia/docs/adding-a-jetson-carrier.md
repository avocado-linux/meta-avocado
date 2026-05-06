# Adding a new carrier to an existing Jetson SOM target

This guide walks through bringing up a new carrier board on top of an
existing SOM-targeted Yocto MACHINE in avocado-os, without authoring a
new MACHINE config. The worked example is the Advantech ICAM-540 — an
Orin NX SOM in a custom Advantech carrier — running on top of the
generic `jetson-orin-nx` MACHINE.

## Why this pattern

Historically each Jetson product got its own Yocto MACHINE — one
per carrier-on-SOM combination (e.g. the now-retired
`avocado-jetson-agx-orin-devkit` and `avocado-icam-540`, each with
their own kas yml, stone manifest, and SDK-target hooks). That works,
but every new carrier required a fresh recipe set and customers
couldn't really add their own.

The new pattern splits the BSP at the SOM/carrier boundary:

- The Yocto MACHINE is **SOM-targeted** (e.g. `avocado-jetson-orin-nx`).
  It produces the comprehensive tegraflash BSP for every variant of
  the SOM family — meta-tegra ships every SKU's DTBs, BCT files, BPMP
  DTBs, SDRAM init dts, and pinmux dtsi in the same `tegraflash-bsp/`
  output. Selection is by reference, not by what's built.
- The **carrier** is a BSP extension under `bsp/<carrier>/`. It contributes:
  - a `stone/carrier-bsp/` overlay with carrier-specific files (DTB,
    BPMP DTB, BPMP firmware, etc.)
  - a `carrier.env` declaring which references in `flashvars` /
    `.env.initrd-flash` to retarget at provision time (DTB, pinmux,
    SDRAM BCT, ODMDATA, board ID/SKU, …)
  - regular extension content: kernel-module package list,
    `on_merge:` hooks, `modprobe:`, optional confext `overlay/etc/*`
    for hostname etc.

The same SOM MACHINE serves the reference DevKit (as one carrier
extension) and any number of custom carriers. Customers with their own
boards add `bsp/<my-carrier>/` and never touch the MACHINE config.

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│ avocado-os Yocto MACHINE: avocado-jetson-orin-nx           │
│   - require orin-nx.inc + devkit-wifi.inc                  │
│   - produces full P3768/P3767 tegraflash-bsp                │
│   - stone-jetson-orin-nx.json declares                      │
│     tegraflash_carrier_bsp: "carrier-bsp"                   │
└────────────────────────────────────────────────────────────┘
                            ▲
                            │ avocado.target = jetson-orin-nx
                            │
┌────────────────────────────────────────────────────────────┐
│ Carrier BSP extension: bsp/<carrier>/                       │
│   default_target: jetson-orin-nx                            │
│   stone_include_paths: [stone]                              │
│   stone/carrier-bsp/                                        │
│     ├── carrier.env  (CARRIER_FV_* / CARRIER_ENV_*)         │
│     ├── <custom DTB>.dtb                                    │
│     ├── <custom BPMP DTB>.dtb                               │
│     └── <custom BPMP firmware>.bin                          │
│   overlay/etc/hostname  (optional)                          │
│   packages: { kernel-module-*, … }                          │
└────────────────────────────────────────────────────────────┘
```

At avocado-cli build time, `stone create` walks `-i <input>` paths in
this order: extension first, runtime input dir, SDK stone dir last.
The carrier extension's `carrier-bsp/` wins over the empty stub the
Yocto build deploys (the stub exists only so the Yocto-time
`do_stone_validate` task passes — see
[recipes-bsp/tegraflash/tegraflash-bsp.bb](../recipes-bsp/tegraflash/tegraflash-bsp.bb)).

At provision time,
[stone-provision-tegraflash.sh](../stone/tegra/stone-provision-tegraflash.sh)
overlays the carrier-bsp/ files onto the staged tegraflash-bsp/ working
directory (so same-named files shadow MACHINE-baked defaults), sources
`carrier.env`, and applies the `CARRIER_FV_<NAME>` / `CARRIER_ENV_<NAME>`
overrides to `flashvars` and `.env.initrd-flash` before invoking
`initrd-flash`.

## Step-by-step: adding a new carrier

The following walks through what was done for `bsp/icam-540/`.
Substitute your own carrier name and SOM-specific values.

### 1. Create the BSP extension directory

```
mkdir -p bsp/<my-carrier>/{stone/carrier-bsp,overlay/etc}
```

### 2. Author `bsp/<my-carrier>/avocado.yaml`

```yaml
default_target: jetson-orin-nx
supported_targets:
  - jetson-orin-nx

distro:
  release: 2024
  channel: edge

extensions:
  avocado-bsp-<my-carrier>:
    version: 0.1.0
    release: r0
    summary: Board support for <my-carrier> (carrier extension on jetson-orin-nx)
    license: <your license>
    url: <your repo URL>
    vendor: <your name>

    types:
      - sysext
      - confext

    # The carrier overlay files in stone/ are made available to stone
    # via stone_include_paths. Path is relative to this extension's
    # src_dir (= avocado-os/bsp/<my-carrier>/).
    stone_include_paths:
      - stone

    # Optional confext overlay — anything here gets merged onto /
    # at runtime via systemd-confext. Use this for /etc/hostname,
    # /etc/udev/rules.d/, /etc/modules-load.d/, etc.
    overlay: overlay

    # Auto-load any kernel modules required at first boot.
    modprobe:
      - <module-1>

    # Shell commands run when the extension is merged at boot.
    on_merge:
      - udevadm control --reload
      - udevadm trigger --type=subsystems --action=add --settle
      - udevadm trigger --type=devices --action=add --settle
      - nvbootctrl verify

    # Carrier-specific kernel module packages. The shared Orin NX
    # base list lives in bsp/jetson-orin-nx/avocado.yaml — only add
    # what's *additional* for this carrier here.
    packages:
      kernel-module-<carrier-driver>: '*'
```

### 3. Create `bsp/<my-carrier>/stone/carrier-bsp/carrier.env`

This is the heart of the carrier override. Two generic knob shapes:

- `CARRIER_FV_<NAME>=value` — patches `<NAME>=value` in `flashvars`.
- `CARRIER_ENV_<NAME>=value` — patches `<NAME>=value` in `.env.initrd-flash`.

Files referenced by name must exist in the merged BSP — either in the
MACHINE-baked `tegraflash-bsp/` (for variants meta-tegra already ships,
e.g. SKU-specific pinmux / sdram dtsi), or in this overlay alongside
`carrier.env` (for vendor-specific files not in upstream meta-tegra).

Worked example for the iCAM-540
([carrier.env](../../../bsp/icam-540/stone/carrier-bsp/carrier.env)):

```
CARRIER_LABEL="Advantech ICAM-540 (P3768-0000 + P3767-0001 Orin NX 16GB)"

# Kernel DTB — Advantech-specific (-nv suffix carries proper CSI/NVCSI
# for the ICAM500 camera). Shipped in this overlay (not in upstream
# meta-tegra), see step 4.
CARRIER_ENV_DTBFILE="tegra234-p3768-0000+p3767-0001-nv.dtb"

# BPMP DTB / firmware — Advantech variants. Shipped in this overlay.
CARRIER_FV_BPFDTB_FILE="tegra234-bpmp-3767-0001-3509-a02.dtb"
CARRIER_FV_BPF_FILE="bpmp_t234-TE980M-A1_prod.bin"

# Pinmux + pad-voltage dtsi — HDMI variants. Already in the
# MACHINE-baked tegraflash-bsp/, just retargeted here.
CARRIER_FV_PINMUX_CONFIG="tegra234-mb1-bct-pinmux-p3767-hdmi-a03.dtsi"
CARRIER_FV_PMC_CONFIG="tegra234-mb1-bct-padvoltage-p3767-hdmi-a03.dtsi"

# SDRAM init — SKU 0001. Default jetson-orin-nx is SKU 0000; without
# these the MB1 DRAM alias check fails with "Read/write mis-match".
CARRIER_FV_WB0SDRAM_BCT="tegra234-p3767-0001-wb0sdram-l4t.dts"
CARRIER_ENV_EMMC_BCTS="tegra234-p3767-0001-sdram-l4t.dts"

# EEPROM compare values — accept SKU 0001 SOM. Default MACHINE bakes
# 3767 / 0000; without these, signing aborts with "actual board SKU
# X does not match expected board SKU Y".
CARRIER_FV_CHECK_BOARDID="3767"
CARRIER_FV_CHECK_BOARDSKU="0001"
```

#### Common knobs reference

`flashvars` knobs (set via `CARRIER_FV_<NAME>`):

| Variable | Purpose |
|---|---|
| `CHECK_BOARDID`, `CHECK_BOARDSKU` | EEPROM compare values; mismatch aborts signing |
| `BPFDTB_FILE`, `BPF_FILE` | BPMP DTB and firmware; SOM-keyed |
| `PINMUX_CONFIG`, `PMC_CONFIG` | Pinmux + pad-voltage dtsi (often carrier-keyed for display variants) |
| `WB0SDRAM_BCT` | Warm-boot SDRAM init dts; SKU-specific |
| `MB2BCT_CFG`, `BR_CMD_CONFIG`, `DEV_PARAMS`, `DEV_PARAMS_B`, `DEVICEPROD_CONFIG`, `DEVICE_CONFIG`, `GPIOINT_CONFIG`, `MISC_CONFIG`, `PROD_CONFIG`, `SCR_CONFIG`, `PMIC_CONFIG`, `MINRATCHET_CONFIG`, `UPHY_CONFIG` | SOM/carrier-keyed BCT configs |
| `OVERLAY_DTB_FILE`, `PLUGIN_MANAGER_OVERLAYS`, `BOOTCONTROL_OVERLAYS` | Runtime DTBO selection |
| `RCM_UEFI_IMAGE`, `UEFI_IMAGE`, `TBCDTB_FILE` | Bootloader binaries / templates |

`.env.initrd-flash` knobs (set via `CARRIER_ENV_<NAME>`):

| Variable | Purpose |
|---|---|
| `DTBFILE` | Kernel DTB filename to flash |
| `EMMC_BCTS` | Primary SDRAM init dts (despite the name) |
| `ODMDATA` | UPHY lane / GBE config string |
| `ROOTFS_DEVICE`, `BOOTDEV`, `EXTERNAL_ROOTFS_DRIVE`, `NO_INTERNAL_STORAGE`, `ROOTFS_IMAGE`, `LNXFILE`, `FLASH_HELPER`, `DATAFILE` | Per-profile boot/storage retargeting |

The list isn't exhaustive — anything in either file can be patched
with `CARRIER_FV_*` / `CARRIER_ENV_*`. Unknown keys log a warning and
get skipped.

### 4. Add carrier-specific binary files to `stone/carrier-bsp/`

If your carrier needs files that aren't in upstream meta-tegra (custom
DTB, custom BPMP firmware, etc.), drop them into
`bsp/<my-carrier>/stone/carrier-bsp/` next to `carrier.env`. They're
copied as part of the overlay step and shadow any same-named MACHINE
file.

For the iCAM-540, these are six files (~2.5 MB total):

- `tegra234-p3768-0000+p3767-0001-nv.dtb` — kernel DTB
- `tegra234-bpmp-3767-0001-3509-a02.dtb` — BPMP DTB
- `bpmp_t234-TE950M-A1_prod.bin`, `bpmp_t234-TE980M-A1_prod.bin` — BPMP firmware
- `tegra234-dcb-p3767-0000-hdmi.dtbo`, `tegra234-p3768-0000+p3767-0000-dynamic.dtbo` — runtime DTBOs

If the canonical bytes are already deployed somewhere else in the
distro (e.g. `recipes-kernel/nvidia-kernel-oot/files/<board>/` or
`recipes-bsp/tegra-binaries/tegra-bootfiles/<board>/`), commit the
files to your BSP extension as a copy — **don't symlink across
directories**. The BSP extension is bind-mounted into the SDK
container at `/opt/_avocado/<target>/includes/<ext-name>/`, and any
relative symlink that escapes the bind mount will silently break stone
copy at provision time.

### 5. (Optional) ship `/etc/hostname` and other confext content

Drop files under `bsp/<my-carrier>/overlay/etc/` to have them merged
onto `/etc/` at boot via systemd-confext. Most common use:

```
echo "<my-carrier>" > bsp/<my-carrier>/overlay/etc/hostname
```

without this the device identifies as the SOM target name (e.g.
`avocado-jetson-orin-nx login:`). The `overlay:` field in the BSP yaml
must point at this directory (relative to the extension's src_dir).

### 6. Use it from a project

Customer / test project `avocado.yaml`:

```yaml
default_target: jetson-orin-nx
supported_targets:
  - jetson-orin-nx

runtimes:
  dev:
    extensions:
      - avocado-ext-dev
      - avocado-ext-sshd-dev
      - avocado-bsp-<my-carrier>
      - app
    packages:
      avocado-runtime: "*"

extensions:
  avocado-bsp-<my-carrier>:
    source:
      type: path
      path: /path/to/avocado-os/bsp/<my-carrier>
  # ... avocado-ext-dev, etc.

sdk:
  image: docker.io/avocadolinux/sdk:2024-edge
```

Then:

```
avocado build
avocado provision dev
```

Watch for these lines in the provision output to confirm the carrier
overlay took effect:

```
Carrier-BSP overlay: /opt/_avocado/<target>/.../carrier-bsp (<N> file(s))
  Carrier: <label from CARRIER_LABEL>
  flashvars: <NAME>=<value>
  .env.initrd-flash: <NAME>=<value>
  ...
```

If you see `Carrier-BSP slot empty (no overrides; using MACHINE-baked
defaults)`, the extension's `stone/carrier-bsp/` didn't reach the
bundle — typically because the consumer project's `extensions:` array
doesn't include your BSP extension, or because the avocado-cli binary
is older than the version that emits absolute container paths for
remote-extension include paths.

If you see `WARNING: CARRIER_FV_<NAME> target not found in flashvars;
skipped`, the carrier.env declared a knob whose target variable isn't
present in the MACHINE-baked `flashvars` (or `.env.initrd-flash`).
The parser refuses to append new lines defensively — silently adding
unknown vars can break the flash flow. Either remove the unused knob
from carrier.env, or fix the variable name (a typo is the most common
cause).

## Caveats

- **EEPROM SKU mismatch aborts signing.** If the actual SOM SKU
  doesn't match `CHECK_BOARDSKU` in flashvars, tegraflash refuses to
  sign with `actual board SKU X does not match expected board SKU Y`.
  Always set `CARRIER_FV_CHECK_BOARDSKU` to the SOM SKU you expect on
  the carrier.
- **Wrong SDRAM dts bricks DRAM init.** SKU 0000 vs 0001 SDRAM params
  are not compatible. Without `CARRIER_FV_WB0SDRAM_BCT` and
  `CARRIER_ENV_EMMC_BCTS`, MB1 reports `SDRAM initialized!` then fails
  the alias check with `Read/write mis-match`.
- **Wrong BCT pinmux can brick a SOM.** Pinmux dtsi is part of the
  bootloader BCT and is flashed to QSPI. Picking a dtsi that drives
  the wrong pin function on a power-related GPIO can leave the SOM
  unrecoverable. Test pinmux changes carefully and have a known-good
  recovery path.
- **Carrier files via symlinks across directories don't work.** The
  extension's working tree is bind-mounted into the SDK container, so
  a symlink whose target is outside the extension dir resolves to a
  non-existent path inside the container. Stone's copy step then
  silently skips the file (or worse, errors mid-copy and leaves an
  empty target dir). Commit copies, not links.

## Future work

- **First-class `hostname:` field** on the extension config (mirrors
  the existing `users:` schema) — would replace the manual
  `overlay/etc/hostname` step.
- **Common Tegra BSP SDK package** — factor the bulk of the
  meta-tegra `tegraflash-bsp/` into a `nativesdk-tegra-bsp-common`
  package available to all Jetson targets via SDK. BSP extensions
  would then ship only their per-carrier delta.
- **Provision-time SOM-SKU detection** — read EEPROM at provision
  time and pick the right `CARRIER_FV_*` set automatically rather
  than requiring per-carrier configuration up front.

## See also

- [bsp/icam-540/avocado.yaml](../../../bsp/icam-540/avocado.yaml) — full worked example
- [bsp/icam-540/stone/carrier-bsp/carrier.env](../../../bsp/icam-540/stone/carrier-bsp/carrier.env) — carrier override values
- [stone-jetson-orin-nx.json](../stone/stone-jetson-orin-nx.json) — SOM stone manifest with `tegraflash_carrier_bsp` slot
- [stone-provision-tegraflash.sh](../stone/tegra/stone-provision-tegraflash.sh) — carrier overlay + flashvars/env patching at provision time
- [tegraflash-bsp.bb](../recipes-bsp/tegraflash/tegraflash-bsp.bb) — Yocto-time empty `carrier-bsp/` stub for `do_stone_validate`
- avocado-cli `get_stone_include_paths_for_runtime` — composes runtime + per-extension paths, scoped to extension location for remote sources
